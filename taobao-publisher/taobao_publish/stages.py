# -*- coding: utf-8 -*-
"""阶段注册表与执行器。

阶段划分与抖店 v4 同构（``session → upload_images → ... → submit``），进度回调
签名也刻意保持一致：``progress_callback(pct, msg, step_name, steps)``。
这样前端 ``UploadStepInfo`` / ``UploadTaskSummary`` 那套类型可以零改动复用。

与抖店 v4 的**关键差异**（都是淘宝特有的约束）：

* 抖店 v4 一上来就建 WebSocket 干活；淘宝这边 ``session`` 阶段只读
  ``/json/list``，因为发布页的 DOM 结构一条都没实证，贸然连接没有意义。
* 抖店有 webpack 注入这条「协议捷径」；淘宝没有对应物（外部调研已实证官方
  API 对集市卖家关闭），因此淘宝只剩 mtop 协议与 DOM 两条路，两条都还没取证。
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from collections import OrderedDict
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Dict, List, Optional, Sequence

from .authorization import WriteAuthorization
from .cdp import SessionProbe, probe_session, snapshot_from_probe
from .constants import (
    STAGE_LABELS,
    STAGE_PRECHECK,
    STAGE_READBACK,
    STAGE_SESSION,
    STAGE_SUBMIT,
    CATEGORY_PAGE_URL,
    STAGE_WRITE_OPERATION,
)
from .contracts import Contracts, load_contracts
from .errors import Blocker, TaobaoPublishError, dedupe_blockers
from . import locating
from .models import (
    STEP_CANCELLED,
    STEP_FAILED,
    STEP_OK,
    STEP_RUNNING,
    STEP_SKIPPED,
    STAGE_PCTS,
    PublishItem,
    StepRecord,
)
from .preflight import PageSnapshot, PreflightResult, run_preflight
from .media_manifest import PreparedProductMedia

#: 进度回调签名，与抖店 v4 的 ``progress_callback(pct, msg, step_name, steps)`` 一致。
ProgressCallback = Callable[[int, str, str, List[Dict[str, Any]]], None]

#: 会话探测器签名。默认用 :func:`taobao_publish.cdp.probe_session`；
#: 测试与已持有浏览器句柄的调用方可以替换它。
SessionProbeFn = Callable[[str], SessionProbe]


# ---------------------------------------------------------------------------
# 运行上下文与结果
# ---------------------------------------------------------------------------
@dataclass
class PipelineContext:
    """一次发布的运行上下文。阶段处理器只读这个对象。"""

    item: PublishItem
    authorization: WriteAuthorization = field(default_factory=WriteAuthorization.none)
    contracts: Optional[Contracts] = None
    dry_run: bool = True
    cdp_list_url: str = ""
    snapshot: Optional[PageSnapshot] = None
    artifacts_dir: str = ""
    progress: Optional[ProgressCallback] = None
    #: 会话探测器注入点。``None`` 时用默认实现（真实探测 9334）。
    session_probe: Optional[SessionProbeFn] = None
    #: 取消钩子。返回 True 表示「不要再往下走了」。
    #:
    #: **只在阶段边界检查**——阶段内部（例如一次上传）不会被打断，因为半途中断会
    #: 留下说不清的状态。这与 ``/api/taobao/publish/cancel`` 承诺的语义一致：
    #: 「已请求取消，将在阶段边界停止」。
    #:
    #: 为什么不复用 ``progress`` 回调抛异常：``emit_progress`` **刻意吞掉**回调异常
    #: （前端渲染问题不该毁掉发布），所以抛异常根本停不下来。
    should_cancel: Optional[Callable[[], bool]] = None
    prepared_media: Optional[PreparedProductMedia] = None
    account_profile: str = ''
    #: 阶段间共享的可变状态（例如 session 探到的页面事实）。
    scratch: Dict[str, Any] = field(default_factory=dict)

    def cancelled(self) -> bool:
        """是否已请求取消。钩子自身抛错时按**未取消**处理并如实记录。

        取消钩子连的是 sidecar 的任务表；它出问题不该导致流水线异常中止——
        那种情况下「继续跑」比「莫名其妙停住」更容易排查。
        """

        if self.should_cancel is None:
            return False
        try:
            return bool(self.should_cancel())
        except Exception:  # noqa: BLE001 - 见 docstring
            self.scratch["cancel_hook_error"] = True
            return False

    def resolved_contracts(self) -> Contracts:
        return self.contracts if self.contracts is not None else load_contracts()


@dataclass
class StageOutcome:
    """单个阶段的执行结果。"""

    ok: bool = True
    status: str = STEP_OK
    summary: str = ""
    error_code: str = ""
    data: Dict[str, Any] = field(default_factory=dict)
    blockers: List[Blocker] = field(default_factory=list)

    @classmethod
    def skipped(cls, summary: str) -> "StageOutcome":
        return cls(ok=True, status=STEP_SKIPPED, summary=summary)

    @classmethod
    def failed(cls, error_code: str, summary: str, blockers: Optional[Sequence[Blocker]] = None,
               data: Optional[Dict[str, Any]] = None) -> "StageOutcome":
        """失败结果。

        :param data: **失败时的诊断明细**。为什么失败也要能带数据：早先只带
            `summary` + `blockers`，于是"逐项为什么没填上"这种内部明细在失败时
            **全部丢失**，只能靠重跑猜。失败必须留下可诊断的证据。
        """

        return cls(
            ok=False,
            status=STEP_FAILED,
            error_code=error_code,
            summary=summary,
            data=dict(data or {}),
            blockers=list(blockers or ()),
        )

    @classmethod
    def not_implemented(cls, reason: str, blockers: Optional[Sequence[Blocker]] = None) -> "StageOutcome":
        return cls.failed("NOT_IMPLEMENTED", reason, blockers)


# ---------------------------------------------------------------------------
# 阶段处理器
# ---------------------------------------------------------------------------
def stage_session(ctx: PipelineContext) -> StageOutcome:
    """阶段 ``session``：连接调试浏览器并读取当前页面状态。**只读**。"""

    from .constants import TAOBAO_CDP_LIST_URL

    list_url = ctx.cdp_list_url or TAOBAO_CDP_LIST_URL
    pinned_target = str(getattr(ctx.prepared_media, 'publish_target_id', '') or '')
    prober: SessionProbeFn = ctx.session_probe or (
        (lambda url: probe_session(url, target_id=pinned_target, require_publish_page=True))
        if pinned_target else (lambda url: probe_session(url)))
    probe: SessionProbe = prober(list_url)
    ctx.scratch["session_probe"] = probe
    snapshot = snapshot_from_probe(probe)

    if not probe.ok:
        ctx.scratch["snapshot"] = snapshot
        first = probe.blockers[0] if probe.blockers else None
        return StageOutcome.failed(
            first.code if first else "CDP_UNREACHABLE",
            (first.detail if first else "会话探测失败"),
            blockers=probe.blockers,
        )

    # 类目页也是合法起点。连接阶段只读取页面事实，不能等待填写页：
    # 填写页依赖后面的 select_category，否则会在这里空等 30 秒。
    facts_filled = False
    # 注入探测器由测试/调用方负责会话；生产路径才连接当前页面。
    if ctx.session_probe is None:
        try:
            from . import page as page_module

            # 公共入口已检查调试通道与 renderer；这里只要求页面能响应。
            with _open_publish_page(ctx, wait_form=False) as client:
                snapshot = page_module.fill_snapshot_facts(snapshot, client)
                facts_filled = True
        except Exception as exc:  # 阶段错误必须是失败，不能交给下游伪装成未知事实
            ctx.scratch["snapshot"] = snapshot
            if isinstance(exc, TaobaoPublishError):
                code = exc.code
                detail = exc.detail or str(exc)
                blockers = list(exc.blockers)
            else:
                code = "PLATFORM_ERROR"
                detail = "读取发布页面状态失败（{}）".format(type(exc).__name__)
                blockers = []
            if not blockers:
                blockers.append(Blocker(
                    code=code,
                    field="page.renderer" if code == "RENDERER_HUNG" else "page.session",
                    detail=detail, source="stages.stage_session",
                ))
            return StageOutcome.failed(code, "连接发布页面失败：" + detail, blockers)

    ctx.scratch["snapshot"] = snapshot

    if facts_filled and snapshot.has_category_page:
        where = "类目选择页"
    elif facts_filled and snapshot.has_workbench_root:
        where = "商品填写页"
    else:
        where = "发布入口" if probe.publish_target_found else "淘宝页面（非发布工作台）"
    facts_note = ""
    if facts_filled:
        facts_note = "；DOM 事实已评估（工作台={}，遮挡={}）".format(
            "有" if snapshot.has_workbench_root else "无",
            "有" if snapshot.has_blocking_overlay else "无",
        )
    return StageOutcome(
        ok=True,
        summary=f"CDP 就绪，目标 {probe.target_count} 个，当前在{where}{facts_note}",
        data=probe.to_dict(),
    )


def stage_precheck(ctx: PipelineContext) -> StageOutcome:
    """阶段 ``precheck``：发布前置检查。**只读**，且**不触碰平台**。"""

    snapshot = ctx.scratch.get("snapshot", ctx.snapshot)
    # 只对**本次计划里的**写操作要求授权。
    #
    # 缺省（``required_operations=None``）会按**全部**写操作检查，那对
    # 「提交前截停」的运行是过严的：明明不会提交，却要求 ``submit_publish`` 授权，
    # 于是 `require_write=True` 下预检永远过不了（实测：4 条阻塞里 2 条是这个）。
    planned = ctx.scratch.get("stage_plan")
    required_operations = None
    if planned:
        required_operations = tuple(sorted({
            STAGE_WRITE_OPERATION[stage]
            for stage in planned
            if STAGE_WRITE_OPERATION.get(stage)
        }))
    result: PreflightResult = run_preflight(
        ctx.item,
        snapshot=snapshot,
        authorization=ctx.authorization,
        contracts=ctx.resolved_contracts(),
        require_write=not ctx.dry_run,
        required_operations=required_operations,
    )
    ctx.scratch["preflight"] = result

    # 后续控件缺口按阶段记录，不能阻止已实现的类目选择/下一步。
    # 各阶段在执行前重新核对自身控件，未知映射仍明确停止，绝不先上传再报错。
    from .form_adapters import STAGE_PURPOSES, stage_adapter_blockers
    deferred = {}
    if not ctx.dry_run:
        for stage in (planned or STAGE_PURPOSES):
            blockers = stage_adapter_blockers(ctx.item, ctx.resolved_contracts(), stage)
            if blockers:
                deferred[stage] = [blocker.to_dict() for blocker in blockers]
    ctx.scratch['deferred_adapter_blockers'] = deferred

    if result.ready:
        return StageOutcome(
            ok=True,
            summary=(
                f"基础检查通过（阻塞 0，告警 {len(result.warnings)}；"
                f"SKU {len(ctx.item.skus)} 条，主图 {len(ctx.item.images.main)} 张）"
            ),
            data={**result.to_dict(), 'deferred_adapter_blockers': deferred},
        )
    return StageOutcome.failed(
        "PREFLIGHT_BLOCKED",
        f"前置检查未通过：{len(result.blockers)} 条阻塞项；" + _blocker_details(result.blockers),
        blockers=result.blockers,
    )


def _blocker_details(blockers: Sequence[Blocker]) -> str:
    """把重复控件原因合并到原有错误提示，保留结构化 blocker 明细。"""
    adapter_reasons = {
        "sku.custom_mode": "自定义规格填写控件尚未确认淘宝页面结构",
        "sku.custom_rows": "自定义规格填写控件尚未确认淘宝页面结构",
        "sku.custom_input": "自定义规格填写控件尚未确认淘宝页面结构",
        "sku.custom_add": "自定义规格填写控件尚未确认淘宝页面结构",
        "sku.image_slot": "SKU 图片绑定控件尚未确认淘宝页面结构",
        "sku.table_image": "SKU 图片绑定控件尚未确认淘宝页面结构",
        "media.image_card": "图片空间卡片控件尚未确认淘宝页面结构",
        "detail.editor": "宝贝详情编辑器尚未确认淘宝页面结构",
    }
    reasons = list(dict.fromkeys(
        adapter_reasons.get(blocker.field, blocker.detail or blocker.message)
        if blocker.code == "EVIDENCE_INSUFFICIENT" else (blocker.detail or blocker.message)
        for blocker in blockers
    ))
    return "；".join(reasons)


def _stage_adapter_guard(ctx: PipelineContext, stage: str) -> Optional[StageOutcome]:
    """只核对本阶段实际使用的控件，在打开页面或写入前明确停止。"""
    if ctx.dry_run:
        return None
    if stage == 'readback':
        from .form_adapters import missing_media_roles
        missing_media = missing_media_roles(ctx.item, ctx.scratch.get('bound_media', {}))
        if missing_media:
            return StageOutcome.failed(
                'EVIDENCE_INSUFFICIENT',
                '本次还未完成{}的写入与回读，不能确认完整填写；已停在提交前'.format(
                    '、'.join(label for _, label in missing_media)),
                blockers=[Blocker(
                    code='EVIDENCE_INSUFFICIENT', field=field,
                    detail='没有本次对应规格/详情顺序的完整绑定回执；不以路径或图片数量冒充完成',
                    source='stages.stage_readback',
                ) for field, _ in missing_media],
            )
    from .form_adapters import (
        RUNTIME_GUARDED_KEYS, STAGE_PURPOSES, media_plan, required_keys, stage_adapter_blockers,
    )
    handler = STAGE_HANDLERS.get(stage)
    purpose = STAGE_PURPOSES.get(stage)
    if handler and handler.mutates_page and purpose:
        needed = set(required_keys(ctx.item, purpose=purpose)) & RUNTIME_GUARDED_KEYS
        undeclared = sorted(needed - set(handler.runtime_selector_keys))
        if undeclared:
            return StageOutcome.failed(
                'CONTRACT_INVALID',
                '本阶段缺少原生控件运行时验证声明：' + '、'.join(undeclared),
                blockers=[Blocker(code='CONTRACT_INVALID', field=key,
                                  detail='处理器必须声明并执行对应控件的运行时验证',
                                  source='stages._stage_adapter_guard') for key in undeclared],
            )
    if stage == 'upload_images':
        try:
            media_plan(ctx.item)
        except TaobaoPublishError as exc:
            return StageOutcome.failed(
                exc.code, "上传前素材对应关系无效：" + exc.detail,
                blockers=exc.blockers or [Blocker(
                    code=exc.code, field='images.sku', detail=exc.detail,
                    source='stages._stage_adapter_guard',
                )],
            )
    blockers = stage_adapter_blockers(ctx.item, ctx.resolved_contracts(), stage)
    if not blockers:
        return None
    return StageOutcome.failed(
        "EVIDENCE_INSUFFICIENT",
        "阶段「{}」尚不能执行：{}".format(stage_label(stage), _blocker_details(blockers)),
        blockers=blockers,
    )


@dataclass(frozen=True)
class StageHandlerSpec:
    """一个阶段的处理器 + 它对「这个阶段会写什么」的**自我声明**。

    为什么要自我声明：``STAGE_WRITE_OPERATION`` 是中央登记表，但执行器只能靠它判断
    「要不要过授权门」。如果一个阶段的处理器实际上会写平台、却在中央表里被登记成
    只读，授权门就被绕过了。让处理器自己声明一次，执行器**交叉校验**两份声明，
    不一致即 fail closed（对抗性审查 2026-10-02，F11）。

    审查特别点出 ``select_category`` 与 ``readback``：它们天然要「点页面 / 回读表单」，
    是未来最容易偷偷引入写操作的位置。
    """

    run: Callable[[PipelineContext], StageOutcome]
    write_operation: Optional[str] = None
    #: 处理器是否会触碰平台（读也算）。``False`` 表示纯本地计算。
    touches_platform: bool = True
    #: 处理器是否会**改变页面或平台状态**（点击、输入、选择、上传、提交）。
    #:
    #: 为什么不能只看 ``write_operation``：``select_category`` 会选中类目与品牌，
    #: 但**不产生草稿、不上架、不提交**，所以它在中央登记表里是 ``None``。
    #: dry-run 的语义是「绝不触碰平台」，只看 ``write_operation`` 会让它在 dry-run 下
    #: 照样点页面——这是本字段存在的原因（由 test_pipeline 的 dry-run 用例发现）。
    mutates_page: bool = False
    #: 处理器是否**能走到成功**。
    #:
    #: ``True``（缺省）表示实现完整。``False`` 表示「已注册但故意停在中间」——
    #: 实现完整不等于所有平台控件已实测；平台证据由 ``LIVE_VERIFIED_STAGES`` 单列。
    #:
    #: 为什么需要这个字段：``unimplemented_stages`` 只看「有没有注册」，
    #: 于是一个**永远不会成功**的阶段会被算成已实现，让 ``publishable`` 报出
    #: 「现在能一键发布」——而流水线一定会在那一步失败。
    #: 这与 ``publish_route_ready`` 的假信号是同一类问题（见 E-099）。
    complete: bool = True
    #: 由原生控件处理器验证当前 DOM 的选择器。注册声明与实际用途交叉检查，
    #: 不提升静态 candidate 等级，也不替代动作前检查及动作后回读。
    runtime_selector_keys: Sequence[str] = ()


def stage_not_implemented(reason: str, blocked_by: Sequence[str] = ()) -> Callable[[PipelineContext], StageOutcome]:
    """产出一个「未实现」的阶段处理器。

    ``blocked_by`` 列出挡在前面的证据项，写进 blocker detail，让后人一眼知道
    要补什么，而不是只看到一句「未实现」。
    """

    def handler(ctx: PipelineContext) -> StageOutcome:
        detail = reason
        blockers: List[Blocker] = []
        if blocked_by:
            detail += "；前置证据缺口：" + "、".join(blocked_by)
            for intent in blocked_by:
                blockers.append(
                    Blocker(
                        code="EVIDENCE_INSUFFICIENT",
                        field=intent,
                        detail=f"阶段 {reason} 依赖该证据，当前不可用",
                        source="stages.stage_not_implemented",
                    )
                )
        return StageOutcome.not_implemented(detail, blockers)

    return handler


def _open_publish_page(ctx: PipelineContext, *, wait_form: bool = True) -> "PageClient":
    """连上发布工作台页面。连不上时抛 :class:`PageError`，**不返回 None**。

    阶段里所有写值都经过它。找不到页面说明用户还没走到填写页——这时应该明确报错，
    而不是「什么都没填」还报成功。

    ⚠️ **`wait_form=True` 会等填写页真的渲染出来。**

    这是实机踩出来的**交接缺陷**：`select_category` 选中类目后会**导航到填写页**，
    紧接着的 `fill_base` 只隔 14 毫秒就去找元素，报
    「标签 '宝贝标题' 没有定位到行」——而页面几秒后完全正常。

    **单独跑 `fill_base` 永远发现不了**（页面早就加载好了），
    只有连着跑才暴露：**阶段各自能跑，交接不行。**

    一直等不到就**明确报错**，而不是把症状留给下游阶段。

    :param wait_form: `session` 和 `select_category` 要传 ``False``——连接和选类目
        均允许从类目页开始；填写阶段保持默认 ``True`` 等待表单渲染。
    """

    from .cdp import TAOBAO_CDP_LIST_URL, list_targets, select_publish_target
    from .page import PageClient, PageError, RendererHungError

    list_url = ctx.cdp_list_url or TAOBAO_CDP_LIST_URL
    targets = list_targets(list_url)
    pinned_target = str(getattr(ctx.prepared_media, 'publish_target_id', '') or '')
    if pinned_target:
        targets = [target for target in targets if str(target.get('id') or '') == pinned_target]
    target = select_publish_target(targets)
    if target is None:
        raise PageError("没有找到淘宝发布页面；请打开商品发布的类目选择页或填写页")
    ws_url = str(target.get("webSocketDebuggerUrl") or "")
    if not ws_url:
        raise PageError("发布工作台页面没有调试通道（webSocketDebuggerUrl 缺失）")
    client = PageClient.connect(ws_url, target_url=str(target.get("url") or ""))

    # ⚠️ **「连上了」不等于「能用」。**
    #
    # 实测（2026-10-03）：renderer 冻结时连接**成功**，但 `Page.enable`、
    # `Runtime.evaluate` 全部超时，`getNavigationHistory` 返回 0 条。
    # 连 `Page.reload` 都没救回来（同一浏览器里另一个页面 reload 后正常）。
    #
    # 不探这一下的话，每个阶段都要各自撞一次 25 秒超时，最后只报一句
    # 「等待 CDP Page.navigate 响应超时」——**分不清是网慢还是页面卡死**。
    # 在动手之前就失败，并说清怎么办。
    if not client.health_check(timeout=6.0):
        client.close()
        raise RendererHungError(
            "连上了调试通道，但**页面不响应**——renderer 可能卡死。"
            "请在浏览器里刷新该页面；刷新无效时关掉该标签页重开"
            "（登录态在 profile 里，不会丢）。"
            "实测：卡死时连 Page.reload 都可能救不回来，需要重建标签页。")

    if wait_form:
        from . import page as _page

        rows = _page.wait_for_publish_form(client)
        if not rows:
            client.close()
            raise PageError(
                "等了 30 秒，填写页仍然没有渲染出任何一行"
                "（可能是类目刚选完还在加载，或页面停在了别的步骤）")
    return client


def _field_report(results: List[Dict[str, Any]]) -> str:
    return "、".join("{}={!r}".format(r["label"], r.get("read_back")) for r in results)


def stage_fill_base(ctx: PipelineContext) -> StageOutcome:
    """阶段 ``fill_base``：填标题与商家编码。

    **写阶段**（登记为 ``save_draft``）。只填 ``PublishItem`` 里确实有的字段，
    没有的就跳过并在 summary 里说明——**不编造值**。

    写入前按契约的长度规则先校验：标题超长时平台会截断或拒绝，
    与其等提交时失败，不如现在明确报出来。
    """

    from .page import fill_text_field, blockers_for

    from .text_rules import count_title_units

    contracts = ctx.resolved_contracts()
    title = (ctx.item.title or "").strip()
    if not title:
        return StageOutcome.failed(
            "EVIDENCE_INSUFFICIENT", "没有可填的宝贝标题（item.title 为空）")

    max_chars = contracts.rules.integer("title_max_chars")
    min_chars = contracts.rules.integer("title_min_chars")
    if count_title_units(title) < min_chars:
        return StageOutcome.failed("TITLE_TOO_SHORT", "宝贝标题少于 {} 字符".format(min_chars))
    if count_title_units(title) > max_chars:
        return StageOutcome.failed(
            "TITLE_TOO_LONG",
            "宝贝标题 {} 字符，超过契约上限 {}".format(count_title_units(title), max_chars),
            blockers=[Blocker(
                code="TITLE_TOO_LONG", field="item.title",
                detail="实测上限 {} 字符（见 contracts/rules.json title_max_chars）".format(max_chars),
                source="stages.stage_fill_base",
            )],
        )

    guide_title = (getattr(ctx.item, "guide_title", "") or "").strip()
    if guide_title:
        contracts_guide = contracts.rules.get("guide_title_max_chars")
        if contracts_guide is not None and contracts_guide.hard:
            guide_max = contracts_guide.integer()
            if count_title_units(guide_title) > guide_max:
                return StageOutcome.failed(
                    "TITLE_TOO_LONG",
                    "导购标题 {} 字符，超过契约上限 {}".format(count_title_units(guide_title), guide_max),
                    blockers=[Blocker(
                        code="TITLE_TOO_LONG", field="guide_title",
                        detail="见 contracts/rules.json guide_title_max_chars",
                        source="stages.stage_fill_base",
                    )],
                )

    results: List[Dict[str, Any]] = []
    client = None
    try:
        client = _open_publish_page(ctx)
        results.append(fill_text_field(client, "宝贝标题", title))
        if guide_title:
            # 选填：给了才填。`fill_text_field` 自带回读校验。
            results.append(fill_text_field(client, "导购标题", guide_title))
        outer_id = (ctx.item.outer_id or "").strip()
        if outer_id:
            results.append(fill_text_field(client, "商家编码", outer_id))
    except Exception as exc:  # noqa: BLE001 - 阶段异常必须转成结构化结果
        return StageOutcome.failed(
            getattr(exc, "code", "PAGE_ERROR"),
            "填基础信息失败：{}".format(exc),
            blockers=blockers_for(exc, stage="fill_base") if client is not None else None,
        )
    finally:
        if client is not None:
            client.close()

    ctx.scratch["fill_base"] = results
    skipped = [] if (ctx.item.outer_id or "").strip() else ["商家编码（未提供）"]
    summary = "已填并回读校验：" + _field_report(results)
    if skipped:
        summary += "；跳过：" + "、".join(skipped)
    return StageOutcome(ok=True, summary=summary, data={"fields": results, "skipped": skipped})


def stage_fill_props(ctx: PipelineContext) -> StageOutcome:
    """阶段 ``fill_props``：按属性名填类目属性。

    **写阶段**（登记为 ``save_draft``）。

    两条硬约束：

    1. 属性名必须出现在**实测行标签地图**（:data:`locating.MEASURED_ROW_LABELS`）里。
       不在名单里的属性**直接报错**，不去猜它叫什么、在哪一行——页面上的属性名是
       ``prop_name``，若与实测名对不上，说明该类目的属性集尚未勘察。
    2. 每条都要回读校验。属性控件多是下拉框，选了未必生效；只报「已选择」而不核对，
       等于把「选上了吗」交给运气。
    """

    from .locating import MEASURED_ROW_LABELS
    from .page import (classify_row, fill_text_field, pick_prop_value,
                      wait_for_prop_row, blockers_for)

    props = list(ctx.item.props or [])
    if not props and not ctx.item.captured_attributes:
        return StageOutcome.skipped("没有指定类目属性覆盖，保留页面现有值；实际必填属性由最终回读验证")

    unknown = [p.prop_name for p in props if p.prop_name not in MEASURED_ROW_LABELS]
    if unknown:
        # fail closed：不去猜这些属性在哪一行。猜错会写到别的字段上，且每一步都「成功」。
        return StageOutcome.failed(
            "EVIDENCE_INSUFFICIENT",
            "以下属性不在实测行标签地图里，拒绝填写：{}".format("、".join(unknown)),
            blockers=[Blocker(
                code="EVIDENCE_INSUFFICIENT", field=p,
                detail="该属性名未在页面上实测到；需先勘察该类目的属性集，不可凭猜填写",
                source="stages.stage_fill_props",
            ) for p in unknown],
        )

    no_control = [p.prop_name for p in props
                  if MEASURED_ROW_LABELS[p.prop_name].get("controls", 0) == 0]
    if no_control:
        return StageOutcome.failed(
            "EVIDENCE_INSUFFICIENT",
            "以下属性行内没有可写控件，需走各自的专用入口：{}".format("、".join(no_control)),
            blockers=[Blocker(
                code="EVIDENCE_INSUFFICIENT", field=name,
                detail=MEASURED_ROW_LABELS[name].get("note") or "该行无内联控件",
                source="stages.stage_fill_props",
            ) for name in no_control],
        )

    results: List[Dict[str, Any]] = []
    unwritable: List[Blocker] = []
    captured_skipped = []
    client = None
    try:
        client = _open_publish_page(ctx)
        for entry in props:
            # ⚠️ **先分类，再决定怎么写。**
            #
            # 改之前这里对每个属性都调 `fill_text_field`。而实测：当前类目下的
            # 属性行（品牌、适用季节…）**全是 ``input[role=combobox]``**
            # （可搜索下拉），打字不提交值——于是只会拿到
            # 「标签 '品牌' 没有定位到行」，**说的是症状，不是原因**。
            #
            # 真正的原因有两层：
            # ① 属性行用的是 `.sell-catProp-item-common` 那套结构，不是发布页那套；
            # ② 它的控件是可搜索下拉，**没有写入方式**。
            # ⚠️ **先等这一行渲染出来。**
            #
            # 「类目属性」块比表单行渲染得晚：实测 `select_category` 刚导航完时，
            # 直接分类会得到 `not_located`，而几秒后它就在那里——
            # 于是报「不在当前类目的表单上」，**把交接问题说成了类目问题**。
            shape = wait_for_prop_row(client, entry.prop_name)
            kind = shape.get("kind")

            if (entry.prop_name == '品牌' and ctx.scratch.get('select_category', {}).get('brand') == entry.value_name):
                from .page import read_prop_value
                current = read_prop_value(client, entry.prop_name)
                if current == entry.value_name:
                    results.append({'label': entry.prop_name, 'written': entry.value_name,
                                    'read_back': current, 'how': 'kept_selected_brand'})
                    continue

            if kind == "text":
                results.append(fill_text_field(client, entry.prop_name, entry.value_name))
                continue

            if kind == "combobox":
                # **下拉类属性走「点开 → 搜索 → 精确点中候选 → 回读」。**
                #
                # 实机验证过两种控件都能走：
                # * `sell-o-combobox`（品牌）—— 值在 input.value；
                # * `sell-o-select`（适用季节/适用性别）—— input 只读，值在
                #   `.next-select-values`。
                # `pick_prop_value` 内部按优先级读，两种都能回读。
                #
                # ⚠️ **绝不退化成自由文本硬填**：契约实测往输入框打字并回车
                # **不会**加入任何值。候选里没有就如实报错。
                picked = pick_prop_value(client, entry.prop_name, entry.value_name)
                results.append({
                    "label": entry.prop_name,
                    "written": entry.value_name,
                    "read_back": picked.get("read_back"),
                    "how": "picked_from_dropdown",
                })
                continue
            elif kind == "not_located":
                detail = (
                    "「{}」**不在当前类目的表单上**。`MEASURED_ROW_LABELS` 是"
                    "**跨类目的并集**（46 个标签），当前页面上只有其中一个子集；"
                    "换类目后可用属性会变，需按当前类目重新核对"
                ).format(entry.prop_name)
            elif kind == "ambiguous":
                detail = "「{}」定位到 {} 行，**拒绝猜是哪一行**".format(
                    entry.prop_name, shape.get("hitCount"))
            else:
                detail = "「{}」行内没有可写控件（kind={}）".format(entry.prop_name, kind)

            unwritable.append(Blocker(
                code="EVIDENCE_INSUFFICIENT",
                field=entry.prop_name,
                detail=detail,
                source="stages.stage_fill_props",
            ))
        if not unwritable:
            from .attribute_fill import fill as fill_captured_attributes
            captured_results, captured_skipped = fill_captured_attributes(client, ctx.item)
            results.extend(captured_results)
    except Exception as exc:  # noqa: BLE001
        return StageOutcome.failed(
            getattr(exc, "code", "PAGE_ERROR"),
            "填类目属性失败：{}".format(exc),
            blockers=blockers_for(exc, stage="fill_props") if client is not None else None,
        )
    finally:
        if client is not None:
            client.close()

    if unwritable:
        # **一条都没写成**与「写了几条、剩下写不了」要分开说。
        return StageOutcome.failed(
            "EVIDENCE_INSUFFICIENT",
            "有 {} 条属性写不进去（成功 {} 条）：{}".format(
                len(unwritable), len(results),
                "；".join(item.detail.split("：")[0] for item in unwritable[:3])),
            blockers=unwritable,
        )

    ctx.scratch["fill_props"] = results
    return StageOutcome(
        ok=True,
        summary="已填并回读校验 {} 条属性：{}".format(len(results), _field_report(results)),
        data={"props": results, "captured_skipped": captured_skipped},
    )


def stage_fill_required(ctx: PipelineContext) -> StageOutcome:
    """阶段 ``fill_required_attrs``：补齐**平台标了 `*` 的必填项**。

    **写阶段**（登记为 ``save_draft``）。

    与 ``fill_props`` 的分工：那个填**采集到的**属性值；这个填**平台要求必填、
    而采集数据里没有**的那些。取值来自 :mod:`taobao_publish.category_defaults`：

    * **类目驱动**（如筒高跟随类目末级：中筒袜→中筒）；
    * **零商品语义的稳妥值**（`四季通用`/`男女通用`/`其他`），且**平台推荐值优先**；
    * **商品事实（面料/材质成分/产地/品牌…）一律不填**——那是商品事实，猜了就是错标。

    三条硬约束：

    1. 稳妥值**必须落在平台候选里**——候选里没有就不填（不硬塞自由文本，实测不提交）；
    2. 每项**逐项回读**，读不回就记失败（不把"点到了"当"填上了"）；
    3. 逐项失败**如实报出**，且**不中断**其余项——最后按失败数与"仍空"数决定成败。
    """

    from . import required_attrs as required
    from .page import blockers_for

    client = None
    try:
        client = _open_publish_page(ctx)
        before = required.read_required_rows(client)
        result = required.fill_required_attrs(
            client,
            # ⚠️ 类目路径在 `item.category.path`（`CategoryRef.path`，人类可读的完整路径）；
            # `PublishItem` 上没有 `category_path` 字段（实测写错过）。
            category_path=list(getattr(ctx.item.category, "path", ()) or ()),
            skip=list((ctx.scratch.get("skip_required_attrs") or ())),
        )
        after = required.read_required_rows(client)
    except Exception as exc:  # noqa: BLE001
        return StageOutcome.failed(
            getattr(exc, "code", "PAGE_ERROR"),
            "补齐必填项失败：{}".format(exc),
            blockers=blockers_for(exc, stage="fill_required_attrs") if client is not None else None,
        )
    finally:
        if client is not None:
            client.close()

    filled = list(result.get("filled") or [])
    failed = list(result.get("failed") or [])
    needs_human = list(result.get("needs_human") or [])
    # 填完之后**仍然为空**的下拉类必填项：这才是"真的没补齐"。
    still_empty = [row for row in after
                   if row.get("empty") and row.get("display") is not None]
    ctx.scratch["fill_required_attrs"] = result

    if failed or still_empty:
        blockers = [
            Blocker(code="REQUIRED_FIELD_MISSING", field=str(row.get("name")),
                    detail="必填项填完之后仍为空", source="stages.stage_fill_required")
            for row in still_empty
        ] + [
            Blocker(code="FIELD_MISMATCH", field=str(item.get("name")),
                    detail=str(item.get("error")), source="stages.stage_fill_required")
            for item in failed
        ]
        return StageOutcome.failed(
            "REQUIRED_FIELD_MISSING",
            "有 {} 项必填没补齐（已填 {} 项）：{}".format(
                len(still_empty) + len(failed), len(filled),
                "、".join(str(row.get("name")) for row in (still_empty[:5] or failed[:5]))),
            blockers=blockers,
            # ⚠️ **失败也要带逐项明细**：早先这里不带 `data`，于是"为什么没填上"
            # （候选读不到？没有稳妥值？写了没生效？）在失败时完全无从判断。
            data={"required": result, "empty_after": still_empty},
        )

    return StageOutcome(
        ok=True,
        summary="必填项已补齐并逐项回读：新填 {} 项{}，已有 {} 项；商品事实留给人 {} 项".format(
            len(filled),
            ("（{}）".format("、".join(str(item.get("label")) for item in filled))
             if filled else ""),
            len(result.get("already") or []),
            len(needs_human)),
        data={"required": result, "empty_after": still_empty},
    )


def stage_fill_price_stock(ctx: PipelineContext) -> StageOutcome:
    """阶段 ``fill_price_stock``：填一口价与总库存。

    **写阶段**（登记为 ``save_draft``）。

    一口价与总库存都是**商品级**字段（不是 SKU 行）。SKU 行的价格库存由
    ``fill_skus`` 负责——两者不能混。

    注意：总库存在 UI 上**预填 1**（实测回读为 ``'1'``），所以它是「有值」的。
    写入前先回读，把这个既有值记下来，便于出错时判断是不是我们写坏的。
    """

    from .page import fill_text_field, read_text_field, blockers_for

    contracts = ctx.resolved_contracts()

    skus = list(ctx.item.skus or [])
    prices = [s.price for s in skus if s.price is not None]
    stocks = [s.stock for s in skus if s.stock is not None]
    if not prices:
        return StageOutcome.failed(
            "EVIDENCE_INSUFFICIENT", "没有任何 SKU 带价格（sku.price 全为空）")
    if not stocks:
        return StageOutcome.failed(
            "EVIDENCE_INSUFFICIENT", "没有任何 SKU 带库存（sku.stock 全为空）")

    price_min = contracts.rules.number("sku_price_min")
    # 用户指定：商品一口价 = 最低 SKU 售价的两倍，向上取整到元；SKU 行单价保持原值。
    from .price_policy import listing_price
    price = listing_price(prices)
    if min(prices) < price_min:
        return StageOutcome.failed(
            "PRICE_TOO_LOW",
            "SKU 单价 {} 低于契约下限 {}".format(min(prices), price_min),
            blockers=[Blocker(
                code="PRICE_TOO_LOW", field="sku.price",
                detail="见 contracts/rules.json sku_price_min",
                source="stages.stage_fill_price_stock",
            )],
        )
    stock = sum(stocks)

    client = None
    try:
        client = _open_publish_page(ctx)
        stock_before = read_text_field(client, "总库存")
        results = [
            fill_text_field(client, "一口价", _format_price(price)),
            fill_text_field(client, "总库存", str(stock)),
        ]
        # 已删除：「购买须知」的写入与随之而来的 `skipped` 记录（`购买须知（未提供）`）。
        # `PublishItem.notice` 已无调用方（界面 E-318 撤掉入口、侧车不转发），所以这里
        # 既不写那一行，也不再往摘要里报"未填"——为一行不存在的数据报"未填"只会误导。
        # 平台那一行仍在，要接回来请补齐五处（见 models.py 的说明）。
    except Exception as exc:  # noqa: BLE001
        return StageOutcome.failed(
            getattr(exc, "code", "PAGE_ERROR"),
            "填价格库存失败：{}".format(exc),
            blockers=blockers_for(exc, stage="fill_price_stock") if client is not None else None,
        )
    finally:
        if client is not None:
            client.close()

    ctx.scratch["fill_price_stock"] = results
    summary = "已填并回读校验：{}（总库存写入前为 {!r}）".format(_field_report(results), stock_before)
    return StageOutcome(
        ok=True,
        summary=summary,
        data={"fields": results, "stock_before": stock_before,
              "price": price, "stock": stock},
    )


def stage_select_category(ctx: PipelineContext) -> StageOutcome:
    """阶段 ``select_category``：搜索发品 → 精确匹配候选 → 选品牌 → 进入填写页。

    **这一步会改变页面状态**（选中类目、选中品牌），但**不创建草稿、不上架、不提交**。
    登记表把它标为 ``None``（非写操作），处理器也如实声明 ``write_operation=None``。

    ## 一个必须说清楚的张力

    ``CategoryRef.path`` 的注释写着「只用于展示与人工核对，**不做程序判定**」，
    但类目搜索的候选**只给路径、不给 ID**（实测 DOM 里 ``cate-path`` / ``wrap`` /
    ``result-item`` 都没有 ``data-*`` 或 ``id``）。所以本阶段的处理是：

    * 完整路径已给出时精确匹配；只给出明确搜索关键词时，候选的末级名称
      必须与关键词精确相同且只命中一条，完整路径取页面原文；
    * **选完之后把解析出的 catId 回读**（``/router/asyncOpt.htm`` 的请求或后续 URL），
      写进 ``ctx.scratch``，那才是权威 ID。

    换句话说：路径负责「点哪一个」，ID 负责「选中的到底是什么」。
    命中 0 个或多个都**直接失败**，不做「最接近」的妥协。
    """

    from . import page
    from urllib.parse import urlsplit

    def at_category_page(url: str) -> bool:
        destination = urlsplit(url)
        expected = urlsplit(CATEGORY_PAGE_URL)
        return (
            destination.scheme == expected.scheme
            and destination.hostname == expected.hostname
            and destination.path == expected.path
            and destination.port in (None, 443)
            and destination.username is None
            and destination.password is None
        )

    target_path = tuple(str(seg).strip() for seg in (ctx.item.category.path or ()) if str(seg).strip())
    search_keyword = str(getattr(ctx.item.category, "search_keyword", "") or "").strip()
    if not target_path and not search_keyword:
        return StageOutcome.failed(
            "EVIDENCE_INSUFFICIENT",
            "没有目标类目路径或明确类目关键词，无法在类目搜索结果里唯一定位候选")
    target_text = ">".join(target_path)

    brand = ""
    brand_entries = [entry for entry in (ctx.item.props or []) if entry.prop_name == "品牌"]
    supplied = {entry.value_name.strip() for entry in brand_entries if entry.value_name and entry.value_name.strip()}
    if len(supplied) > 1:
        return StageOutcome.failed('CONTRACT_INVALID', '本次提供了不同的品牌值，不能选择其中一项')
    brand_defaulted = not supplied
    requested_brand = next(iter(supplied)) if supplied else "无品牌"

    keyword = search_keyword or target_path[-1]

    client = None
    try:
        # **不等填写页**：本阶段从类目页开始（或自己导航过去），那里没有填写页。
        client = _open_publish_page(ctx, wait_form=False)
        steps: List[Dict[str, Any]] = []

        # **自己导航到类目搜索页**：流水线不能依赖「用户恰好停在某个页面」。
        # 上一轮跑完会把页面留在填写页，下一次跑就会报
        # 「当前不在类目搜索页（publish.htm?catId=…）」（实测踩过）。
        current = str(client.evaluate("location.href") or "")
        if not at_category_page(current):
            client.navigate(CATEGORY_PAGE_URL, wait=10.0)
            steps.append({"step": "navigate", "to": CATEGORY_PAGE_URL})

        # 1) 确认在类目页
        href = str(client.evaluate("location.href") or "")
        if not at_category_page(href):
            return StageOutcome.failed(
                "PAGE_ERROR",
                "当前不在类目搜索页（{}），请先回到 https://item.upload.taobao.com/sell/ai/category.htm".format(href[:80]))

        # 2) 搜索发品
        steps.append(page.search_category(client, keyword))

        # 3) 切到「类目」tab
        steps.append(page.switch_category_tab(client, "类目"))

        # 4) 完整路径精确匹配；只有叶子名时必须从实际候选取唯一完整路径。
        if target_path:
            candidate = page.find_exact_category_candidate(client, target_text)
        else:
            candidate = page.find_leaf_category_candidate(client, keyword)
            target_text = candidate["path_text"]
            target_path = tuple(candidate["path"])

        # 5) 点它（⚠️ 必须点文本元素自己，点祖先卡片静默无效）
        steps.append(page.click_unique_text(client, page.CATEGORY_CANDIDATE_SELECTOR, target_text))

        # 6) 回读选中状态：面包屑必须真的出现。
        #
        # **必须轮询等待**：实测「点完马上读」会拿到空数组，看起来像点击没生效，
        # 其实只是 React 还没渲染完。固定 sleep 在弱网下又会误判失败。
        selected = page.wait_for_selected_category(client, list(target_path))
        if selected != list(target_path):
            return StageOutcome.failed(
                "SELECTION_NOT_CONFIRMED",
                "点击后选中的类目与目标不一致：期望 {}，实际 {}".format(
                    list(target_path), selected or "（读不到）"),
                blockers=[Blocker(
                    code="SELECTION_NOT_CONFIRMED", field="item.category.path",
                    detail="类目候选点击后页面没有出现对应面包屑，拒绝继续",
                    source="stages.stage_select_category",
                )],
            )

        # 用户已指定默认无品牌；从当前页面精确选候选，不以缺少 props 再阻塞。
        brand_control = page.read_brand_control_state(client)
        next_state = page.read_confirm_button_state(client)
        if not brand_defaulted or brand_control['present'] or next_state.get('disabled') is not False:
            picked = page.select_brand(client, requested_brand)
            brand = str(picked.get('picked') or '')
            if not brand:
                raise page.PageError('品牌选项没有返回可核对的原文')
            steps.append(picked)
            next_state = page.wait_for_confirm_button(client)
        if (next_state.get('present') is not True or next_state.get('visible') is not True
                or next_state.get('disabled') is not False):
            return StageOutcome.failed(
                "BRAND_REQUIRED", "品牌选择后仍未确认下一步可用，未继续点击",
                blockers=[Blocker(code="BRAND_REQUIRED", field="item.props",
                    detail="已按本次品牌规则匹配候选，但页面尚未允许进入下一步",
                    source="stages.stage_select_category")],
            )

        # 8) 进下一步并回读 catId
        resolved = page.confirm_category_and_read_id(client)
        if not isinstance(resolved, dict):
            raise page.PageError("下一步没有返回可核对的页面与类目结果")
        resolved_id = page.category_id_from_publish_url(str(resolved.get("href") or ""))
        if str(resolved.get("category_id") or "") != resolved_id:
            raise page.PageError("类目回读结果与填写页 URL 的 catId 不一致，拒绝继续")
        expected_id = str(ctx.item.category.category_id or "").strip()
        if expected_id and expected_id != resolved_id:
            return StageOutcome.failed(
                "SELECTION_NOT_CONFIRMED",
                "填写页类目与指定类目不一致：期望 {}，实际 {}".format(expected_id, resolved_id),
                blockers=[Blocker(
                    code="SELECTION_NOT_CONFIRMED", field="item.category_id",
                    detail="完整路径选中后回读的 catId 与调用方指定 ID 不一致，拒绝继续",
                    source="stages.stage_select_category",
                )],
            )
    except Exception as exc:  # noqa: BLE001
        return StageOutcome.failed(
            getattr(exc, "code", "PAGE_ERROR"),
            "选择类目失败：{}".format(exc),
            blockers=page.blockers_for(exc, stage="select_category") if client is not None else None,
        )
    finally:
        if client is not None:
            client.close()

    # 只在选项与下一步都成功后，将实际原文用于后续填写和最终品牌回读。
    if brand:
        if brand_entries:
            for entry in brand_entries:
                entry.value_name = brand
        else:
            from .models import PropEntry
            ctx.item.props.append(PropEntry(prop_name="品牌", value_name=brand))

    ctx.scratch["select_category"] = {
        "keyword": keyword,
        "target_path": list(target_path),
        "brand": brand,
        "brand_defaulted": brand_defaulted,
        "requested_brand": requested_brand,
        "resolved_category_id": resolved.get("category_id"),
        "steps": steps,
    }
    ctx.scratch["resolved_category_id"] = resolved.get("category_id")
    ctx.scratch["resolved_category_path"] = list(target_path)
    ctx.item.category.category_id = resolved_id
    ctx.item.category.path = target_path
    return StageOutcome(
        ok=True,
        summary="类目已选中并进入填写页：{}（店铺 catId={}，品牌={}）".format(
            target_text, resolved.get("category_id") or "未读到", brand or "未提供"),
        data={"target_path": list(target_path), "brand": brand,
              "category_id": resolved.get("category_id"), "steps": steps},
    )


def expected_field_values(ctx: PipelineContext) -> List[Dict[str, Any]]:
    """从 ``PublishItem`` 算出「表单上应当出现哪些值」。

    **这是填表与回读的单一真源**：``fill_*`` 按它写、``readback`` 按它核对。
    两边各算一遍的话，迟早会漂移——那种漂移表现为「回读总是对不上」，
    而人会先去怀疑页面，而不是怀疑两边算得不一样。
    """

    from .price_policy import listing_price
    contracts = ctx.resolved_contracts()
    item = ctx.item
    expected: List[Dict[str, Any]] = []

    title = (item.title or "").strip()
    if title:
        expected.append({"label": "宝贝标题", "value": title, "source": "item.title",
                         "kind": "text"})

    guide_title = (getattr(item, "guide_title", "") or "").strip()
    if guide_title:
        expected.append({"label": "导购标题", "value": guide_title,
                         "source": "item.guide_title", "kind": "text"})

    outer_id = (item.outer_id or "").strip()
    if outer_id:
        expected.append({"label": "商家编码", "value": outer_id,
                         "source": "item.outer_id", "kind": "text"})

    for entry in (item.props or []):
        if entry.value_name:
            expected.append({
                "label": entry.prop_name,
                "value": entry.value_name,
                "source": "item.props[{}]".format(entry.prop_name),
                "kind": "captured_attribute" if entry.evidence.source == "visible_product_parameters_v1" else "text",
            })

    skus = list(item.skus or [])
    prices = [s.price for s in skus if s.price is not None]
    stocks = [s.stock for s in skus if s.stock is not None]
    if prices:
        expected.append({
            "label": "一口价",
            "value": _format_price(listing_price(prices)),
            "source": "min(sku.price)",
            "kind": "text",
        })
    if stocks:
        expected.append({"label": "总库存", "value": str(sum(stocks)),
                         "source": "sum(sku.stock)", "kind": "text"})

    # 已删除：「购买须知」的回读期望（`item.notice`）。写它的那条路已经删掉
    # （见 `stage_fill_price_stock` 与 models.py 的说明），回读里再期待它有值，
    # 就会把每一次发布都判成"少写了一行"。

    # --- 结构性核对 ---------------------------------------------------------
    #
    # ⚠️ **这三项以前不在核对范围内**，而它们恰好是最容易被「后续重渲染」抹掉的
    # ——E-126 实测过：选运费模板会清掉一口价与总库存。主图位与 SKU 表同样是
    # React 从服务端状态渲染出来的，被抹掉时**不会报错，只会悄悄变空**。
    #
    # 而 ``submit`` 现在要求 readback 必须通过，所以漏掉它们等于：
    # 「主图位空着、SKU 表空着」的运行**能通过核对继续走到提交**。
    main_count = len(list(item.images.main or []))
    if main_count:
        # ⚠️ **能比对内容时就不只比张数。**
        #
        # `upload_images` 会把「选图入位后平台上的 URL 列表」记进 scratch。
        # 有它就能核对**内容**（现在挂着的还是不是刚选进去的那几张）；
        # 没有它（例如单独跑 readback）才退回只比张数。
        #
        # 我们**无法**核对「平台 URL 对应的本地文件」——图片空间只给文件名，
        # 没有名字→URL 的映射。所以这里证明的是**稳定性**，不是**身份**。
        recorded = (ctx.scratch.get("upload_images") or {}).get("selected_urls") or []
        if recorded:
            expected.append({
                "label": "主图内容",
                "value": _format_urls(recorded),
                "source": "upload_images 选入后读到的 URL（证明未被替换）",
                "kind": "main_images",
            })
        else:
            expected.append({
                "label": "主图张数",
                "value": str(main_count),
                "source": "len(item.images.main)；本次没有选入记录，只能比张数",
                "kind": "main_image_count",
            })

    if skus:
        # ⚠️ **这一项同时证明两件事：行数对、每行的规格值也对。**
        #
        # 原先只核对 `rowCount`——那样「规格值填错」或「多行填成一样的」都能过。
        # 而页面**本来就读回了** `rows[].specs`（实测：`[["M(37-41)"]]`），
        # 只是核对没用它。
        expected.append({
            "label": "SKU 规格值",
            "value": _format_sku_specs(skus),
            "source": "item.skus[].spec_values",
            "kind": "sku_specs",
        })
        # ⚠️ **平台的硬判据：至少有一个 sku 的价格大于 0。**
        #
        # 实测（2026-10-03）：完整链条跑完之后，平台在页面上**可见地**报着
        #     「至少有一个sku的价格大于0，请先设置sku价格」
        # 而 SKU 行第 3 列（`元`）的输入框是空的——
        # 因为 `fill_skus` 只创建规格行，`fill_price_stock` 填的是**商品级**
        # 「一口价/总库存」，**两张表不是一回事**。
        #
        # 两者都被核对通过，而平台说不能提交。所以这一项直接照搬平台的判据。
        expected.append({
            "label": "SKU 价格",
            "value": "至少一行价格大于 0",
            "source": "平台原文「至少有一个sku的价格大于0，请先设置sku价格」",
            "kind": "sku_row_prices",
        })
        expected.append({
            "label": "SKU 逐行价格库存",
            "value": _format_sku_row_values([
                {"specs": list(sku.spec_values.values()),
                 "price": sku.price, "stock": sku.stock}
                for sku in skus
            ]),
            "source": "item.skus 每组规格的价格与库存；不以至少一行有价格替代全部一致",
            "kind": "sku_row_values",
        })

    freight = (item.freight_template_name or ctx.scratch.get('fill_freight', {}).get('template') or "").strip()
    if freight:
        expected.append({
            "label": "运费模板",
            "value": freight,
            "source": "item.freight_template_name",
            "kind": "freight_template",
        })

    # 提交按钮：**只做否决，不算核对项**。
    #
    # ⚠️ 我原先把它当成「平台自身的完整性判断」加进来，是**错的**。
    # `stage_submit` 的注释里写着实测事实：
    #
    #   「按钮可用」不等于「表单填完了」——实测宝贝标题为空时按钮仍 enabled，
    #   **平台是在点击之后才做校验的**。所以本阶段把「按钮禁用」当作否决信号，
    #   但**不把「按钮可用」当作放行信号**。
    #
    # 把它算成一项「通过的核对」会：① 虚增「N 项一致」的计数；
    # ② 给读的人「平台说可以提交」的误导印象。
    #
    # 所以改成 `veto_only`：禁用 → 失败；可用 → **不计入**。
    expected.append({
        "label": "提交按钮",
        "value": "可点",             # 只在「禁用」时才用于报错
        "source": "平台自身的按钮状态（page.read_submit_state）；**只做否决**",
        "kind": "submit_ready",
        "veto_only": True,
    })

    # contracts 目前不参与计算，但保留参数位置：将来若上限/格式进契约，这里直接取用，
    # 不会出现「填表用了契约、回读忘了用」的不一致。
    _ = contracts
    return expected



def _read_expected_value(client, page_module, entry: Dict[str, Any]) -> str:
    """按 ``entry["kind"]`` 选对应的只读读取器，返回**字符串形式**的实际值。

    为什么要有分派而不是一律 ``read_text_field``：像「主图张数」「SKU 行数」
    这类东西在页面上**不是一个文本字段**，行定位找不到它们
    （早先正是因此把它们排除在核对之外）。
    """

    kind = entry.get("kind") or "text"
    label = entry["label"]

    if kind == "captured_attribute":
        from .attribute_fill import read
        return read(client, label)

    if kind == "text":
        # ⚠️ **两种读法都要试，不能只看有没有抛异常。**
        #
        # 实测：`fill_props` 刚写进去「品牌」，`readback` 却报「期望 '无品牌'，实际 ''」——
        # 因为 `read_text_field` 走发布页那套结构，**它"成功"返回了空串**，
        # 于是永远轮不到属性行那条兜底（原来只在抛异常时才兜底）。
        # 而「品牌」是类目属性行（`.sell-component-wrapper` / 下拉），
        # 值在 `.next-select-values` 里，得用 `read_prop_value` 读。
        #
        # 所以判据改成：**发布页读法拿不到非空值，就换属性行读法**。
        primary = None
        try:
            primary = page_module.read_text_field(client, label)
        except Exception:  # noqa: BLE001 - 定位不到就走属性行那条路
            primary = None
        if primary is not None and str(primary).strip():
            return str(primary)
        fallback = page_module.read_prop_value(client, label)
        if fallback is not None and str(fallback).strip():
            return str(fallback)
        # 「读不到」和「读到了但是空的」是两件事，不能都算 mismatch（既有测试盯这条）。
        if primary is None and fallback is None:
            raise page_module.PageError("属性 {!r} 两种读法都没有读到值".format(label))
        return str(primary if primary is not None else fallback)

    if kind == "main_images":
        # 比对**内容**：现在挂着的 URL 还是不是 `upload_images` 选进去的那几个。
        slots = page_module.read_main_image_slots(client)
        return _format_urls([str(u) for u in (slots.get("images") or []) if str(u).strip()])

    if kind == "main_image_count":
        slots = page_module.read_main_image_slots(client)
        return str(int(slots.get("filled") or 0))

    if kind == "sku_specs":
        # 页面读回的 `rows[].specs` 是**每行的规格值**，直接比对——
        # 只数行数的话，规格值填错也看不出来。
        table = page_module.read_sku_table(client)
        rows = table.get("rows") or []
        actual = [
            "、".join(sorted(str(spec).strip() for spec in (row.get("specs") or []) if str(spec).strip()))
            for row in rows
        ]
        return _format_sku_specs_from_rows(actual)

    if kind == "sku_row_prices":
        # 照搬平台的判据：**至少一行价格 > 0**。
        rows = page_module.read_sku_row_numbers(client)
        if not rows:
            return "读不到 SKU 行"
        positive = 0
        for row in rows:
            try:
                if float(str(row.get("price") or "0").strip() or "0") > 0:
                    positive += 1
            except (TypeError, ValueError):
                continue
        if positive:
            return "至少一行价格大于 0"
        return "{} 行价格都为空或 0".format(len(rows))

    if kind == "sku_row_values":
        return _format_sku_row_values(page_module.read_sku_row_numbers(client))

    if kind == "submit_ready":
        # **这是否决信号，不是放行信号。**
        #
        # 禁用 → 确定不能提交，报错。
        # 可用 → **什么也证明不了**（平台点击之后才校验），返回一个明确的说明，
        #        让调用方知道它没有被算作通过项。
        state = (page_module.read_submit_state(client) or {}).get("submit") or {}
        if not state.get("present"):
            return "查不到提交按钮"
        if state.get("visible") is False:
            return "提交按钮不可见"
        # ⚠️ **`disabled` 必须显式是 False 才算可点。**
        #
        # 缺失时 `dict.get` 给的是 `None`，而 `None` 是假值——直接
        # `return "不可点" if state.get("disabled") else "可点"` 会把
        # **「不知道」当成「没问题」**。
        # 页面的 DOM 事实是三态（`True`/`False`/`None`）。
        disabled = state.get("disabled")
        if disabled is None:
            return "按钮状态未知（disabled 字段缺失）"
        return "不可点" if disabled else "可点"

    if kind == "freight_template":
        value = page_module.read_freight_template(client)
        return str(value or "")

    raise ValueError("未知的核对类型 {!r}（字段 {!r}）".format(kind, label))


#: 拥有**专用读取器**的必填项：它们的"填没填"由各自的读取器判定，**不要再拿
#: 通用文本读取器去读**（那会读回空串，把"读不到"误判成"没填"）。
#: 名字与 `required_fields` 里 `reader` 字段的取值一一对应。
_DEDICATED_REQUIRED_READERS = frozenset({
    "main_images",          # 1:1主图（图片位）
    "detail_modules",       # 宝贝详情（新版模块编辑器）
    "native_rich_text",     # 宝贝详情（旧版/夹具的原生富文本）——**漏过这个**：
                            # 不在名单里就会被通用文本读取器读到空串，误报"未填写"
    "category_path_text",   # 当前类目（展示路径）
    "sku_table",            # 销售规格（规格表）
    "radio_groups",         # 上架时间 / 发货时间（单选组，值不是文本）
    "property_composite",   # 商品属性（复合区）
})


def _read_required_property_values(client, page_module):
    """在链尾核对页面实际要求的属性；与调用方有没有提供该属性无关。"""

    coverage = {"known": False, "scope": "visible_property_label_required",
                "completePage": False, "required": []}
    blockers = []
    try:
        coverage = page_module.read_required_properties(client)
    except Exception as exc:  # 事实读取失败必须阻断回读，不能当作零个必填项。
        coverage["reason"] = "{}: {}".format(type(exc).__name__, exc)
    if coverage.get("known") is not True:
        blockers.append(Blocker(
            code="EVIDENCE_INSUFFICIENT", field="page.required_properties",
            detail=coverage.get("reason") or "当前类目实际必填属性事实未知，不能确认已填完",
            source="stages.stage_readback",
        ))
        return coverage, blockers

    checked = []
    for entry in coverage.get("required") or []:
        label = str(entry.get("label") or "").strip()
        if not label or entry.get("hitCount") != 1:
            blockers.append(Blocker(
                code="READBACK_UNREADABLE", field=label or "page.required_properties",
                detail="页面必填属性标签缺失或不唯一，不能确认其实际值",
                source="stages.stage_readback",
            ))
            continue
        if entry.get("supportedReader") is not True:
            blockers.append(Blocker(
                code="UNSUPPORTED_REQUIRED_FIELD", field=label,
                detail="当前页面将此属性标为必填，但尚无经过确认的控件读取方式",
                source="stages.stage_readback",
            ))
            continue
        # ⚠️ **有的必填项不是文本控件**（`当前类目` 是展示路径、`1:1主图` 是图片位、
        # `宝贝详情` 是模块编辑器）。它们各自有**专用读取器**，结论已经在
        # `entry["filled"]` 里了；再拿通用文本读取器 `read_prop_value` 去读，
        # 只会读回空串，把"读不到"误判成"没填"（实测踩过）。
        # 所以：**专用读取器报了 filled 就用它**，只有没有专用结论时才回落到文本读取。
        dedicated = str(entry.get("reader") or "")
        if dedicated in _DEDICATED_REQUIRED_READERS:
            if entry.get("filled") is True and entry.get("valid") is not False:
                checked.append({"label": label, "value": dedicated,
                                "fact": "dedicated_reader"})
            else:
                blockers.append(Blocker(
                    code="REQUIRED_FIELD_MISSING", field=label,
                    detail="该必填项由专用读取器判定为未填（reader={}）".format(dedicated),
                    source="stages.stage_readback",
                ))
            continue
        try:
            value = page_module.read_prop_value(client, label)
        except Exception as exc:
            blockers.append(Blocker(
                code="READBACK_UNREADABLE", field=label,
                detail="读取实际必填属性失败：{}: {}".format(type(exc).__name__, exc),
                source="stages.stage_readback",
            ))
            continue
        if value is None:
            blockers.append(Blocker(
                code="READBACK_UNREADABLE", field=label,
                detail="没有读到当前页面必填属性的实际值",
                source="stages.stage_readback",
            ))
        elif not str(value).strip():
            blockers.append(Blocker(
                code="REQUIRED_FIELD_MISSING", field=label,
                detail="当前类目将此属性标为必填，实际值为空；不能把未提供属性从回读范围排除",
                source="stages.stage_readback",
            ))
        else:
            checked.append({"label": label, "value": str(value).strip()})
    coverage = {**coverage, "checked": checked, "checkedCount": len(checked)}
    return coverage, blockers


def _read_required_form_controls(client, page_module):
    from .required_fields import blockers
    try:
        coverage = page_module.read_required_form(client)
    except Exception as exc:
        coverage = {'known': False, 'scope': 'visible_publish_rows_required', 'completePage': False,
                    'required': [], 'reason': '{}: {}'.format(type(exc).__name__, exc)}
    return coverage, blockers(coverage)


#: 上架方式的**默认值**：放入仓库。
#:
#: 为什么不默认立刻上架：立刻上架会让商品**马上对消费者可见**，一旦前面的字段有错
#: 就是生产事故；放入仓库则先进仓库，人可以在后台复核后再上架。要立刻上架必须
#: **显式**指定（`ctx.scratch["listing_mode"]`）。
DEFAULT_LISTING_MODE = "放入仓库"

#: 页面上的三个上架方式（实测 `tmp/probe-listing-time.py`）。
LISTING_MODES = ("立刻上架", "定时上架", "放入仓库")


def stage_set_listing(ctx: PipelineContext) -> StageOutcome:
    """阶段 ``set_listing_time``：设置**上架时间**，并回读确认。

    **写阶段**（登记为 ``save_draft``）。

    为什么单独成阶段：它决定商品**是否立刻对消费者可见**。默认
    :data:`DEFAULT_LISTING_MODE`（放入仓库），要立刻上架必须显式指定——
    **危险的那个绝不能是默认值**。

    实测（E-255）：`上架时间` 行有 3 个单选，文案挂在**外层 label** 上，
    而 `input.closest('label')` 命中的是**空的**那一层（`.next-radio-wrapper`），
    所以按文本找选项必须**逐层向上取第一个非空短文本**。
    """

    from .page import blockers_for, choose_radio_by_text
    from .page import build_radio_group_state_expression as page_build_radio_group_state

    mode = str(ctx.scratch.get("listing_mode") or DEFAULT_LISTING_MODE)
    if mode not in LISTING_MODES:
        return StageOutcome.failed(
            "CONTRACT_INVALID",
            "上架方式 {!r} 不是页面上的三个选项之一（{}）".format(mode, "、".join(LISTING_MODES)),
            blockers=[Blocker(code="CONTRACT_INVALID", field="publish.listing_mode",
                              detail="取值必须来自页面实测的三个选项",
                              source="stages.stage_set_listing")],
        )

    client = None
    try:
        client = _open_publish_page(ctx)
        result = choose_radio_by_text(client, "上架时间", mode)
        # 一次求值读回**三个选项**的选中情况，确认有且仅有目标那个被选中
        state = client.evaluate(
            page_build_radio_group_state("上架时间", LISTING_MODES), timeout=30.0)
    except Exception as exc:  # noqa: BLE001
        return StageOutcome.failed(
            getattr(exc, "code", "PAGE_ERROR"),
            "设置上架时间失败：{}".format(exc),
            blockers=blockers_for(exc, stage="set_listing_time") if client is not None else None,
        )
    finally:
        if client is not None:
            client.close()

    checked = [name for name, value in (state or {}).items() if value]
    if checked != [mode]:
        return StageOutcome.failed(
            "FIELD_MISMATCH",
            "上架时间回读不符：期望只选中 {!r}，实际选中 {}".format(mode, checked or "无"),
            blockers=[Blocker(code="FIELD_MISMATCH", field="publish.listing_mode",
                              detail="期望 {}，实际选中 {}".format(mode, checked or "无"),
                              source="stages.stage_set_listing")],
        )

    ctx.scratch["listing_mode"] = mode
    return StageOutcome(
        ok=True,
        summary="上架时间已设为 {!r} 并回读确认{}".format(
            mode, "（本来就是这个值，未重复点击）" if result.get("unchanged") else ""),
        data={"listing_mode": mode, "all_option_state": state},
    )


def stage_readback(ctx: PipelineContext) -> StageOutcome:
    """阶段 ``readback``：把表单上的值读回来，与 ``PublishItem`` 逐项核对。**只读**。

    为什么需要它：**写入「看起来成功」和「真的成功」是两件事**。
    React 受控组件、下拉框格式化、平台改写字段，都会让写入报成功而实际不对。
    ``fill_*`` 已经做了逐字段回读，但那是在写入的那一刻；本阶段提供的是
    **整体核对**——覆盖面更广，也能发现「被后续操作改掉」的情况。

    核对结果不掩盖：不一致进 blockers，读不到也进 blockers（说明定位失效或字段不在了）。
    """

    blocked = _stage_adapter_guard(ctx, 'readback')
    if blocked is not None:
        return blocked

    # ⚠️ **dry-run 下没有可回读的东西**：写阶段全被跳过，页面是上一次留下的状态。
    # 这时硬去核对必然对不上，然后报成 `READBACK_MISMATCH` 失败——
    # 实测踩过：一次校对模式的任务以「总库存 期望 '200'，实际 '0'」告终，
    # 看起来像流水线坏了，其实**什么都没写，本来就无从核对**。
    if ctx.dry_run:
        return StageOutcome.skipped(
            "校对模式（dry-run）不写平台，因此没有本次写入可回读；"
            "回读只在真实写入模式下才有意义"
        )

    from .form_adapters import verify_bound_media

    from . import page

    expected = expected_field_values(ctx)
    if not expected:
        return StageOutcome.failed(
            "EVIDENCE_INSUFFICIENT", "没有任何期望值可核对（item 里没有标题、属性或 SKU 价格/库存）")

    client = None
    matched: List[Dict[str, Any]] = []
    mismatched: List[Dict[str, Any]] = []
    unreadable: List[Dict[str, Any]] = []
    #: `veto_only` 的项（例如「提交按钮」）。**匹配时不计入 `matched`**——
    #: 它们只能否决，通过不构成放行信号。单独记，免得虚增「N 项一致」。
    vetoes_passed: List[Dict[str, Any]] = []
    #: 平台/店铺默认值那几行的实际选中项。**不核对，只报告**——
    #: 它们不是流水线该判的（那是店铺政策），但操作人要知道发出去的是什么。
    default_notice: Dict[str, Any] = {}
    required_coverage: Dict[str, Any] = {}
    required_form: Dict[str, Any] = {}
    required_blockers: List[Blocker] = []
    try:
        client = _open_publish_page(ctx)
        for entry in expected:
            label = entry["label"]
            want = entry["value"]
            try:
                got = _read_expected_value(client, page, entry)
            except (locating.LabelNotFound, locating.LabelAmbiguous) as exc:
                unreadable.append({"label": label, "expected": want,
                                   "reason": "{}: {}".format(type(exc).__name__, exc)})
                continue
            except page.PageError as exc:
                # 「**读不到**」也要算阻塞，不能当作通过（`_read_expected_value` 在
                # 两种读法都拿不到值时抛这个）。这与 `LabelNotFound` 是同一类事实，
                # 只是来源不同读法。
                unreadable.append({"label": label, "expected": want,
                                   "reason": "{}: {}".format(type(exc).__name__, exc)})
                continue
            # 下拉框读回的是显示文本；平台可能规范化（去空格、改大小写），所以比对前 strip
            if (got or "").strip() == want.strip():
                # ⚠️ **`veto_only` 的项匹配时不计入 `matched`。**
                #
                # 「提交按钮可点」这类项只能做**否决**（禁用 → 一定不能提交），
                # 可用时**什么也证明不了**——平台是点击之后才校验的。
                # 把它算进「N 项一致」会虚增计数，还会给读的人
                # 「平台说可以提交」的误导印象。
                if entry.get("veto_only"):
                    vetoes_passed.append({"label": label, "value": got,
                                          "note": "只做否决；通过不构成放行信号"})
                else:
                    matched.append({"label": label, "value": got})
            else:
                mismatched.append({"label": label, "expected": want, "actual": got})

        required_coverage, required_blockers = _read_required_property_values(client, page)
        required_form, form_blockers = _read_required_form_controls(client, page)
        required_blockers.extend(form_blockers)
        if ctx.item.images.detail or ctx.item.images.sku or any(s.image_path for s in ctx.item.skus):
            try:
                verify_bound_media(client, ctx.item, ctx.resolved_contracts(), ctx.scratch.get('bound_media', {}))
            except page.PageError as exc:
                required_blockers.append(Blocker(code='READBACK_MISMATCH', field='images',
                                                detail=exc.detail, source='stages.stage_readback'))

        # ⚠️ **必须在 `client` 还开着的时候读。**
        #
        # 我最初把这段放在 `finally: client.close()` **之后**——
        # 于是在一个已关闭的连接上读：**链条里全是空，而单独测是好的**。
        # 「两种环境不一致」最容易被漏掉。
        #
        # 这几行**不核对**，只如实报告：它们由平台/店铺默认值决定，
        # 平台不要求填（第 77 轮：无阻塞错误、按钮可用）。
        # **流水线不该设它们**——那会越过「不猜字段」的红线。
        #
        # 但「不设」不等于「不用告诉操作人」：
        # **`上架时间` 实测默认「立刻上架」**——一旦提交，商品立即公开在售，
        # 而这条默认值此前没被任何人看过（`submit` 从未执行过）。
        for _label in ("上架时间", "发货时间", "提取方式"):
            try:
                default_notice[_label] = page.read_selected_options(client, _label)
            except Exception as _exc:  # noqa: BLE001
                # **不吞**：记下原因，summary 里说「未读到（原因）」。
                # 返回空列表会把「读失败」伪装成「没有选中项」——
                # 那正是我第一版犯的错（红线：不用兜底掩盖真实问题）。
                default_notice[_label] = {
                    "error": "{}: {}".format(type(_exc).__name__, str(_exc)[:80])}
    finally:
        if client is not None:
            client.close()

    ctx.scratch["readback"] = {
        "matched": matched, "mismatched": mismatched, "unreadable": unreadable,
        "vetoes_passed": vetoes_passed,
        "required_field_coverage": required_coverage,
        "visible_form_requirements": required_form,
        "required_blockers": [blocker.to_dict() for blocker in required_blockers],
    }

    if mismatched or unreadable or required_blockers:
        blockers: List[Blocker] = list(required_blockers)
        for item in mismatched:
            blockers.append(Blocker(
                code="READBACK_MISMATCH", field=item["label"],
                detail="期望 {!r}，实际 {!r}".format(item["expected"], item["actual"]),
                source="stages.stage_readback",
            ))
        for item in unreadable:
            blockers.append(Blocker(
                code="READBACK_UNREADABLE", field=item["label"],
                detail=item["reason"],
                source="stages.stage_readback",
            ))
        outcome = StageOutcome.failed(
            "READBACK_FAILED",
            "回读核对未通过：一致 {} 项，不一致 {} 项，读不到 {} 项，实际必填字段阻塞 {} 项".format(
                len(matched), len(mismatched), len(unreadable), len(required_blockers)),
            blockers=blockers,
        )
        if required_blockers:
            outcome.summary += "；" + "；".join("{}：{}".format(b.field, b.detail or b.message) for b in required_blockers[:4])
        outcome.data = {"required_field_coverage": required_coverage, "visible_form_requirements": required_form}
        return outcome

    # ⚠️ **这三行不核对，只如实报告。**
    #
    # 它们由**店铺默认值**决定，平台不要求填（第 77 轮验证过：无阻塞错误、
    # 提交按钮可用）。**流水线不该去设它们**——那会越过「不猜字段」的红线。
    #
    # **但「不设」不等于「不用告诉操作人」**：商品按什么物流条款上架，
    # 发布之后没有任何地方会说。若店铺默认值与这件商品不符，
    # 货就按错的条款发出去了。
    #
    # **不做成 pass/fail**——我们没有立场说哪个值「对」，那是店铺政策。
    # **也不新增核对项**——第 70 轮的教训：虚增计数会让人误判。
    # `data` 是给程序看的，**操作人看的是 summary**。
    # ⚠️ 另起一句，**不动「N 项一致」那个数字**（第 70 轮的教训：虚增计数会让人误判）。
    notice_bits = []
    for _label, _picked in default_notice.items():
        if isinstance(_picked, dict):
            # 读失败：**说清是失败**，不是「没有」
            notice_bits.append("{}（未读到：{}）".format(_label, _picked.get("error", "未知")))
        else:
            notice_bits.append("{}={}".format(
                _label, "、".join(_picked) if _picked else "未读到"))
    notice_text = ("；顺带读到的**平台默认值**（本流水线不设，但影响上架结果）：{}".format(
        "，".join(notice_bits)) if notice_bits else "")
    required_notice = ("；当前可见类目必填属性 {} 项有值"
                       "（覆盖 label.required 属性行，尚不代表整页必填项均已验证）".format(
                           required_coverage.get("checkedCount", 0)))

    return StageOutcome(
        ok=True,
        summary="回读核对通过：{} 项全部一致（{}）".format(
            len(matched), "、".join(item["label"] for item in matched)) + required_notice + notice_text,
        data={"matched": matched, "mismatched": [], "unreadable": [],
              "vetoes_passed": vetoes_passed,
              "required_field_coverage": required_coverage,
              "visible_form_requirements": required_form,
              # 这几行**不核对**，只报告——它们是平台/店铺默认值，不是流水线该判的。
              # `上架时间` 在其中：**实测默认「立刻上架」**，
              # 而 `submit` 从未执行过，这条默认值此前没被任何人看过。
              "default_notice": default_notice},
    )


def stage_fill_freight(ctx: PipelineContext) -> StageOutcome:
    """阶段 ``fill_freight``：选择运费模板。**写阶段**（登记为 ``save_draft``）。

    未明确商品模板时仅核验当前账户页面的已选项，不猜默认列表顺序。
    调用方的模板清单接口仍为 /api/shop/freight-templates；本阶段不增加设置向导。

    为什么必须**精确匹配**模板名：运费模板选错，货就按别人的运费规则发出去，
    而且**发出去才发现**。所以命中 0 或多个都失败，并把当时可选的模板列出来——
    让调用方知道该改成哪个名字，而不是让程序猜一个「最接近」的。

    实测该下拉**不带搜索框**（与品牌下拉不同），选项直接列在
    ``li.next-menu-item`` 里，用 ``.next-menu-item-text`` 取文本。
    """

    from . import page

    name = (ctx.item.freight_template_name or "").strip()
    from_page_selection = not bool(name)
    client = None
    try:
        client = _open_publish_page(ctx)
        before = page.read_freight_template(client)
        if from_page_selection:
            name = str(before or '').strip()
            if not name:
                return StageOutcome.failed(
                    "EVIDENCE_INSUFFICIENT", "当前账户页面没有已选运费模板，也未明确提供商品模板；不能猜默认项",
                    blockers=[Blocker(code="EVIDENCE_INSUFFICIENT", field="logistics.freight_template_id",
                                      detail="需要当前店铺真实已选模板或明确商品模板，不复用抖店模板",
                                      source="stages.stage_fill_freight")])
        opened = page.open_freight_dropdown(client)
        options = page.read_freight_options(client)
        if not options:
            return StageOutcome.failed(
                "EVIDENCE_INSUFFICIENT",
                "运费模板下拉里没有读到任何选项（下拉可能没展开，或该店铺没有模板）",
                blockers=[Blocker(
                    code="EVIDENCE_INSUFFICIENT", field="logistics.freight_template_id",
                    detail="实测该下拉不带搜索框，选项直接列在 li.next-menu-item 里；读到 0 个说明结构变了或确实没有模板",
                    source="stages.stage_fill_freight",
                )],
            )
        if name not in options:
            return StageOutcome.failed(
                "FREIGHT_TEMPLATE_NOT_FOUND",
                "店铺里没有名为 {!r} 的运费模板；当前可选：{}".format(name, "、".join(options)),
                blockers=[Blocker(
                    code="FREIGHT_TEMPLATE_NOT_FOUND", field="item.freight_template_name",
                    detail="可选模板：{}".format("、".join(options)),
                    source="stages.stage_fill_freight",
                )],
            )

        picked = page.pick_freight_option(client, name)
        after = page.wait_for_freight_value(client, name)
        if after != name:
            return StageOutcome.failed(
                "READBACK_MISMATCH",
                "选中运费模板后回读不一致：期望 {!r}，实际 {!r}".format(name, after),
                blockers=[Blocker(
                    code="READBACK_MISMATCH", field="item.freight_template_name",
                    detail="下拉可能没有真正生效；不要在此状态下继续发布",
                    source="stages.stage_fill_freight",
                )],
            )
    except Exception as exc:  # noqa: BLE001
        return StageOutcome.failed(
            getattr(exc, "code", "PAGE_ERROR"),
            "填运费模板失败：{}".format(exc),
            blockers=page.blockers_for(exc, stage="fill_freight") if client is not None else None,
        )
    finally:
        if client is not None:
            client.close()

    ctx.scratch["fill_freight"] = {
        "template": name, "before": before, "options": options, "picked": picked,
        "source": "current_page_selection" if from_page_selection else "explicit_product",
    }
    return StageOutcome(
        ok=True,
        summary="运费模板已选并回读确认：{!r}（写入前为 {!r}；该店铺共 {} 个模板）".format(
            name, before, len(options)),
        data={"template": name, "before": before, "options": options},
    )


def stage_save_draft(ctx: PipelineContext) -> StageOutcome:
    """阶段 ``save_draft``：把填好的商品**存成后台草稿**（不上架）。

    ⚠️ **默认不执行**：只有调用方显式要求（``ctx.scratch["save_draft_requested"]``）
    时才点按钮；否则**一个动作都不做**，如实报"未请求"。这样既守住"默认零写入"，
    又让"整条链走到保存草稿"这件事可被验证。

    **判据**：点完之后必须观察到**新增**的页面反馈（或 URL 变化）才算数。
    ⚠️ 不能把"页面上有提示文本"当成"保存成功"——页面本来就飘着一堆说明文字
    （实测 5 条以上），那是点击前就存在的（`wait_for_submit_outcome` 的注释里记着
    这个坑：原判据 0.0 秒就返回、把旧提示当成结果）。所以用 `before_messages` 做差，
    等不到新增反馈就**如实报"点了但读不到结果"**，不假装成功。
    """

    if not ctx.scratch.get("save_draft_requested"):
        return StageOutcome.skipped("未请求保存草稿（默认不做任何动作）")

    from . import page

    client = None
    try:
        client = _open_publish_page(ctx)
        before = page.read_submit_outcome(client)
        before_href = str(before.get("href") or "")
        before_messages = [m.get("text") for m in (before.get("messages") or []) if m.get("text")]
        before_dialogs = [str(d.get("text") or "") for d in (before.get("dialogs") or [])]
        page.click_button_by_text(client, page.SAVE_DRAFT_BUTTON_TEXT)
        outcome = page.wait_for_submit_outcome(
            client, before_href, before_messages=before_messages, timeout=25.0, interval=0.5)
        after = client.evaluate(page.build_read_submit_outcome_expression(), timeout=30.0)
    except Exception as exc:  # noqa: BLE001
        return StageOutcome.failed(
            getattr(exc, "code", "PAGE_ERROR"),
            "保存草稿失败：{}".format(exc),
            blockers=page.blockers_for(exc, stage="save_draft") if client is not None else None,
        )
    finally:
        if client is not None:
            client.close()

    fresh = [str(t) for t in (outcome.get("new_messages") or [])]
    # ⚠️ **新出现的对话框是最强信号**：实测保存草稿后平台弹
    # `next-dialog … next-dialog-quick`（「草稿箱最大保存 10 条草稿…确定」），
    # 而页面上**没有任何"成功"字样**。对话框是"平台处理了这次动作"的可观察证据，
    # 与页面常驻的静态说明文字（点击前就在）不是一回事。
    after_dialogs = [str(d.get("text") or "") for d in ((after or {}).get("dialogs") or [])]
    fresh_dialogs = [t for t in after_dialogs if t not in before_dialogs]
    ctx.scratch["save_draft"] = {"changed": bool(outcome.get("changed")),
                                 "new_messages": fresh,
                                 "new_dialogs": fresh_dialogs,
                                 "href": outcome.get("href")}
    if not fresh_dialogs:
        # 没有新对话框 = 平台没给出可观察的响应。**不谎称成功**——
        # 「草稿箱最大保存 10 条」这句静态说明既可能在点击前就有，也无法证明保存发生了。
        return StageOutcome.failed(
            "READBACK_UNREADABLE",
            "已点「保存草稿」，但页面上没有出现新的对话框（等 25 秒）——无法确认平台处理了这次保存",
            blockers=[Blocker(
                code="READBACK_UNREADABLE", field="publish.draft",
                detail="保存草稿的成功特征尚未实证；点击后必须观察到**新出现的对话框**才算"
                       "平台有响应。页面常驻的静态提示（如「草稿箱最大保存 10 条」）不算证据",
                source="stages.stage_save_draft")],
        )
    return StageOutcome(
        ok=True,
        summary="已点保存草稿，平台弹出了新对话框（说明平台处理了这次保存）：{}".format(
            fresh_dialogs[0][:60]),
        data={"save_draft": ctx.scratch["save_draft"]},
    )


def stage_submit(ctx: PipelineContext) -> StageOutcome:
    """阶段 ``submit``：提交发布。**整套流水线里唯一真正把商品推上平台的一步。**

    执行器已经替本处理器挡住了两件事，处理器里**不再重复判断**（重复判断会让人
    误以为这里是唯一的关卡）：

    * ``STAGE_WRITE_OPERATION["submit"] == "submit_publish"``；
    * ``submit_publish`` 需要**两把锁**同时满足——``TAOBAO_UPLOAD_ALLOW_WRITE``
      里含 ``submit_publish``，且 ``TAOBAO_UPLOAD_ALLOW_SUBMIT`` 精确为 ``"1"``；
    * ``dry_run=True`` 时整个阶段被跳过。

    ## 诚实边界（必须读）

    **提交通道的成功特征尚未实证。** 本阶段没有真的提交过任何商品，
    因此它**不声称成功**：它报告「已点击」以及能观察到的页面变化
    （URL 变化、提示文本），最后一句永远是「请在卖家中心核对是否上架成功」。

    把「点了按钮」当成「发布成功」是这类工具最容易犯、也最难发现的错误——
    商品可能因为没有填必填项而被平台退回，而界面上什么都不会说。

    ⚠️ **「按钮可用」不等于「表单填完了」**（实测）。2026-10-03 的守卫验证里，
    宝贝标题是空的、提交按钮却仍是 enabled——**平台是在点击之后才做校验的**。
    所以本阶段把「按钮禁用」当作**否决信号**（禁用就一定不能提交），
    但**不把「按钮可用」当作放行信号**：真正的前置校验由前面的 ``readback``
    阶段负责，它按 ``expected_field_values`` 逐项核对。
    """

    # ⚠️ **前置条件先查，再连页面。** 放在打开浏览器之后是错的：
    # 条件不满足时根本不该去连页面，而且那样也没法离线测。
    #
    # 回读必须是**硬前置条件**，不能只是「记一笔」。原来只把 readback 的结论
    # 记进结果里，文档写着「真正的前置校验由前面的 readback 阶段负责」——
    # 但那只是**对计划的假设**，不是被强制的不变量：任何直接调用
    # `run_stage(ctx, "submit")` 的路径都会**完全跳过 readback**。
    # 平台是**点击之后才校验**的（实测：标题为空时按钮仍然可用），
    # 所以「按钮可用」根本不能当放行信号。这里 fail closed。
    # ⚠️ **回读必须是硬前置条件，不能只是「记一笔」。**
    #
    # 原来这里只把 readback 的结论记进结果里，文档写着「真正的前置校验由前面的
    # readback 阶段负责」——但那只是**对计划的假设**，不是被强制的不变量：
    # 任何直接调用 `run_stage(ctx, "submit")` 的路径（比如守卫验证脚本、
    # 或将来某个绕开 run() 的调用方）都会**完全跳过 readback**，
    # 于是「凭一个可用的按钮就点下去」。
    #
    # 平台是**点击之后才校验**的（实测：标题为空时按钮仍然可用），
    # 所以「按钮可用」根本不能当放行信号。这里 fail closed：
    # 没有本次运行的回读结论，就不点。
    readback = ctx.scratch.get("readback")
    if not isinstance(readback, dict) or "matched" not in readback:
        return StageOutcome.failed(
            "SUBMIT_WITHOUT_READBACK",
            "本次运行没有回读核对结果，拒绝提交——"
            "「按钮可用」不等于「表单填对了」，平台是点击之后才校验的",
            blockers=[Blocker(
                code="SUBMIT_WITHOUT_READBACK", field="readback",
                detail="submit 必须跑在通过的回读核对之后；"
                       "请走完整流水线（readback 阶段会逐项核对），"
                       "不要单独调用 submit",
                source="stages.stage_submit",
            )],
        )
    if readback.get("mismatched") or readback.get("unreadable") or readback.get("required_blockers"):
        return StageOutcome.failed(
            "SUBMIT_BLOCKED_BY_FORM",
            "回读核对有未通过项（不一致 {} 项、读不到 {} 项），拒绝提交".format(
                len(readback.get("mismatched") or []),
                len(readback.get("unreadable") or [])),
            blockers=[Blocker(
                code="SUBMIT_BLOCKED_BY_FORM", field="readback",
                detail="submit 只有在回读逐项核对通过之后才允许执行",
                source="stages.stage_submit",
            )],
        )

    from . import page

    client = None
    try:
        client = _open_publish_page(ctx)
        state = page.read_submit_state(client)
        submit_state = state.get("submit") or {}
        if not submit_state.get("present"):
            return StageOutcome.failed(
                "PAGE_ERROR",
                "页面上没有唯一的「{}」按钮（命中 {}）".format(
                    page.SUBMIT_BUTTON_TEXT, submit_state.get("hitCount")))
        if submit_state.get("disabled"):
            # 禁用是**否决信号**——但反过来不成立：可用不代表填完了。
            # 具体缺哪一项不在这里猜，交给 readback 阶段列出。
            return StageOutcome.failed(
                "SUBMIT_BLOCKED_BY_FORM",
                "「{}」处于禁用状态，表单尚未填完；请先看 readback 阶段的阻塞项".format(
                    page.SUBMIT_BUTTON_TEXT),
                blockers=[Blocker(
                    code="SUBMIT_BLOCKED_BY_FORM", field="",
                    detail="提交按钮 disabled；常见原因是必填项未填，或选完类目后未选品牌",
                    source="stages.stage_submit",
                )],
            )

        checked_fields = len(readback.get("matched") or [])

        before_href = str(state.get("href") or "")
        # ⚠️ **必须在点击前取一次基线。**
        #
        # 页面上本来就飘着一堆 `.next-message`（说明文字、历史提示）。
        # 实测（2026-10-03）：未提交的页面上有 5 条，而原判据
        # 「有提示文本就算有变化」因此 **0.0 秒**就返回，
        # 把这 5 条**点击前就存在**的提示当成「提交的结果」——
        # **提交什么都没发生时也会报「观察到页面响应」。**
        #
        # 传了基线之后，只有**新增**的提示才算变化。
        before_outcome = page.read_submit_outcome(client)
        before_messages = [m.get("text") for m in (before_outcome.get("messages") or [])
                           if m.get("text")]
        page.click_submit_button(client)
        outcome = page.wait_for_submit_outcome(client, before_href,
                                               before_messages=before_messages)
    except Exception as exc:  # noqa: BLE001
        return StageOutcome.failed(
            getattr(exc, "code", "PAGE_ERROR"),
            "提交失败：{}".format(exc),
            blockers=page.blockers_for(exc, stage="submit") if client is not None else None,
        )
    finally:
        if client is not None:
            client.close()

    messages = [m.get("text") for m in (outcome.get("messages") or []) if m.get("text")]
    # **只认新增的提示**——`messages` 里大部分是页面本来就有的说明文字。
    fresh = [str(t) for t in (outcome.get("new_messages") or [])]
    changed = bool(outcome.get("changed"))
    href_after = str(outcome.get("href") or "")
    navigated = bool(href_after) and href_after != before_href

    ctx.scratch["submit"] = {
        "clicked": True, "href_before": before_href, "href_after": href_after,
        "navigated": navigated, "messages": messages,
        "new_messages": fresh, "changed": changed,
        "messages_before": before_messages,
        "readback_checked_fields": checked_fields,
    }

    # **三种情形分开说**，尤其是第三种——原判据永远不会说它。
    if navigated:
        detail = "页面已跳转到 {}".format(href_after)
    elif fresh:
        detail = "页面出现新提示：{}".format("；".join(fresh)[:160])
    else:
        detail = ("点击后没有观察到页面变化"
                  "（页面上有 {} 条提示，但**都是点击前就有的**）".format(len(messages)))

    return StageOutcome(
        ok=True,
        summary=(
            "已点击「{}」并观察到页面响应（{}）。"
            "**注意：提交通道的成功特征尚未实证，本阶段不声称发布成功——"
            "请在卖家中心核对是否上架。**"
        ).format(page.SUBMIT_BUTTON_TEXT, detail),
        data={
            "clicked": True,
            "navigated": navigated,
            "changed": changed,
            "href_before": before_href,
            "href_after": href_after,
            "messages": messages,
            # 只含**点击后新出现**的提示；`messages` 里还有页面本来就有的说明文字。
            "new_messages": fresh,
            # 点击**前**页面上的提示。带上它，事后才能判断
            # 「哪些是新出现的」——没有基线的话，一堆旧提示与真响应分不开。
            "messages_before": before_messages,
            # 明确标出「成功与否未确认」，避免调用方把 ok=True 当成「已上架」
            "publish_confirmed": False,
            "confirmation_required": "请在卖家中心核对商品是否出现在出售中/仓库中",
            # 提交前做过逐项核对的字段数。**按钮可用不代表表单有效**，
            # 这个数字让调用方能判断「到底有没有核对过」。
            "readback_checked_fields": checked_fields,
        },
    )


def _desired_specs(item: PublishItem) -> "OrderedDict[str, List[str]]":
    """从 ``item.skus`` 反推「属性名 → 去重后的值列表」，保持首次出现顺序。

    顺序很重要：表格行的排列跟着值的加入顺序走，回读时要按同样的顺序比对。
    """

    ordered: "OrderedDict[str, List[str]]" = OrderedDict()
    for sku in item.skus:
        for name, value in (sku.spec_values or {}).items():
            clean_name = str(name or "").strip()
            clean_value = str(value or "").strip()
            if not clean_name or not clean_value:
                continue
            bucket = ordered.setdefault(clean_name, [])
            if clean_value not in bucket:
                bucket.append(clean_value)
    return ordered


def _sku_spec_key(spec_values) -> str:
    """把一条 SKU 的规格值排成**可精确比对**的键。

    只按值的集合比，不按字典顺序——`spec_values` 的键序不保证稳定。
    """

    values = [str(v).strip() for v in (spec_values or {}).values() if str(v).strip()]
    return "、".join(sorted(values))


def _fill_sku_row_numbers(client, page, ctx: PipelineContext) -> List[Dict[str, Any]]:
    """按**规格值**把每行的价格 / 库存填上，并回读确认。

    ⚠️ **不按行序号匹配。** 行是平台按属性值生成的，顺序不保证与 `item.skus` 一致；
    按序号填会把价格填到别的规格上——那是猜，踩红线。

    匹配不上就**失败**，并把当时行上的规格值与可用的 SKU 都列出来，
    让调用方能改对，而不是让程序猜一个。

    返回每行实际填进去的值，供上游记录。
    """

    # `CandidateNotFound` 定义在 `page.py`（是 `PageError` 的子类），
    # 不在 `errors.py`——本模块其它地方也是从 `page` 取的。
    rows = list(page.read_sku_table(client).get("rows") or [])
    if not rows:
        # ⚠️ **这里返回空，不抛错。**
        #
        # 「表格根本没出现」是比「没有行可以填价格」更具体的诊断，
        # 由阶段后面那两处检查报出来（`SKU_CREATE_SILENT_FAILURE` /
        # `READBACK_MISMATCH`）。在这里抢先抛 `CandidateNotFound`
        # 会把那个更有用的诊断盖掉——实测就是这样：
        #   AssertionError: 'CANDIDATE_NOT_FOUND' != 'SKU_CREATE_SILENT_FAILURE'
        #
        # **不是兜底**：跳过之后仍然会失败，只是由更准确的那条报出来。
        return []

    by_spec = {}
    for sku in (ctx.item.skus or []):
        key = _sku_spec_key(getattr(sku, "spec_values", None))
        if key:
            by_spec.setdefault(key, []).append(sku)

    ambiguous_specs = [(key, candidates) for key, candidates in by_spec.items()
                       if len(candidates) != 1]
    if ambiguous_specs:
        key, candidates = ambiguous_specs[0]
        raise page.CandidateNotFound(
            "SKU 规格值 {!r} 在 item.skus 里匹配到 {} 条；未填写价格库存".format(
                key, len(candidates)))

    if len(rows) != len(ctx.item.skus):
        raise page.CandidateNotFound(
            "SKU 表格行数不完整：期望 {} 行，实际 {} 行；未填写价格库存".format(
                len(ctx.item.skus), len(rows)))

    plan = []
    seen_rows = set()
    for index, row in enumerate(rows):
        row_key = "、".join(sorted(str(s).strip() for s in (row.get("specs") or [])
                                 if str(s).strip()))
        candidates = by_spec.get(row_key) or []
        if row_key in seen_rows:
            raise page.CandidateNotFound(
                "SKU 表格含重复规格 {!r}；未填写价格库存".format(row_key))
        seen_rows.add(row_key)
        if len(candidates) != 1:
            raise page.CandidateNotFound(
                "SKU 第 {} 行的规格值 {!r} 在 item.skus 里匹配到 {} 条；"
                "表格里的行：{}；可用的规格：{}".format(
                    index + 1, row_key, len(candidates),
                    " / ".join("、".join(r.get("specs") or []) for r in rows),
                    " / ".join(sorted(by_spec)) or "（无）"))
        plan.append((index, candidates[0], row_key))

    filled: List[Dict[str, Any]] = []
    for index, sku, row_key in plan:
        price = "" if sku.price is None else _format_price(float(sku.price))
        stock = "" if sku.stock is None else str(int(sku.stock))
        page.set_sku_row_numbers(client, index, price=price, stock=stock)
        filled.append({"row": index + 1, "specs": row_key,
                       "price": price, "stock": stock})

    # **回读确认**：「设了」不等于「设对了」。
    after = list(page.read_sku_row_numbers(client))
    if len(after) != len(plan):
        raise page.CandidateNotFound(
            "SKU 价格库存回读行数不完整：期望 {} 行，实际 {} 行".format(
                len(plan), len(after)))
    for index, sku, row_key in plan:
        actual = after[index] if index < len(after) else {}
        want_price = "" if sku.price is None else _format_price(float(sku.price))
        want_stock = "" if sku.stock is None else str(int(sku.stock))
        got_price = str(actual.get("price") or "").strip()
        got_stock = str(actual.get("stock") or "").strip()
        if _as_number(got_price) != _as_number(want_price):
            raise page.CandidateNotFound(
                "SKU 第 {} 行（{}）的价格没有设上：期望 {!r}，实际 {!r}".format(
                    index + 1, row_key, want_price, got_price))
        if _as_number(got_stock) != _as_number(want_stock):
            raise page.CandidateNotFound(
                "SKU 第 {} 行（{}）的库存没有设上：期望 {!r}，实际 {!r}".format(
                    index + 1, row_key, want_stock, got_stock))

    return filled


def _as_number(text: str):
    """把数字文本归一化后比较——`16.80` 与 `16.8` 应当视为相同。"""

    try:
        return float(str(text).strip() or "0")
    except (TypeError, ValueError):
        return str(text).strip()


def stage_fill_skus(ctx: PipelineContext) -> StageOutcome:
    """阶段 ``fill_skus``：创建销售规格并回读 SKU 表格。**写阶段**（登记为 ``save_draft``）。

    ## 为什么必须显式处理「不需要的属性」

    E-097（2026-10-03 实测）：分层展示·选择标准属性模式下，**只要有一个已勾选属性
    没有值，「确认创建」就静默失败**——抽屉不关、表格不出现、**不报错、按钮也不禁用**。
    实测 15 秒密集轮询毫无变化。

    所以本阶段做两件事：
    1. 把 ``item`` 里没有的属性**显式取消勾选**；
    2. 提交前**逐个校验**每个已勾选属性都有值，不满足就直接失败并说明原因，
       而不是点下去然后等一个不会出现的结果。

    ## 成败判据

    「点到了确认创建」不等于「创建成功」。唯一可靠的判据是
    :func:`page.wait_for_sku_table` —— 表格出现且行数符合预期。
    """

    blocked = _stage_adapter_guard(ctx, 'fill_skus')
    if blocked is not None:
        return blocked

    from . import page

    if ctx.item.sku_mode == 'custom':
        return _stage_fill_custom_skus(ctx)

    desired = _desired_specs(item=ctx.item)
    if not desired:
        return StageOutcome.failed(
            "EVIDENCE_INSUFFICIENT",
            "没有可用于创建规格的销售属性值（item.skus 里的 spec_values 全为空）",
            blockers=[Blocker(
                code="EVIDENCE_INSUFFICIENT", field="skus",
                detail="销售规格必须由调用方明确给出属性名与属性值；"
                       "属性值还必须是平台标准候选项里的值（E-085）",
                source="stages.stage_fill_skus",
            )],
        )

    expected_rows = 1
    for values in desired.values():
        expected_rows *= len(values)
    if expected_rows != len(ctx.item.skus):
        # 不是硬错误：调用方可能只给了部分组合。但必须说清楚，否则回读行数对不上
        # 会被误判成「创建失败」。
        ctx.scratch["fill_skus_row_mismatch"] = {
            "expected_from_specs": expected_rows, "skus_given": len(ctx.item.skus),
        }

    client = None
    try:
        client = _open_publish_page(ctx)
        page.open_sku_drawer(client)

        state = page.read_sku_drawer_state(client)
        if not state.get("open"):
            return StageOutcome.failed(
                "PAGE_ERROR", "销售规格抽屉没有打开；页面结构可能变了")

        # 1) 先把**不需要**的属性取消勾选。这一步是 E-097 的直接对策。
        deselected: List[str] = []
        for prop in state.get("props") or []:
            name = str(prop.get("name") or "").strip()
            if prop.get("selected") and name and name not in desired:
                page.set_prop_selected(client, name, False)
                deselected.append(name)

        # 2) 需要但没勾选的属性勾上。
        selected_props = {str(p.get("name") or "").strip()
                          for p in (state.get("props") or []) if p.get("selected")}
        for name in desired:
            if name not in selected_props:
                page.set_prop_selected(client, name, True)

        # 3) 逐属性补值。
        added: Dict[str, List[str]] = {}
        for name, values in desired.items():
            before = page.read_sku_drawer_state(client)
            block = next(
                (b for b in (before.get("blocks") or []) if str(b.get("name") or "") == name), None)
            if block is None:
                raise page.CandidateNotFound(
                    "抽屉里没有名为 {!r} 的销售属性；当时可见：{}".format(
                        name, "、".join(str(b.get("name")) for b in (before.get("blocks") or []))))
            present = [str(v).strip() for v in (block.get("rowValues") or []) if str(v).strip()]
            # 有几行是**空的**：属性块一开始就自带一行空行，而此时的「+」是**禁用**的
            # ——必须先把空行填上，「+」才会启用（实测 add_disabled）。
            empty_rows = sum(1 for v in (block.get("rowValues") or []) if not str(v).strip())
            added[name] = list(present)
            for value in values:
                if value in present:
                    continue
                # **先填空行，再考虑加行**：顺序反了会报 add_disabled。
                if empty_rows > 0:
                    empty_rows -= 1
                else:
                    page.add_spec_row(client, name)
                page.pick_spec_value(client, name, value)
                added[name].append(value)

        # 4) **提交前的硬校验**：每个已勾选属性都必须有值（E-097）。
        final_state = page.read_sku_drawer_state(client)
        starved = [
            str(b.get("name") or "")
            for b in (final_state.get("blocks") or [])
            if int(b.get("count") or 0) == 0
        ]
        still_selected = {str(p.get("name") or "").strip()
                          for p in (final_state.get("props") or []) if p.get("selected")}
        # 只有**已勾选**的空属性才会让确认创建静默失败；未勾选的空块无所谓。
        starved = [name for name in starved if name in still_selected]
        if starved:
            return StageOutcome.failed(
                "SKU_SPEC_VALUE_MISSING",
                "已勾选但没有值的销售属性：{}；「确认创建」在这种状态下会静默失败".format(
                    "、".join(starved)),
                blockers=[Blocker(
                    code="SKU_SPEC_VALUE_MISSING", field="skus.{}".format(starved[0]),
                    detail="E-097：分层展示模式下任一已勾选属性为空 → 确认创建不生效且不报错。"
                           "要么补上值，要么显式取消勾选该属性",
                    source="stages.stage_fill_skus",
                )],
            )

        # 5) 点确认创建，等表格出现。
        page.confirm_sku_creation(client)
        table = page.wait_for_sku_table(client, expected_rows=expected_rows)

        rows = int(table.get("rowCount") or 0)
        if table.get("tableCount") and rows > 0 and rows != expected_rows:
            return StageOutcome.failed(
                "READBACK_MISMATCH",
                "SKU 表格行数不符：期望 {} 行，实际 {} 行；未填写价格库存".format(
                    expected_rows, rows),
                blockers=[Blocker(
                    code="READBACK_MISMATCH", field="skus",
                    detail="必须先确认全部销售规格已创建，才能填写各行价格库存",
                    source="stages.stage_fill_skus",
                )],
            )

        # 6) **填每一行的价格与库存。**
        #
        # ⚠️ 这一步长期缺失：`fill_price_stock` 填的是**商品级**「一口价/总库存」，
        # 而 SKU 行自己那两列一直是空的。平台在页面上**可见地**报着
        #     「至少有一个sku的价格大于0，请先设置sku价格」
        # 却没有任何核对发现——因为两边核的是不同的表。
        #
        # **按规格值匹配行与 SKU，不按序号**：行是平台按属性值生成的，
        # 顺序不保证一致；按序号填会把价格填到别的规格上（那是猜）。
        filled_rows = _fill_sku_row_numbers(client, page, ctx)
    except Exception as exc:  # noqa: BLE001
        return StageOutcome.failed(
            getattr(exc, "code", "PAGE_ERROR"),
            "创建销售规格失败：{}".format(exc),
            blockers=page.blockers_for(exc, stage="fill_skus") if client is not None else None,
        )
    finally:
        if client is not None:
            client.close()

    rows = int(table.get("rowCount") or 0)
    spec_rows = [row.get("specs") or [] for row in (table.get("rows") or [])]

    if not table.get("tableCount") or rows == 0:
        # 走到这里说明确认创建没生效。**不谎报成功**——这正是 E-097 的表现。
        return StageOutcome.failed(
            "SKU_CREATE_SILENT_FAILURE",
            "点了「确认创建」但 SKU 表格没有出现（抽屉仍开着：{}）；"
            "这是 E-097 描述的静默失败".format(table.get("drawerOpen")),
            blockers=[Blocker(
                code="SKU_CREATE_SILENT_FAILURE", field="skus",
                detail="确认创建后表格未出现。常见原因：某个已勾选属性没有值、"
                       "或属性值不是平台标准候选项",
                source="stages.stage_fill_skus",
            )],
        )

    if expected_rows > 0 and rows != expected_rows:
        return StageOutcome.failed(
            "READBACK_MISMATCH",
            "SKU 表格行数不符：期望 {} 行，实际 {} 行".format(expected_rows, rows),
            blockers=[Blocker(
                code="READBACK_MISMATCH", field="skus",
                detail="行数不符说明属性值没有全部生效；不要在此状态下继续填价格库存",
                source="stages.stage_fill_skus",
            )],
        )

    ctx.scratch["fill_skus"] = {
        "desired": {k: list(v) for k, v in desired.items()},
        "added": added,
        "deselected": deselected,
        "expected_rows": expected_rows,
        "row_count": rows,
        "spec_rows": spec_rows,
        # 每行实际填进去的价格 / 库存（按规格值匹配，见 `_fill_sku_row_numbers`）。
        "filled_rows": filled_rows,
    }

    return StageOutcome(
        ok=True,
        summary="销售规格已创建并回读确认：{} 个属性、{} 行 SKU（取消勾选 {}）；"
                "每行价格库存已填并回读".format(
                    len(desired), rows, "、".join(deselected) if deselected else "无"),
        data={
            "specs": {k: list(v) for k, v in desired.items()},
            "row_count": rows,
            "expected_rows": expected_rows,
            "deselected": deselected,
            "spec_rows": spec_rows,
            "filled_rows": filled_rows,
        },
    )



def _stage_fill_custom_skus(ctx: PipelineContext) -> StageOutcome:
    from . import page
    from .form_adapters import create_custom_skus, config_for
    client = None
    try:
        config_for(ctx.item, ctx.resolved_contracts(), purpose='sku')
        client = _open_publish_page(ctx)
        _t = time.perf_counter()
        table, bindings = create_custom_skus(client, ctx.item, ctx.resolved_contracts(),
                                            ctx.scratch.get('prepared_media', {}))
        _mark_media_located(ctx, 'sku', ctx.scratch.get('prepared_media', {}).get('sku', []))
        _trace_timing(ctx, 'create_custom_skus', _t)
        _t = time.perf_counter()
        filled = _fill_sku_row_numbers(client, page, ctx)
        _trace_timing(ctx, 'fill_sku_row_numbers', _t)
        ctx.scratch.setdefault('bound_media', {})['sku'] = bindings
        ctx.scratch['fill_skus'] = {'row_count': len(ctx.item.skus), 'filled_rows': filled,
                                   'spec_rows': [r['specs'] for r in table['rows']],
                                   'runtime_control_checks': table.get('runtime_control_checks', {})}
        return StageOutcome(summary='自定义规格、对应图片及逐行售价库存已写入并回读',
                            data={'row_count': len(ctx.item.skus), 'filled_rows': filled,
                                  'runtime_control_checks': table.get('runtime_control_checks', {})})
    except Exception as exc:
        return StageOutcome.failed(getattr(exc, 'code', 'PAGE_ERROR'),
                                   '自定义规格填写失败：{}'.format(exc),
                                   blockers=page.blockers_for(exc, stage='fill_skus'))
    finally:
        if client is not None:
            client.close()


def _mark_media_located(ctx, role, receipts):
    """只有实际选图并回读通过，才把准备回执登记为已定位。"""
    indexed = {}
    for entry in ctx.scratch.get('media_observations', []):
        indexed.setdefault((entry.get('role'), entry.get('path'), entry.get('sha256')), []).append(entry)
    for receipt in receipts:
        observations = indexed.get((role, receipt.get('path'), receipt.get('sha256')), [])
        for observation in observations:
            observation.update(status='located', folder_path=list(receipt.get('folder_path') or []))


def report_media_activity(ctx, message):
    current = ctx.scratch.get('active_stage_progress')
    if current is not None:
        index, total, steps = current
        emit_progress(ctx, index, total, steps, 'upload_images', STEP_RUNNING, message)


def _protocol_upload_hook(ctx):
    """按 ``TAOBAO_MEDIA_ROUTE`` 决定是否返回**协议上传钩子**。

    为什么做成钩子而不是改 ``prepare_media`` 的默认行为：
    默认必须保持原来的 DOM 路线一行不改；协议路线是**显式开关**打开的。
    ``TAOBAO_MEDIA_ROUTE`` 取值不认识时直接抛错（见 ``media_route_from_environment``），
    不做静默回退——静默回退会让人以为跑的是协议。

    钩子做的事：把整批缺图 POST 进图片空间，返回
    ``{文件名: {url, picture_id, uploaded_now}}``。它**不碰页面**。

    ## 为什么改收 ``{file_name: folder_id}`` 而不是裸 batch

    从根层改成**按用途目录**上传（用户诉求："直接上传整个文件夹"）：
    每个条目要落到 ``全部图片/<商品名>/<主图|SKU|详情页>``，
    而 `upload.api` 的目标目录就是一个 `folderId`。所以钩子需要"哪个文件去哪个目录"。

    **目录的解析不在这里做**——解析要读页面目录树（`prepare_media` 那边有页面），
    这里只收结果。这样钩子保持纯传输，职责不混。
    """

    from .protocol_media import (
        ENV_MEDIA_ROUTE, ROUTE_PROTOCOL, media_route_from_environment,
    )
    if media_route_from_environment() != ROUTE_PROTOCOL:
        return None

    def upload(batch, destinations):
        from .cdp_ws import CdpBrowser, CdpClientError, cookie_value
        from .protocol_media import UploadLedger, default_pace_seconds
        from .upload_api import UploadCandidate
        from .upload_page import PictureSpacePageUploader, open_session

        # 按目标目录分组：`folderId` 是上传接口的目标，不能混传。
        by_folder: Dict[str, List[Dict[str, Any]]] = {}
        for entry in batch:
            folder_id = str((destinations or {}).get(entry['name']) or '').strip()
            if not folder_id:
                # **不兜底到根目录**：那正是"图全是散的"的成因。
                # 宁可显式失败，也不悄悄把结构丢掉。
                raise TaobaoPublishError(
                    'IMAGE_UPLOAD_FAILED',
                    '素材 {!r} 没有目标目录 ID，拒绝上传到根目录（会破坏目录结构）'.format(
                        entry['name']),
                )
            by_folder.setdefault(folder_id, []).append(entry)

        port = _taobao_cdp_port(_cdp_port_from_url(getattr(ctx, 'cdp_list_url', '')))
        # --- 断点续传：账本里已经传过的直接复用，不再打平台 ---
        #
        # 平台按频率触发风控（实测连传数十张后回 FAIL_SYS_USER_VALIDATE）。
        # 没有这一步，被风控打断后只能整批重来，而重来会**更快**撞上去。
        #
        # ⚠️ 复用要**按目录校验**：账本键只有"文件名 + sha256"，不含目录。
        # 不校验的话，旧版全部传在根层留下的回执会挡住"改成分目录上传"这个改动
        # ——平台上的图还在根层，程序却认为已经传好了（E-284）。
        ledger = UploadLedger.load()
        reused = ledger.reuse(batch, destinations)
        if reused and callable(getattr(ctx, 'progress', None)):
            report_media_activity(ctx, '{}张素材已有上传回执，跳过重复上传'.format(len(reused)))

        browser = CdpBrowser(port=port)
        session = None
        try:
            fresh: Dict[str, Any] = {}
            # 逐目录上传：每个目录一次 `upload_batch`（同一个 `folderId`）。
            for folder_id, entries in by_folder.items():
                remaining = [entry for entry in entries if entry['name'] not in reused]
                if not remaining:
                    continue
                if session is None:
                    token = cookie_value(browser.cookies(), "_tb_token_")
                    if not token:
                        raise TaobaoPublishError(
                            "LOGIN_REQUIRED",
                            "cookie 里没有 _tb_token_：协议上传需要淘宝登录态",
                        )
                    session = open_session(browser)
                uploader = PictureSpacePageUploader(session)
                candidates = [
                    UploadCandidate(path=entry['path'], name=entry['name'],
                                    size=os.path.getsize(entry['path']),
                                    sha256=str(entry.get('sha256') or ''))
                    for entry in remaining
                ]
                by_name = {entry['name']: entry for entry in remaining}

                def remember(receipt, _by_name=by_name, _folder_id=folder_id):
                    # 每张成功立刻记账：后面被风控打断也不丢已完成的成果。
                    # **连目录一起记**，否则下次复用无法判断"它是不是已经在目标目录"。
                    entry = _by_name.get(receipt.name)
                    if entry is None:
                        return
                    ledger.record(entry, {"url": receipt.url, "picture_id": receipt.picture_id},
                                  folder_id=_folder_id)

                report = uploader.upload_batch(
                    candidates, folder_id=folder_id, authorization=ctx.authorization,
                    progress=lambda message: report_media_activity(ctx, message),
                    pace_seconds=default_pace_seconds(), on_receipt=remember)
                for receipt in report.receipts:
                    fresh[receipt.name] = {
                        "url": receipt.url,
                        "picture_id": receipt.picture_id,
                        "folder": [],
                        "uploaded_now": True,
                    }
                if report.stopped_reason:
                    # 风控：如实上报并停手，**不重试**；已成功的回执（含账本里的）照常带回去。
                    # 平台给的人工验证入口一并交出去——那是**给人用的**，程序不碰。
                    hint = ""
                    if report.challenge_url:
                        hint = "；人工验证入口（平台给的，请本人打开完成）：" + report.challenge_url
                    raise TaobaoPublishError(
                        "VERIFICATION_REQUIRED",
                        report.stopped_reason + hint +
                        "；已完成 {} 张，下次运行会从断点继续".format(len(reused) + len(fresh)),
                    )
                if report.failed:
                    detail = "、".join(
                        "{}：{}".format(item.get('name'), item.get('message'))
                        for item in report.failed[:3])
                    raise TaobaoPublishError("IMAGE_UPLOAD_FAILED", "协议上传未完成：" + detail)
            return {**reused, **fresh}
        except CdpClientError as exc:
            raise TaobaoPublishError("CDP_UNREACHABLE", "协议上传无法连接调试浏览器：{}".format(exc))
        finally:
            if session is not None:
                session.close()
            browser.close()

    return upload


def _cloud_folder_creator(ctx):
    """跨页建目录回调：``(商品名, 角色目录名列表) -> {目录名: folderId}``。

    ## 为什么需要它（2026-10-07 接线，复盘见 docs/35）

    图片空间里没有 ``全部图片/<商品名>/<主图|SKU|详情页>`` 时，**选图器弹层里
    没有任何建目录入口**（E-286 实测：平铺按钮只有「本地上传」、右键不弹菜单）；
    只有**素材中心页**有「新建文件夹」按钮且目录节点带 folderId（E-282）。
    所以建目录要另开一个素材中心标签——那需要 CDP 端口，
    只有流水线这一层（`ctx.cdp_list_url`）拿得到，`form_adapters` 拿不到。

    接上之前的行为：目录不存在就**如实报错**并要求人工去素材中心建
    （`media_library.resolve_role_folder` 的既有语义，不兜底到根目录）。

    ## 授权：先过写授权门，再建

    建目录本身就是**写平台**。而这一步发生在逐图上传的授权检查**之前**
    （`upload_batch` 才逐张 `require`），所以这里必须自己先过一遍：
    没有 ``upload_image`` 授权时**一个目录都不建**——否则会出现
    "图一张没传成、平台上却多了一堆空目录"这种半截状态。
    """

    from .constants import WRITE_UPLOAD_IMAGE
    from .protocol_media import ROUTE_PROTOCOL, media_route_from_environment

    if media_route_from_environment() != ROUTE_PROTOCOL:
        # DOM 路线不需要 folderId（它被 upload_panel 固定成「全部图片」），
        # 保持原来的报错语义，一行行为都不改。
        return None

    def create(product_name, folder_names):
        ctx.authorization.require(WRITE_UPLOAD_IMAGE)
        from .protocol_media import ensure_cloud_folders
        # 端口表达式与 `_protocol_upload_hook` **完全一致**：建目录与上传必须
        # 落在同一个浏览器实例上，否则建完的目录在上传那侧看不见。
        port = _taobao_cdp_port(_cdp_port_from_url(getattr(ctx, 'cdp_list_url', '')))
        return ensure_cloud_folders(port, str(product_name), list(folder_names))

    return create


def _cdp_port_from_url(cdp_list_url: str, default: int = 9334) -> int:
    """从调试地址里取端口；取不到用 9334（本子项目的研究实例端口）。"""

    import re
    match = re.search(r":(\d+)(?:/|$)", str(cdp_list_url or ""))
    if match:
        return int(match.group(1))
    return default


def _taobao_cdp_port(default: int = 9334) -> int:
    """取淘宝调试端口。研究实例固定 9334；应用管理的账户端口段见 ``cdp.py``。"""

    import os as _os
    raw = _os.environ.get('TAOBAO_CDP_PORT')
    if raw and str(raw).strip().isdigit():
        return int(str(raw).strip())
    return default


def stage_fill_detail(ctx: PipelineContext) -> StageOutcome:
    blocked = _stage_adapter_guard(ctx, 'fill_detail')
    if blocked is not None:
        return blocked

    if not ctx.item.images.detail:
        return StageOutcome.skipped('本次没有提供详情图片')
    if ctx.dry_run:
        return StageOutcome.skipped('校对模式不写详情')
    from . import page
    from .form_adapters import (
        detail_receipts_for, detail_uses_module_editor, fill_detail,
        fill_detail_by_picture_id, config_for,
    )
    client = None
    try:
        config_for(ctx.item, ctx.resolved_contracts(), purpose='detail')
        client = _open_publish_page(ctx)
        prepared = dict(ctx.scratch.get('prepared_media') or {})
        # ⚠️ **先补齐回执再决定走哪条路**：`prepared` 只在真跑过 `upload_images`
        # 时才有内容，断点续跑时是空的/不全——那时若拿它判分支，会错误地退回
        # 旧版编辑器路径并报 `detail_editor_not_unique`（实测踩过）。
        detail_receipts = detail_receipts_for(ctx.item, prepared)
        if detail_receipts:
            prepared['detail'] = detail_receipts
        # ⚠️ **按详情区形态选路径**（与 `verify_bound_media` 同一判据）：
        # * 新版**模块编辑器**（真机）：`contenteditable` / `textarea` 都是 0，
        #   必须走「点 `[data-type=pic]` → 按 ID 多选 → 确定」（E-235）；
        # * 旧版**原生编辑区**（夹具 / 部分类目）：直接写 HTML。
        # 只按 `picture_id` 判分支会在旧版形态上硬点一个不存在的图片模块（实测踩过）。
        use_module_editor = detail_uses_module_editor(client)
        has_ids = bool(detail_receipts) and all(r.get('picture_id') for r in detail_receipts)
        if use_module_editor and has_ids:
            bindings = fill_detail_by_picture_id(client, ctx.item, ctx.resolved_contracts(),
                                                 prepared)
        else:
            bindings = fill_detail(client, ctx.item, ctx.resolved_contracts(), prepared)
        ctx.scratch.setdefault('bound_media', {})['detail'] = bindings
        _mark_media_located(ctx, 'detail', prepared.get('detail', []))
        return StageOutcome(summary='详情图片按采集顺序写入并回读',
                            data={'detail_count': len(bindings), 'runtime_control_checks': {'scope': 'current_dom_and_readback', 'image_count': len(bindings)}})
    except Exception as exc:
        return StageOutcome.failed(getattr(exc, 'code', 'PAGE_ERROR'),
                                   '详情填写失败：{}'.format(exc),
                                   blockers=page.blockers_for(exc, stage='fill_detail'))
    finally:
        if client is not None:
            client.close()


def _trace_timing(ctx: PipelineContext, label: str, started: float) -> None:
    """把**阶段内部**的耗时打出来（`TAOBAO_TIMING=1` 时）。

    为什么需要：阶段总耗时只能告诉你"哪个阶段慢"，看不出"慢在哪一步"。
    实测 `upload_images` 占整条流水线 52%（127 秒），而它内部有两大块——
    **协议上传素材**与**逐张选图**——不拆开就无从下手优化。
    产物同时写进 `ctx.scratch['timings']`，便于落盘对比。
    """

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    bucket = ctx.scratch.setdefault('timings', [])
    bucket.append({'label': label, 'elapsed_ms': elapsed_ms})
    if os.environ.get('TAOBAO_TIMING') == '1':
        import sys as _sys
        # ⚠️ 用 ASCII 输出（`ascii()`），避免控制台把中文显示成乱码而误读
        _sys.stderr.write('[timing] {:>7} ms  {}\n'.format(elapsed_ms, ascii(label)))
        _sys.stderr.flush()


def stage_upload_images(ctx: PipelineContext) -> StageOutcome:
    """阶段 ``upload_images``：备齐全部素材，再按原顺序选入主图位。**写阶段**。

    ## 完整链路

    1. 点主图空位 → 打开素材中心弹层 → 切到素材中心的 iframe 上下文；
    2. 查找本商品主图、SKU、详情的已有素材，以内容身份复用可核验的图片；
    3. 合并缺图，点「本地上传」并确认「上传至全部图片」，一次传入文件清单，
       等待整批队列完成并取得图片空间回执，后续各用途复用这些回执；
    4. 选图：逐张点卡片中的 label，弹层关闭时重新打开下一空位；
    5. 关闭仍可见的弹层，核对已填位数和完整 URL 数量。

    ## 判据

    数量与 URL 能确认本次选入及后续稳定性，不能仅凭张数确认既有图片身份。
    任何一步没达到预期都返回失败，绝不把「传上去了」当成「主图设好了」。
    """

    blocked = _stage_adapter_guard(ctx, 'upload_images')
    if blocked is not None:
        return blocked

    from . import page

    images = [str(p) for p in (ctx.item.images.main or []) if str(p).strip()]
    if not images:
        return StageOutcome.failed(
            "EVIDENCE_INSUFFICIENT",
            "没有要上传的主图（item.images.main 为空）",
            blockers=[Blocker(
                code="EVIDENCE_INSUFFICIENT", field="images.main",
                detail="主图必须由调用方明确给出；淘宝要求 1:1、jpg/png/jpeg、至多 5 张",
                source="stages.stage_upload_images",
            )],
        )

    missing = [p for p in images if not os.path.isfile(p)]
    if missing:
        return StageOutcome.failed(
            "REQUIRED_FIELD_MISSING",
            "以下主图在磁盘上不存在：{}".format("、".join(missing[:3])),
            blockers=[Blocker(
                code="REQUIRED_FIELD_MISSING", field="images.main[0]",
                detail="上传前必须先确认文件存在，否则会塞进一个无效路径",
                source="stages.stage_upload_images",
            )],
        )

    # 同一商品同名图片改过内容时必须得到新身份，不能继续复用旧素材。
    # 槽位编号保留相同内容的重复主图及用户指定顺序。
    from .form_adapters import media_file_identity
    try:
        identities = [media_file_identity(path, ctx.item.record_id, 'main', slot=index + 1)
                      for index, path in enumerate(images)]
    except Exception as exc:
        return StageOutcome.failed(getattr(exc, 'code', 'PAGE_ERROR'),
                                   '主图来源读取失败：{}'.format(exc))
    names = [identity['name'] for identity in identities]
    client = None
    try:
        client = _open_publish_page(ctx)
        before = page.read_main_image_slots(client)
        if not before.get("found"):
            return StageOutcome.failed("PAGE_ERROR", "没有唯一可回读的 1:1 主图区；未上传或选图")
        if int(before.get("filled") or 0) > 0:
            return StageOutcome.failed(
                "READBACK_MISMATCH",
                "主图区已有 {} 张图，无法核验它们是否对应本商品；请确认并清理后再运行".format(
                    before.get("filled")),
                blockers=[Blocker(
                    code="READBACK_MISMATCH", field="images.main",
                    detail="平台当前未提供可核验的本地文件到已选主图的映射，不能按已有张数跳过或补前几张；已有图片保留",
                    source="stages.stage_upload_images",
                )],
            )
        page.open_media_popup(client)
        popup = page.read_media_popup(client)
        if not popup.get("open"):
            return StageOutcome.failed("PAGE_ERROR", "图片选择弹层没有打开")
        context_id = page.media_iframe_context(client)
        from .media_library import open_directory, pick_media_by_id_with_requery
        from .form_adapters import prepare_media, bind_prepared_media
        _t0 = time.perf_counter()
        if ctx.prepared_media is not None:
            # 完整准备回执意味着目录和图片已经入库；不能建空目录掩盖交接失败。
            from .media_library import ensure_product_root
            ensure_product_root(client, ctx.prepared_media.manifest.folder_name,
                                context_id=context_id, wait_seconds=8.0)
            prepared = bind_prepared_media(client, ctx.item, ctx.resolved_contracts(), ctx.prepared_media,
                ctx.account_profile, context_id=context_id,
                progress=lambda message: report_media_activity(ctx, message),
                observations=ctx.scratch.setdefault('media_observations', []))
            identities = [{key: entry[key] for key in ('path', 'name', 'sha256')} for entry in prepared['main']]
            names = [entry['name'] for entry in prepared['main']]
        else:
            prepared = prepare_media(client, ctx.item, ctx.resolved_contracts(), context_id=context_id,
                progress=lambda message: report_media_activity(ctx, message), main_identities=identities,
                observations=ctx.scratch.setdefault('media_observations', []),
                protocol_upload=_protocol_upload_hook(ctx),
                # 协议路线下目标目录不存在时**由程序自己建**（开一个素材中心标签）。
                # 不接这一条的话，新商品第一次上架会停在
                # 「图片空间里没有目录 …，请去素材中心建好该目录后重试」。
                folder_creator=_cloud_folder_creator(ctx))
        ctx.scratch['prepared_media'] = {role: prepared.get(role, []) for role in ('sku', 'detail')}
        _trace_timing(ctx, 'prepare_media', _t0)
        main_receipts = list(prepared['main'])
        in_space = [entry['name'] for entry in prepared['main'] if not entry['uploaded_now']]
        uploaded_now = [entry['path'] for entry in prepared['main'] if entry['uploaded_now']]

        # 逐张选中。**点卡片里的 label 即回填**，没有确认按钮。
        #
        # ⚠️ **每张图都要重新打开弹层**：这个选择器的 iframe URL 带 ``max=1``
        # ——一次只能选一张；弹层可能保持打开，需要明确关闭后进入下个空位。
        # 复用同一次打开的弹层会导致后续图片没有填入新的空位。
        #
        # 已有图无法按文件身份核验时在前面停止；从空主图区按商品素材顺序逐张选入。
        selected: List[str] = []
        expected_urls: List[str] = []
        for main_receipt in main_receipts:
            _t_image = time.perf_counter()
            name = main_receipt['name']
            report_media_activity(ctx, '选择主图：{}/{}，核对图片位置'.format(len(selected) + 1, len(names)))
            if selected:
                page.ensure_media_popup_closed(client)
            if not page.read_media_popup(client).get("open"):
                page.open_media_popup(client)
                context_id = page.media_iframe_context(client)
            selected_directory = main_receipt.get('folder_path', [])
            if selected_directory:
                main_receipt['folder_path'] = open_directory(client, selected_directory, context_id=context_id,
                                                            expected_images=[main_receipt])
            # ⚠️ **有 pictureId 就按 ID 精确选**（协议上传的回执里有）。
            #
            # 这是「确定性选择」：`Array.filter` 一次命中，不受同名、虚拟滚动、
            # 遍历上限影响。按名字查找那条路要滚动遍历整个目录（实测 327 张卡片时
            # `search_incomplete`、5~13 秒还 0 命中），只作为没有 ID 时的兜底。
            picture_id = str(main_receipt.get('picture_id') or '')
            if os.environ.get('TAOBAO_MEDIA_DEBUG') == '1':
                import sys as _sys
                _sys.stderr.write(
                    '[media-debug] 选图 name={!r} picture_id={!r} url={!r} keys={}\n'.format(
                        name, picture_id, str(main_receipt.get('url') or '')[:60],
                        sorted(str(key) for key in main_receipt.keys())))
                _sys.stderr.flush()
            if picture_id:
                # `wait` 是"等卡片渲染出来"的上限（E-277）。主图这条以前是 0——
                # 之所以一直没暴露，是因为外层 `open_media_popup` 有固定 3 秒兜着；
                # 但那是**顺带**成立的，不该依赖。这里也给它渲染时间窗。
                try:
                    receipt = pick_media_by_id_with_requery(client, [picture_id], context_id=context_id,
                                                            select=True, wait=10.0, stage='upload_images', expected_urls={picture_id:main_receipt['url']})
                except page.MediaImageMissing:
                    # ⚠️ **弹层重开后的初始加载偶发很慢**（2026-10-08 run37/run44 真机：
                    # 图明明在空间里，10s 轮询 + 点走再点回共 20s 都没等到卡片）。
                    # 「点走再点回」只重拉列表，树和 iframe 都是旧的；重开弹层是
                    # 完整重置——平台对新弹层一定会做初始加载。图若真不在空间里，
                    # 重开后第二次仍会 missing，照常如实抛出。
                    report_media_activity(ctx, '选图器没等到卡片，重开弹层后重试：' + name)
                    page.ensure_media_popup_closed(client)
                    page.open_media_popup(client)
                    context_id = page.media_iframe_context(client)
                    if selected_directory:
                        main_receipt['folder_path'] = open_directory(client, selected_directory, context_id=context_id,
                                                                    expected_images=[main_receipt])
                    receipt = pick_media_by_id_with_requery(client, [picture_id], context_id=context_id,
                                                            select=True, wait=10.0, stage='upload_images', expected_urls={picture_id:main_receipt['url']})
                chosen = (receipt.get('selected') or [{}])[0]
                selected_url = str(chosen.get('url') or '')
                if not selected_url:
                    raise page.FieldMismatchError('按 ID 选图没有返回对应素材的 URL')
            else:
                # 已定位用途目录后直接精确找图；不先在空的父目录等待30秒。
                receipt = page.select_media_image(client, name, context_id=context_id,
                    expected_url=main_receipt.get('url', ''), wait=0,
                    page_number=main_receipt.get('page_number'))
                selected_url = str(receipt.get('url') or '')
                if not selected_url:
                    raise page.FieldMismatchError('选图没有返回对应素材的完整 URL')
            expected_urls.append(selected_url)
            slots = page.wait_for_main_image_slots(client, len(selected) + 1, expected_urls=expected_urls)
            if int(slots.get("filled") or 0) != len(selected) + 1:
                return StageOutcome.failed(
                    "READBACK_MISMATCH",
                    "主图 {!r} 选入后位数不符：期望 {}，实际 {}".format(
                        name, len(selected) + 1, slots.get("filled")),
                )
            actual_urls = [str(url) for url in (slots.get('images') or [])]
            # ⚠️ **不能逐字比 URL**：槽位回读的是转码地址（`…_320x320q80_.webp`），
            # 选图返回的是另一种形态（`…_320x320?t=…`）——同一张图，逐字比必然不等。
            # 判据用稳定资源标识（`O1CN…`）：数量与顺序都得对，身份也得对。
            if len(actual_urls) != len(expected_urls) or not all(
                    page._images_match(actual, expected)
                    for actual, expected in zip(actual_urls, expected_urls)):
                raise page.FieldMismatchError('主图新增位的素材身份或顺序与本次所选素材不一致')
            selected.append(name)
            _mark_media_located(ctx, 'main', [main_receipt])
            _trace_timing(ctx, 'select_image[{}]'.format(name[:24]), _t_image)

        page.ensure_media_popup_closed(client)
        after = page.wait_for_main_image_slots(client, len(images))
    except Exception as exc:  # noqa: BLE001
        return StageOutcome.failed(
            getattr(exc, "code", "PAGE_ERROR"),
            "上传商品图片失败：{}".format(exc),
            blockers=page.blockers_for(exc, stage="upload_images") if client is not None else None,
        )
    finally:
        if client is not None:
            client.close()

    filled = int(after.get("filled") or 0)
    selected_urls = [str(u) for u in (after.get("images") or []) if str(u).strip()]
    # 同上：按**资源标识**核对身份与顺序，不做逐字比较（槽位地址是转码形态）。
    identity_ok = len(selected_urls) == len(expected_urls) and all(
        page._images_match(actual, expected)
        for actual, expected in zip(selected_urls, expected_urls))
    if filled != len(images) or not identity_ok:
        return StageOutcome.failed(
            "READBACK_MISMATCH",
            "主图回读不完整：期望 {} 张，已填 {} 位，可回读 URL {} 个".format(
                len(images), filled, len(selected_urls)),
            blockers=[Blocker(
                code="READBACK_MISMATCH", field="images.main",
                detail="主图位数与素材身份都必须与本次逐张选入的素材一致（按资源标识核对，不逐字比 URL）",
                source="stages.stage_upload_images",
            )],
        )
    ctx.scratch["upload_images"] = {
        "images": images, "uploaded_now": uploaded_now, "selected": selected,
        "file_identities": identities,
        # 每个完整文件名已对应唯一卡片和 URL；保存选入顺序供链尾再次核对。
        # 平台可能重编码图片，不以远端 URL 声称平台字节摘要等于本地摘要。
        "selected_urls": selected_urls,
        "filled_before": before.get("filled"), "filled_after": filled,
        "in_space_before": len(in_space),
    }

    prepared = ctx.scratch.get('prepared_media', {})
    prepared_counts = {role: len(prepared.get(role, [])) for role in ('sku', 'detail')}
    media_summary = ('；SKU 素材 {} 张、详情素材 {} 张已准备'.format(
        prepared_counts['sku'], prepared_counts['detail']) if any(prepared_counts.values()) else '')
    return StageOutcome(
        ok=True,
        summary="主图已选入主图位并回读确认：{} 张（本次新上传 {} 张，空间里原有 {} 张）".format(
            filled, len(uploaded_now), len(in_space)) + media_summary,
        data={
            "selected": selected,
            "uploaded_now": [os.path.basename(p) for p in uploaded_now],
            "filled": filled,
            "filled_before": before.get("filled"),
            "prepared_media": prepared_counts,
        },
    )


def _format_urls(urls) -> str:
    """把一串 URL 拼成**可稳定比对**的形式。

    用 `｜` 连接——与页面读回的顺序一致（主图位是有序的，第 1 张是搜索主图）。
    本地路径与平台 URL 都可能很长，所以这里**不做截断**：
    截断会让「前 N 位相同、后面不同」的两次比对误判为相等。
    """

    return "｜".join(str(u).strip() for u in urls if str(u).strip())


def _format_sku_row_values(rows) -> str:
    """按规格归一化全部价格库存；表格调序不能改变核对结果。"""

    import json

    def number_text(value):
        if value is None or not str(value).strip():
            return ""
        text = str(value).strip()
        try:
            number = Decimal(text)
            return format(number.normalize(), "f") if number.is_finite() else text
        except InvalidOperation:
            return text

    entries = [
        [sorted(str(v).strip() for v in (row.get("specs") or []) if str(v).strip()),
         number_text(row.get("price")), number_text(row.get("stock"))]
        for row in rows
    ]
    entries.sort(key=lambda entry: json.dumps(entry, ensure_ascii=False))
    return json.dumps(entries, ensure_ascii=False, separators=(",", ":"))


def _format_sku_specs(skus) -> str:
    """把 `item.skus` 的规格值排成**可稳定比对**的一串。

    形如 ``1 行：M(37-41)`` / ``2 行：M(37-41)｜L(42-45)``。

    用 `｜` 分行、`、` 分同一行内的多个规格值——两个分隔符都与页面读回的
    `rows[].specs` 一致，这样期望值与实际值可以**逐字符比对**。
    """

    rows = []
    for sku in skus:
        values = sorted(str(v).strip() for v in (getattr(sku, "spec_values", None) or {}).values()
                        if str(v).strip())
        rows.append("、".join(values))
    return _format_sku_specs_from_rows(rows)


def _format_sku_specs_from_rows(rows) -> str:
    """把「每行的规格值」拼成与期望值同构的一串。"""

    joined = "｜".join(sorted(rows))
    return "{} 行：{}".format(len(rows), joined)


def _format_price(value: float) -> str:
    """把价格格式化成稳定的两位小数。

    不用 ``str(float)``：``16.8`` 会变成 ``'16.8'``、``16.80`` 会变成 ``'16.8'``，
    而回读校验是逐字符比对的，格式不稳定会让校验随机失败。
    """

    return "{:.2f}".format(float(value))


#: 阶段 → 处理器。**未列出的阶段一律视为未实现**，不会静默跳过。
#:
#: 注册写阶段之前必须先补齐该阶段的证据（见 ``docs/06-阻塞项.md``），并把
#: ``write_operation`` 声明与 ``STAGE_WRITE_OPERATION`` 对齐——不对齐执行器会直接拒绝。
STAGE_HANDLERS: Dict[str, StageHandlerSpec] = {
    STAGE_SESSION: StageHandlerSpec(run=stage_session, write_operation=None, touches_platform=True),
    STAGE_PRECHECK: StageHandlerSpec(run=stage_precheck, write_operation=None, touches_platform=False),
    # 上传主图登记为 upload_image（会真的把文件传进店铺图片空间）。
    #
    # 链路已完整实证（E-101..E-109）：点空位 → 素材中心 iframe → 本地上传 →
    # setFileInputFiles → 点卡片选图（点即生效、无确认按钮）→ 关弹层 → 回读主图位。
    # **判据是主图位已填数**，任何一步不达预期都返回失败。
    "upload_images": StageHandlerSpec(
        run=stage_upload_images, write_operation="upload_image", mutates_page=True),
    # 以下三个都是**写阶段**，登记为 save_draft（与 STAGE_WRITE_OPERATION 一致）。
    # 执行器会交叉校验这两份声明，不一致直接拒绝执行。
    "fill_base": StageHandlerSpec(
        run=stage_fill_base, write_operation="save_draft", mutates_page=True),
    "fill_props": StageHandlerSpec(
        run=stage_fill_props, write_operation="save_draft", mutates_page=True),
    "fill_required_attrs": StageHandlerSpec(
        run=stage_fill_required, write_operation="save_draft", mutates_page=True,
        runtime_selector_keys=('required.row_marker', 'required.option_item')),
    "fill_skus": StageHandlerSpec(
        run=stage_fill_skus, write_operation="save_draft", mutates_page=True,
        runtime_selector_keys=('sku.custom_mode', 'sku.custom_rows', 'sku.custom_input',
                               'sku.custom_add', 'sku.image_slot', 'sku.table_image')),
    "fill_detail": StageHandlerSpec(
        run=stage_fill_detail, write_operation="save_draft", mutates_page=True,
        runtime_selector_keys=('detail.editor',)),
    "fill_price_stock": StageHandlerSpec(
        run=stage_fill_price_stock, write_operation="save_draft", mutates_page=True),
    "set_listing_time": StageHandlerSpec(
        run=stage_set_listing, write_operation="save_draft", mutates_page=True,
        runtime_selector_keys=('required.row_marker',)),
    # 保存草稿：**默认跳过**（处理器里判 `save_draft_requested`），要求显式请求。
    # 登记为写操作 => 执行器会要 `save_draft` 授权；dry-run 下必然跳过。
    # 按钮在契约里 `selector` 为 null、靠 `label` 文本定位，所以走运行期守卫键。
    "save_draft": StageHandlerSpec(
        run=stage_save_draft, write_operation="save_draft", mutates_page=True,
        runtime_selector_keys=('submit.save_draft_button',)),
    "fill_freight": StageHandlerSpec(
        run=stage_fill_freight, write_operation="save_draft", mutates_page=True),
    # select_category 会选中类目与品牌（页面状态变更），但**不创建草稿、不上架、不提交**，
    # 所以登记表里它是 None。但它确实会动手，因此 mutates_page=True ——
    # 少了这一条，dry-run 会照样去点页面。
    "select_category": StageHandlerSpec(
        run=stage_select_category, write_operation=None, touches_platform=True, mutates_page=True),
    # readback 只读页面，不改任何东西——dry-run 下也应当执行（它正是用来核对状态的）。
    "readback": StageHandlerSpec(
        run=stage_readback, write_operation=None, touches_platform=True, mutates_page=False),
    # submit 是整套流水线里唯一真正把商品推上平台的一步。登记为 submit_publish，
    # 执行器会要求**两把锁**同时满足，且 dry-run 下必定跳过。
    "submit": StageHandlerSpec(
        run=stage_submit, write_operation="submit_publish", mutates_page=True),
}

#: 阶段 → 阻挡它的证据缺口（用于「未实现」的具体说明）。
STAGE_EVIDENCE_GAPS: Dict[str, Sequence[str]] = {
    "upload_images": ("media.main_images",),
    "select_category": ("item.category_id",),
    "fill_base": ("item.title", "item.outer_id"),
    "fill_props": ("item.props",),
    # 必填项不依赖采集数据（取值来自 category_defaults 的稳妥值/类目驱动规则），
    # 所以**没有**证据缺口——缺的只有"逐项回读是否通过"，那由阶段自己保证。
    "fill_required_attrs": (),
    "fill_skus": ("item.sale_props", "item.sale_prop_values"),
    "fill_detail": ("images.detail",),
    "fill_price_stock": ("sku.price", "sku.stock"),
    "fill_freight": ("logistics.freight_template_id",),
    # 上架时间的取值来自页面实测的三个选项 + `DEFAULT_LISTING_MODE`（放入仓库），
    # **不依赖采集数据**，所以没有证据缺口。
    "set_listing_time": (),
    # 保存草稿的成功特征尚未实证（要靠"新增反馈"做差判断），所以证据缺口在这里如实记着。
    "save_draft": ("publish.draft_outcome",),
    STAGE_READBACK: ("item.category_id",),
    STAGE_SUBMIT: ("publish.listing_mode",),
}


# ---------------------------------------------------------------------------
# 执行器
# ---------------------------------------------------------------------------
@dataclass
class StageRun:
    """一次阶段执行的完整记录。"""

    name: str
    outcome: StageOutcome
    elapsed_ms: int = 0
    skipped_for_dry_run: bool = False

    def to_step_record(self) -> StepRecord:
        return StepRecord(
            name=self.name,
            status=self.outcome.status,
            elapsed_ms=self.elapsed_ms,
            summary=self.outcome.summary,
            error_code=self.outcome.error_code,
        )


def stage_label(stage: str) -> str:
    return STAGE_LABELS.get(stage, stage)


def stage_progress_percent(index: int, total: int) -> int:
    """按阶段序号算进度百分比。

    优先用固定的 :data:`STAGE_PCTS` 锚点（与抖店 v4 的进度条观感一致）；
    阶段数量对不上时按线性插值兜底到 0-100 区间。
    """

    if total <= 0:
        return 0
    if total == len(STAGE_PCTS):
        return STAGE_PCTS[max(0, min(index, total - 1))]
    return int(round(100.0 * (index + 1) / total))


def run_stage(
    stage: str,
    ctx: PipelineContext,
    *,
    index: int,
    total: int,
    steps: List[StepRecord],
) -> StageRun:
    """执行一个阶段，并在必要时**先过授权门**。

    执行顺序（顺序本身就是安全设计）：

    1. 写阶段 + ``dry_run`` → 跳过，状态 ``skipped``，绝不触碰平台。
    2. 写阶段 + 未授权 → 失败，**不执行**。
    3. 无处理器 → 未实现。
    4. 执行处理器。

    第 2 步走的是「结构化失败」而不是把异常抛给调用方：``run()`` 的契约是
    *总是*返回一个可展示的结果。安全性不受影响——:meth:`WriteAuthorization.require`
    在**任何平台调用之前**就抛了，这里只是把异常转成前端能显示的错误码。
    """

    # Fail closed：未知阶段**不能**被当成只读阶段放过去。
    # ``STAGE_WRITE_OPERATION.get()`` 对未知键返回 None，若不拦住就等于
    # 「往 STAGE_ORDER 里加一个写阶段但忘了登记」时会静默放行。
    if stage not in STAGE_WRITE_OPERATION:
        return StageRun(
            name=stage,
            outcome=StageOutcome.failed(
                "CONTRACT_INVALID",
                f"未知阶段 {stage!r}：不在 STAGE_ORDER / STAGE_WRITE_OPERATION 登记表中，拒绝执行",
            ),
            elapsed_ms=0,
        )

    # 取消检查放在**最前面**：已经叫停了就不该再有后续动作，连授权判断都不必做。
    if ctx.cancelled():
        return StageRun(
            name=stage,
            outcome=StageOutcome(
                ok=True, status=STEP_CANCELLED,
                summary="已请求取消，本阶段未执行",
            ),
            elapsed_ms=0,
        )

    operation = STAGE_WRITE_OPERATION.get(stage)

    spec = STAGE_HANDLERS.get(stage)
    if spec is not None:
        # 交叉校验两份声明：处理器自己的 write_operation 必须与中央登记表一致。
        # 不一致说明有人给一个「登记为只读」的阶段写了会写平台的处理器——这正是
        # 授权门会被绕过的方式，必须 fail closed 而不是继续跑。
        if spec.write_operation != operation:
            return StageRun(
                name=stage,
                outcome=StageOutcome.failed(
                    "CONTRACT_INVALID",
                    f"阶段 {stage!r} 的处理器声明 write_operation="
                    f"{spec.write_operation!r}，与登记表 {operation!r} 不一致，拒绝执行",
                ),
                elapsed_ms=0,
            )

    ctx.scratch['active_stage_progress'] = (index, total, steps)
    emit_progress(ctx, index, total, steps, stage, STEP_RUNNING, "")

    # dry-run 的语义是「绝不触碰平台」。这里**不能只看 write_operation**：
    # select_category 在登记表里是 None（不产生草稿），但它会点页面选类目与品牌。
    # 只看 write_operation 会让它在 dry-run 下照样动手。见 StageHandlerSpec.mutates_page。
    mutates = operation is not None or (spec is not None and spec.mutates_page)
    if mutates and ctx.dry_run:
        reason = "写操作 {}".format(operation) if operation is not None else "会改变页面状态"
        return StageRun(
            name=stage,
            outcome=StageOutcome.skipped("dry-run：跳过（{}）".format(reason)),
            elapsed_ms=0,
            skipped_for_dry_run=True,
        )

    if operation is not None:
        try:
            ctx.authorization.require(operation)
        except TaobaoPublishError as exc:
            return StageRun(
                name=stage,
                outcome=StageOutcome.failed(
                    exc.code, f"写操作 {operation} 未获授权，已阻止执行", blockers=exc.blockers
                ),
                elapsed_ms=0,
            )

    if spec is not None:
        blocked = _stage_adapter_guard(ctx, stage)
        if blocked is not None:
            return StageRun(name=stage, outcome=blocked, elapsed_ms=0)

    if spec is None:
        gaps = STAGE_EVIDENCE_GAPS.get(stage, ())
        outcome = stage_not_implemented(f"阶段「{stage_label(stage)}」尚未实现", gaps)(ctx)
        return StageRun(name=stage, outcome=outcome, elapsed_ms=0)

    started = time.monotonic()
    try:
        outcome = spec.run(ctx)
    except Exception as exc:  # noqa: BLE001 - 阶段异常必须转成结构化结果，前端要展示
        outcome = StageOutcome.failed(
            getattr(exc, "code", "PLATFORM_ERROR"),
            f"阶段执行异常：{exc}",
            blockers=getattr(exc, "blockers", None),
        )
    elapsed_ms = int((time.monotonic() - started) * 1000)
    return StageRun(name=stage, outcome=outcome, elapsed_ms=elapsed_ms)


def emit_progress(
    ctx: PipelineContext,
    index: int,
    total: int,
    steps: List[StepRecord],
    stage: str,
    status: str,
    summary: str,
) -> None:
    """把进度推给回调。回调异常**不允许**打断流水线（前端渲染问题不该毁掉发布）。"""

    if ctx.progress is None:
        return
    percent = stage_progress_percent(index, total)
    step_dicts = [step.to_dict() for step in steps]
    try:
        ctx.progress(percent, summary or stage_label(stage), stage, step_dicts)
    except Exception:  # noqa: BLE001 - 见 docstring
        pass


def collect_stage_blockers(runs: Sequence[StageRun]) -> List[Blocker]:
    """汇总所有阶段的阻塞项并去重。"""

    collected: List[Blocker] = []
    for run in runs:
        collected.extend(run.outcome.blockers)
    return dedupe_blockers(collected)

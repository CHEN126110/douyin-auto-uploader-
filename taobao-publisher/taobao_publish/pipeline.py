# -*- coding: utf-8 -*-
"""发布流水线编排。

对外只有一个入口 :func:`run`，与抖店 v4 的 ``fxg_protocol_v4.run()`` 同构：
同名参数语义（``progress_callback`` / ``stop_before_submit``）、同形状返回值
（``{success, stage, error, steps, data}``）、失败即中断且保留已完成阶段。

**执行顺序里嵌了三条安全设计**：

1. **静态预检先于一切**。数据不对就不去连浏览器——少一次登录态暴露。
2. **写操作在授权门后面**。dry-run 下写阶段直接跳过；真实运行下未授权即抛错。
3. **未实现的阶段显式失败**，不静默跳过。淘宝发布目前有 7 个阶段未实现，
   这必须被看见，而不是让流水线「跑完」了却什么都没做。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

from .authorization import WriteAuthorization
from .constants import (
    LIVE_VERIFIED_STAGES,
    STAGE_ORDER,
    STAGE_SUBMIT,
    TAOBAO_CDP_LIST_URL,
)
from .contracts import Contracts, load_contracts, validate_contracts, write_route_status
from .errors import TaobaoPublishError, dedupe_blockers, split_by_severity
from .mapping import build_publish_item, build_platform_payload
from .media_manifest import PreparedProductMedia
from .models import (
    STEP_CANCELLED,
    STEP_OK,
    STEP_RUNNING,
    STEP_SKIPPED,
    LocalProduct,
    PipelineResult,
    PublishItem,
    StepRecord,
    build_stage_plan,
)
from .preflight import run_static_preflight
from .stages import (
    PipelineContext,
    ProgressCallback,
    StageRun,
    collect_stage_blockers,
    emit_progress,
    run_stage,
    stage_label,
)

#: 产物目录（相对子项目根）。落盘内容一律已脱敏。
DEFAULT_OUTPUTS_DIR = "outputs"


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# 就绪度
# ---------------------------------------------------------------------------
@dataclass
class Readiness:
    """当前实现与证据的整体就绪度。**每次运行都返回**，不因中途失败而省略。"""

    contract_problems: List[str] = field(default_factory=list)
    protocol_write_ready: bool = False
    dom_write_ready: bool = False
    implemented_stages: List[str] = field(default_factory=list)
    unimplemented_stages: List[str] = field(default_factory=list)
    #: 已注册但**走不到成功**的阶段。目前为空——11 个阶段都能走到成功。
    incomplete_stages: List[str] = field(default_factory=list)
    #: **完整链路尚未在真实页面上跑通**的阶段。
    #:
    #: 与 ``unimplemented_stages`` / ``incomplete_stages`` 都不同：那些说的是
    #: 「代码写没写完」，这一个说的是「有没有在真实页面上从头走到尾」。
    #: 一个阶段可以实现完整、单测全绿，却从没真的跑过——
    #: 把这两者混起来就会报出「能一键发布」而某一步从没被验证过。
    live_unverified_stages: List[str] = field(default_factory=list)
    blocked_required_fields: List[str] = field(default_factory=list)
    blocked_write_critical_selectors: List[str] = field(default_factory=list)
    field_evidence: Dict[str, int] = field(default_factory=dict)

    @property
    def publish_route_ready(self) -> bool:
        """是否存在任一可用的真实发布路线。

        ⚠️ **这不是「现在能发布了」**。它只说明「证据面支持某条路线」。

        2026-10-03 起 ``dom_write_ready`` 为真（30 条写关键选择器全部取证），
        于是本属性也为真，并且 11 个阶段**全部已实现**、其中 10 个实机跑通。

        即便如此，本属性**仍然不等于「现在能发布」**：
        ``submit`` 尚未实机执行，且写操作还要过两把锁。两者混起来会报出
        「路线可用，其实还不能安全跑完」这种假信号。

        要判断「现在能不能一键发布」，看 :attr:`publishable`。
        """

        return self.protocol_write_ready or self.dom_write_ready

    @property
    def publishable(self) -> bool:
        """**现在**能不能真的跑完一整条发布路线。

        三个条件缺一不可：

        1. 存在可用路线（``publish_route_ready``）；
        2. **所有阶段都已实现**——否则流水线一定会在缺的那一步失败；
        3. 契约无自检问题。

        ``upload_images`` / ``fill_skus`` 未实现的这段时期，本属性为假，
        而 ``publish_route_ready`` 为真。**面向用户的结论必须用这个。**
        """

        return bool(
            self.publish_route_ready
            and not self.unimplemented_stages
            and not self.incomplete_stages
            and not self.contract_problems
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "contract_problems": list(self.contract_problems),
            "protocol_write_ready": self.protocol_write_ready,
            "dom_write_ready": self.dom_write_ready,
            "publish_route_ready": self.publish_route_ready,
            # 「路线存在」与「现在能发布」分开报。前者只看证据面，
            # 后者还要求所有阶段都已实现——见 `publishable` 的 docstring。
            "publishable": self.publishable,
            "implemented_stages": list(self.implemented_stages),
            "unimplemented_stages": list(self.unimplemented_stages),
            # 「已注册」与「能走完」分开报：目前两者一致，但字段保留——
            # 一旦再有 complete=False 的处理器，这里能立刻看出来。
            "incomplete_stages": list(self.incomplete_stages),
            # 「写完了」与「在真实页面上跑通过」也要分开报。
            "live_unverified_stages": list(self.live_unverified_stages),
            "blocked_required_fields": list(self.blocked_required_fields),
            "blocked_write_critical_selectors": list(self.blocked_write_critical_selectors),
            "field_evidence": dict(self.field_evidence),
        }


def describe_readiness(contracts: Optional[Contracts] = None) -> Readiness:
    """汇总「现在到底能不能真发布」。CLI 与 API 都调它。"""

    from .stages import STAGE_HANDLERS

    data = contracts if contracts is not None else load_contracts()
    route = write_route_status(data)
    implemented = [stage for stage in STAGE_ORDER if stage in STAGE_HANDLERS]
    # 「已注册」不等于「能走完」。``complete=False`` 的处理器**永远返回阻塞项**
    # （目前是 upload_images：上传已实证、选图入位尚未实证）。
    incomplete = [
        stage for stage in STAGE_ORDER
        if stage in STAGE_HANDLERS and not STAGE_HANDLERS[stage].complete
    ]
    return Readiness(
        contract_problems=validate_contracts(data),
        protocol_write_ready=bool(route["protocol_write_ready"]),
        dom_write_ready=bool(route["dom_write_ready"]),
        implemented_stages=implemented,
        unimplemented_stages=[stage for stage in STAGE_ORDER if stage not in STAGE_HANDLERS],
        incomplete_stages=incomplete,
        live_unverified_stages=[
            stage for stage in STAGE_ORDER if stage not in LIVE_VERIFIED_STAGES
        ],
        blocked_required_fields=list(route["blocked_required_fields"]),
        blocked_write_critical_selectors=list(route["blocked_write_critical_selectors"]),
        field_evidence=dict(route["field_evidence"]),
    )


def submit_succeeded(runs: Sequence[StageRun]) -> bool:
    """``submit`` 阶段是否**真的执行成功过**。

    判据是 ``status == STEP_OK``，不是 ``outcome.ok``——``StageOutcome.skipped()``
    的 ``ok`` 也是 ``True``，只看 ``ok`` 会把「按策略跳过提交」误判成「提交发生过」，
    于是 ``success=True`` 而 ``stopped_before_submit=False``
    （对抗性审查 2026-10-02，F9）。

    抽成模块级纯函数是为了能直接被测试覆盖——它是 ``stopped_before_submit`` 的唯一依据，
    而这个字段会被用户与前端用来判断「到底提交了没有」。
    """

    return any(run.name == STAGE_SUBMIT and run.outcome.status == STEP_OK for run in runs)


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def _preflight_warnings_for_report(ctx: "PipelineContext", static: Any) -> Any:
    """报告用的告警列表：**优先 precheck 阶段的完整结果**。

    `pipeline.run` 里有两份预检：

    * ``static`` —— 连浏览器之前的本地预检（步骤 1）；
    * ``ctx.scratch["preflight"]`` —— `precheck` 阶段带页面快照的完整预检。

    聚合输出原先用前者，而步骤 summary 用后者，于是**同一个概念两个数字**
    （实测：precheck 说「告警 2」，聚合 `preflight_warnings` 是 `[]`）。
    这里统一取完整的那份；阶段没跑到时退回静态预检。
    """

    stage_result = ctx.scratch.get("preflight")
    if stage_result is None:
        return list(getattr(static, "warnings", []) or [])
    return list(getattr(stage_result, "warnings", []) or [])


def run(
    local: LocalProduct,
    request: Mapping[str, Any],
    *,
    progress_callback: Optional[ProgressCallback] = None,
    dry_run: bool = True,
    stop_before_submit: bool = True,
    authorization: Optional[WriteAuthorization] = None,
    contracts: Optional[Contracts] = None,
    cdp_list_url: str = TAOBAO_CDP_LIST_URL,
    outputs_dir: Optional[str] = None,
    write_artifact: bool = False,
    session_probe: Optional[Any] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
    prepared_media: Optional[PreparedProductMedia] = None,
    media_preparer: Optional[Callable[..., PreparedProductMedia]] = None,
    account_profile: str = '',
    start_from: str = '',
    skip_stages: Optional[Sequence[str]] = None,
    listing_mode: str = '',
    save_draft: bool = False,
) -> PipelineResult:
    """执行一次淘宝发布。

    :param dry_run: 默认 ``True``。dry-run 下写阶段全部跳过，只验证数据与前置条件。
    :param stop_before_submit: 默认 ``True``，在提交阶段前截停。
    :param authorization: 缺省从环境变量读，即默认零写入。
    :param write_artifact: 是否把本次运行的脱敏报告落盘到 ``outputs/``。
    :param session_probe: 会话探测器注入点（见
        :attr:`taobao_publish.stages.PipelineContext.session_probe`）。生产环境不要传。
    :param should_cancel: 取消钩子，返回 True 表示叫停。**只在阶段边界生效**——
        阶段内部不会被打断，半途中断会留下说不清的状态。
    :param start_from: 从 ``STAGE_ORDER`` 里的某个阶段开始跑（跳过它之前的）。
        用于「已经走到填写页、接着把剩下的填完」；非法值直接报错，**不静默从头跑**。
    :param skip_stages: 明确要**跳过的阶段**（例如单独验证详情图时跳过 SKU 阶段）。
    :param listing_mode: 上架方式（`立刻上架 / 定时上架 / 放入仓库`）。留空则用
        `stages.DEFAULT_LISTING_MODE`（**放入仓库**）——危险的那个绝不能是默认值。
    :param save_draft: 是否在回读通过后**保存草稿**。**默认 False**——
        保存会在平台上多出一条草稿记录，属于写入，必须由调用方显式请求。
        为什么不用 ``start_from`` 代替：``start_from`` 只能砍掉前缀，而 SKU 之后的
        阶段仍要跑。非法阶段名直接报错，**不会静默忽略**——否则调用方以为跳过了，
        实际却写了一次平台。
    """

    # 入参做一次布尔归一：``dry_run=None`` / ``0`` / ``""`` 都按「不是 dry-run」处理。
    # 这个方向是保守的——非 dry-run 反而要过授权门，所以不会有「以为在彩排、
    # 其实在真跑」的风险；但仍然显式归一，避免把 ``None`` 混进下游判断。
    dry_run = bool(dry_run)
    stop_before_submit = bool(stop_before_submit)

    # 请求体里的 options **只能收紧，不能放宽**。
    # 传 True 可以把调用方的非 dry-run 强制拉回 dry-run；传 False 不产生任何效果。
    # 放宽必须由调用方在**代码里**显式决定——否则任何能构造请求体的地方
    # 都能把彩排变成真实发布。
    options = request.get("options") or {}
    if isinstance(options, Mapping):
        if options.get("dry_run") is True:
            dry_run = True
        if options.get("stop_before_submit") is True:
            stop_before_submit = True

    auth = authorization if authorization is not None else WriteAuthorization.from_environment()
    # 类型校验：鸭子类型对象（``require()`` 空实现、``is_granted()`` 恒 True）能架空整个
    # 授权门。审查实测过这种对象能让 9 个阶段全量执行（2026-10-02，F10）。
    # 唯一的生产路径是 ``from_environment``，加这条断言成本极低。
    if not isinstance(auth, WriteAuthorization):
        raise TaobaoPublishError(
            "CONTRACT_INVALID",
            f"authorization 必须是 WriteAuthorization，实际是 {type(auth).__name__}；"
            "生产环境请用 WriteAuthorization.from_environment()",
        )
    data = contracts if contracts is not None else load_contracts()
    readiness = describe_readiness(data)

    steps: List[StepRecord] = []
    runs: List[StageRun] = []
    ctx = None

    def submitted() -> bool:
        """``submit`` 阶段是否真的执行成功过。见 :func:`submit_succeeded`。"""

        return submit_succeeded(runs)

    def finish(result: PipelineResult) -> PipelineResult:
        if ctx is not None and ctx.scratch.get('media_observations'):
            result.data['media_observations'] = list(ctx.scratch['media_observations'])
        result.blockers = [item.to_dict() for item in collect_stage_blockers(runs)] or result.blockers
        result.stopped_before_submit = not submitted()
        from .verification import summarize_form_verification
        result.data['form_verification'] = summarize_form_verification(
            runs, success=result.success, dry_run=result.dry_run,
            stopped_before_submit=result.stopped_before_submit)
        result.data.setdefault("readiness", readiness.to_dict())
        result.data.setdefault("authorization", auth.to_dict())
        result.data.setdefault("generated_at", _now_iso())
        precheck = next((run for run in runs if run.name == "precheck"), None)
        if precheck is not None:
            result.data['deferred_adapter_blockers'] = precheck.outcome.data.get('deferred_adapter_blockers', {})
        if write_artifact:
            _write_artifact(result, outputs_dir)
        return result

    # --- 步骤 0：构建发布意图 -------------------------------------------
    build = build_publish_item(local, request, contracts=data)
    if build.item is None:
        return finish(
            PipelineResult(
                success=False,
                stage="build",
                error={"code": "CONTRACT_INVALID", "message": "无法构建发布意图"},
                blockers=[item.to_dict() for item in build.blockers],
                dry_run=dry_run,
            )
        )
    item: PublishItem = build.item
    build_blockers = build.blockers
    if prepared_media is not None:
        try:
            if not isinstance(prepared_media, PreparedProductMedia):
                raise ValueError('素材准备回执格式不正确')
            prepared_media.selection_plan(item, account_profile)
        except (ValueError, OSError) as exc:
            return finish(PipelineResult(success=False, stage='prepared_media',
                error={'code': 'PREFLIGHT_BLOCKED', 'message': str(exc)}, dry_run=dry_run))

    # --- 步骤 1：静态预检（在连接浏览器之前）-----------------------------
    static = run_static_preflight(
        item,
        contracts=data,
        require_write=not dry_run,
        check_images=True,
    )
    if build_blockers:
        merged = dedupe_blockers(list(static.blockers) + build_blockers)
        static_blockers, static_warnings = split_by_severity(merged)
    else:
        static_blockers, static_warnings = static.blockers, static.warnings

    if static_blockers:
        return finish(
            PipelineResult(
                success=False,
                stage="static_preflight",
                error={
                    "code": "PREFLIGHT_BLOCKED",
                    "message": f"静态预检未通过：{len(static_blockers)} 条阻塞项",
                },
                blockers=[item.to_dict() for item in static_blockers],
                dry_run=dry_run,
            )
        )

    # --- 步骤 2：按阶段执行 ----------------------------------------------
    stages = build_stage_plan(include_submit=not stop_before_submit)
    if start_from:
        # 「从某个阶段接着跑」——页面**不会**被回退，只用来跳过已经做完的部分。
        #
        # 为什么需要：类目页选完会**导航到填写页**，而 `select_category` 是从
        # 类目页开始的动作。已经走到填写页之后再跑整条流水线，它会把页面
        # 导航回类目页（实测这一步会 `Page.navigate` 超时），
        # 于是「继续把剩下的填完」变成「重新来一遍还可能卡住」。
        #
        # 只允许从 ``STAGE_ORDER`` 里真实存在的阶段开始，且**必须至少留下一个阶段**
        # ——传一个非法值不会静默变成「从头跑」。
        if start_from not in STAGE_ORDER:
            raise TaobaoPublishError(
                "CONTRACT_INVALID",
                f"start_from 不是已知阶段：{start_from!r}（可用：{'、'.join(STAGE_ORDER)}）",
            )
        index_of = list(STAGE_ORDER).index(start_from)
        stages = [stage for stage in stages if list(STAGE_ORDER).index(stage) >= index_of]
        if not stages:
            raise TaobaoPublishError(
                "CONTRACT_INVALID",
                f"从 {start_from} 开始没有任何阶段可跑（它被 stop_before_submit 截掉了吗？）",
            )
    if skip_stages:
        wanted = [str(stage).strip() for stage in skip_stages if str(stage).strip()]
        unknown = [stage for stage in wanted if stage not in STAGE_ORDER]
        if unknown:
            raise TaobaoPublishError(
                "CONTRACT_INVALID",
                f"skip_stages 里有未知阶段：{'、'.join(unknown)}（可用：{'、'.join(STAGE_ORDER)}）",
            )
        stages = [stage for stage in stages if stage not in wanted]
        if not stages:
            raise TaobaoPublishError(
                "CONTRACT_INVALID", "skip_stages 把所有阶段都跳过了，没有可执行的阶段",
            )
    if (media_preparer is not None and not dry_run and prepared_media is None
            and start_from and start_from != STAGE_ORDER[0]):
        raise TaobaoPublishError('CONTRACT_INVALID',
            '继续填写时需要传入已完成的素材回执，不能重新导入并导航回发布入口')

    # 桌面整目录路线先完成图片空间导入，之后才连接发布页。
    if media_preparer is not None and not dry_run and prepared_media is None:
        import time
        from .constants import WRITE_UPLOAD_IMAGE
        preparing = StepRecord(name='prepare_media', status=STEP_RUNNING)
        steps.append(preparing)
        started = time.monotonic()
        def report_preparation(message):
            preparing.summary = str(message)
            if progress_callback is not None:
                progress_callback(15, str(message), 'prepare_media', [step.to_dict() for step in steps])
        try:
            auth.require(WRITE_UPLOAD_IMAGE)
            if should_cancel is not None and should_cancel():
                raise TaobaoPublishError('CANCELLED', '已取消，尚未上传或进入发布页')
            report_preparation('先将商品文件夹导入图片空间')
            prepared_media = media_preparer(local, item, auth, report_preparation, should_cancel)
            if not isinstance(prepared_media, PreparedProductMedia):
                raise ValueError('整目录上传端未返回完整素材回执')
            prepared_media.selection_plan(item, account_profile)
            preparing.status = STEP_OK
            preparing.summary = '整目录素材已确认，开始进入发布页'
            preparing.elapsed_ms = int((time.monotonic() - started) * 1000)
            if progress_callback is not None:
                progress_callback(30, preparing.summary, 'prepare_media', [step.to_dict() for step in steps])
        except Exception as exc:
            code = getattr(exc, 'code', 'IMAGE_UPLOAD_FAILED')
            preparing.status = STEP_CANCELLED if code == 'CANCELLED' else 'failed'
            preparing.error_code, preparing.summary = code, str(exc)
            preparing.elapsed_ms = int((time.monotonic() - started) * 1000)
            return finish(PipelineResult(success=False, stage='prepare_media', steps=steps,
                error={'code': code, 'message': str(exc)}, dry_run=False))
        original_progress = progress_callback
        if original_progress is not None:
            def progress_after_preparation(pct, message, step_name, records):
                original_progress(30 + int(pct * 0.7), message, step_name, records)
            progress_callback = progress_after_preparation

    ctx = PipelineContext(
        item=item,
        authorization=auth,
        contracts=data,
        dry_run=dry_run,
        cdp_list_url=cdp_list_url,
        progress=progress_callback,
        artifacts_dir=outputs_dir or DEFAULT_OUTPUTS_DIR,
        session_probe=session_probe,
        should_cancel=should_cancel,
        prepared_media=prepared_media,
        account_profile=account_profile,
    )
    ctx.scratch["static_preflight"] = static
    ctx.scratch["static_warnings"] = static_warnings
    # 本次真正会执行的阶段计划。precheck 用它推导「需要哪些写授权」——
    # 提交前截停的运行不该被要求 submit_publish 授权，否则写模式的预检永远过不了。
    ctx.scratch["stage_plan"] = list(stages)
    ctx.scratch["dry_run"] = dry_run
    # 上架方式：留空则由 `stage_set_listing` 取自己的默认值（放入仓库）。
    if listing_mode:
        ctx.scratch["listing_mode"] = listing_mode
    # 保存草稿：**显式请求才做**（处理器里判 `save_draft_requested`，未请求则 skipped）。
    ctx.scratch["save_draft_requested"] = bool(save_draft)

    total = len(stages)
    for index, stage in enumerate(stages):
        record = StepRecord(name=stage, status=STEP_RUNNING)
        steps.append(record)
        emit_progress(ctx, index, total, steps, stage, STEP_RUNNING, "")

        stage_run = run_stage(stage, ctx, index=index, total=total, steps=steps)
        runs.append(stage_run)

        record.status = stage_run.outcome.status
        record.elapsed_ms = stage_run.elapsed_ms
        record.summary = stage_run.outcome.summary
        record.error_code = stage_run.outcome.error_code
        # 把阶段自己的诊断明细带进产物（`StepRecord.to_dict` 只在非空时输出）。
        record.data = dict(stage_run.outcome.data or {})
        emit_progress(ctx, index, total, steps, stage, record.status, record.summary)

        # 收到取消：把**剩下的阶段**也标成 cancelled 再返回。
        #
        # 不标的话它们会从 steps 里消失，前端看到的是「阶段列表突然变短」——
        # 用户没法区分「已经跑完了」和「还没跑」。显式标出来，列表长度始终是 11。
        if stage_run.outcome.status == STEP_CANCELLED:
            for pending in stages[index + 1:]:
                steps.append(StepRecord(
                    name=pending, status=STEP_CANCELLED, summary="已请求取消，本阶段未执行"))
            return finish(
                PipelineResult(
                    success=False,
                    stage=stage,
                    error={
                        "code": "CANCELLED",
                        "message": "已请求取消，流水线在阶段边界停止",
                        "stage_label": stage_label(stage),
                    },
                    steps=steps,
                    dry_run=dry_run,
                )
            )

        if not stage_run.outcome.ok:
            error_code = stage_run.outcome.error_code or "PLATFORM_ERROR"
            return finish(
                PipelineResult(
                    success=False,
                    stage=stage,
                    error={
                        "code": error_code,
                        "message": stage_run.outcome.summary,
                        "stage_label": stage_label(stage),
                    },
                    steps=steps,
                    dry_run=dry_run,
                )
            )

    # --- 步骤 3：组装平台载荷（不发送）-----------------------------------
    payload, payload_blockers = build_platform_payload(item, data)
    payload_gate_blockers = [item for item in payload_blockers if item.is_blocking]

    result_data: Dict[str, Any] = {
        "item_summary": item.summary(),
        "step_plan": stages,
        "payload_field_count": len(payload),
        # ⚠️ **别用 `static.warnings`。**
        #
        # 这里曾经是 `static.warnings`——那是**连浏览器之前**的本地预检，
        # 而 `precheck` **阶段**跑的是带页面快照的完整预检
        # （存在 `ctx.scratch["preflight"]`）。两者数字不同，实测：
        #
        #     precheck 步骤 summary : 「阻塞 0，告警 2」
        #     聚合 preflight_warnings : []
        #
        # **同一个概念，两个数字**——读聚合字段的人会以为没有告警。
        # 现在优先用阶段的结果；阶段没跑到（例如静态预检就失败）才退回静态预检。
        "preflight_warnings": [
            warning.to_dict() for warning in _preflight_warnings_for_report(ctx, static)
        ],
        "preflight_warnings_source": (
            "precheck_stage" if isinstance(ctx.scratch.get("preflight"), object)
            and ctx.scratch.get("preflight") is not None else "static_preflight"
        ),
        # 「执行过」与「跳过」按**状态**判定，不按 skipped_for_dry_run——后者只覆盖
        # dry-run 这一种跳过原因，未来任何非 dry-run 的跳过都会被错分类（F9）。
        "stages_executed": [run.name for run in runs if run.outcome.status == STEP_OK],
        "stages_skipped": [run.name for run in runs if run.outcome.status == STEP_SKIPPED],
    }
    if write_artifact:
        result_data["artifact_written"] = True

    # ⚠️ **成功时不要挂 blockers**：下面这些是 **mtop 协议路线**的字段映射缺口，
    # 而本次走的是 **DOM 路线**，完全不依赖它们。实测踩过：一次
    # success: True 的运行底下挂着 10 条「阻塞项」，读起来像自相矛盾，
    # 也让人以为还有什么没做完。
    #
    # 它们是**另一条路线的待办**，归到 data 里如实说明，不冒充本次的阻塞。
    result_data["protocol_route_gaps"] = [item.to_dict() for item in payload_gate_blockers]
    if payload_gate_blockers:
        result_data["protocol_route_note"] = (
            "以上 {} 条是 mtop 协议路线的字段映射缺口；本次走 DOM 路线，不依赖它们。"
            "要用协议路线才需要补齐。".format(len(payload_gate_blockers))
        )

    return finish(
        PipelineResult(
            success=True,
            stage="done",
            steps=steps,
            dry_run=dry_run,
            data=result_data,
            blockers=[],
        )
    )


def _write_artifact(result: PipelineResult, outputs_dir: Optional[str]) -> None:
    """把脱敏后的运行报告落盘到 ``outputs/``。

    产物名沿用研究区规范：ASCII + ``tb_<用途>_<时间戳>.json``。
    """

    from .contracts import SUBPROJECT_ROOT
    from .sanitize import assert_clean

    base = Path(outputs_dir) if outputs_dir else (SUBPROJECT_ROOT / DEFAULT_OUTPUTS_DIR)
    base.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = base / f"tb_publish_report_{stamp}.json"
    text = json.dumps(result.to_dict(), ensure_ascii=False, indent=2)
    assert_clean(text, context=str(path))
    path.write_text(text, encoding="utf-8")
    result.data["artifact_path"] = str(path)


# ---------------------------------------------------------------------------
# 便捷入口
# ---------------------------------------------------------------------------
def run_from_record(
    row: Mapping[str, Any],
    request: Optional[Mapping[str, Any]] = None,
    *,
    product_dir: str = "",
    **kwargs: Any,
) -> PipelineResult:
    """从一行 ``record`` 数据直接跑流水线。便于 CLI 与测试。"""

    from .local_source import local_product_from_record

    local = local_product_from_record(row, product_dir=product_dir or str(row.get("path") or ""))
    merged: Dict[str, Any] = dict(request or {})
    merged.setdefault("record_id", local.record_id)
    merged.setdefault("record_name", local.record_name)
    return run(local, merged, **kwargs)

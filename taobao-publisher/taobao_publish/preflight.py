# -*- coding: utf-8 -*-
"""发布前置检查。

**顺序很重要**：静态检查必须跑在连接浏览器之前（抖店 v4 就是这么做的，
见 ``fxg_protocol_v4.py:1577-1591``）。理由很实际——数据本身有问题时，
连上浏览器只会浪费一次登录态暴露和一轮页面加载，还会让报错变得难查。

本模块只做**判定**，不做任何修复，也不触发任何平台交互。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .authorization import WriteAuthorization
from .constants import (
    LOGIN_URL_MARKERS,
    PUBLISH_ALLOWED_HOST_SUFFIXES,
    RISK_CONTROL_URL_MARKERS,
    WRITE_OPERATIONS,
)
from .contracts import Contracts, load_contracts
from .errors import (
    SEVERITY_BLOCKER,
    SEVERITY_WARNING,
    Blocker,
    dedupe_blockers,
    split_by_severity,
)
from .mapping import (
    INTENT_ALL,
    collect_unmapped_fields,
    validate_images,
    validate_skus,
    validate_title,
)
from .text_rules import count_title_units
from .models import PublishItem


#: 如果 URL 里出现这些标记，说明当前页面不是发布页而是别的流程页。
@dataclass
class PageSnapshot:
    """页面状态快照。

    只放**判定所需的最小事实**。``body_text`` 由调用方截断后传入，禁止整页回传
    （页面里可能含订单号、手机号等）。

    ``has_workbench_root`` 与 ``has_blocking_overlay`` 是**三态**：

    * ``True`` —— 已在页面内确认存在。
    * ``False`` —— 已在页面内确认**不**存在（真阻塞）。
    * ``None`` —— **尚未评估**（例如只做了 URL 级探测）。这不是「没有」，
      而是「不知道」，因此不能当成通过，也不能当成失败：只读预检下出告警，
      真实写入前升级为阻塞。
    """

    url: str
    title: str = ""
    body_text: str = ""
    has_workbench_root: Optional[bool] = None
    #: 是否停在**类目搜索页**。流水线本来就从这里开始（`select_category`
    #: 要在这里搜索并导航到填写页），所以「工作台根节点不存在」在这一步是
    #: **预期状态**，不该判成 WRONG_PAGE。实测踩过：顺序改成「先选类目」之后，
    #: 预检拿「工作台=无」把整条流水线拦在了门口。
    has_category_page: Optional[bool] = None
    has_blocking_overlay: Optional[bool] = None
    has_submit_control: Optional[bool] = None
    has_save_draft_control: Optional[bool] = None
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "url": self.url,
            "title": self.title,
            "has_workbench_root": self.has_workbench_root,
            "has_blocking_overlay": self.has_blocking_overlay,
            "has_submit_control": self.has_submit_control,
            "has_save_draft_control": self.has_save_draft_control,
            "notes": list(self.notes),
        }


def host_of(url: str) -> str:
    """提取 host，不引入 urllib 的完整解析（对畸形 URL 更宽容地暴露问题）。"""

    value = str(url or "").strip()
    if "//" in value:
        value = value.split("//", 1)[1]
    return value.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0].lower()


def is_allowed_host(url: str) -> bool:
    """判断 host 是否属于淘宝/天猫。

    **必须同时接受「裸域」与「子域」两种形态，且不能被子串骗过**：

    * ``taobao.com``           → 通过（裸域）
    * ``item.taobao.com``      → 通过（子域）
    * ``notataobao.com``       → **拒绝**（不是 ``.taobao.com`` 的子域，只是以
      ``taobao.com`` 结尾的另一个域名）
    * ``taobao.com.evil.test`` → 拒绝

    用 ``host.endswith("taobao.com")`` 会放过第二个例子，所以这里显式拼 ``"."`` 前缀。
    """

    host = host_of(url).split(":", 1)[0]
    if not host:
        return False
    for suffix in PUBLISH_ALLOWED_HOST_SUFFIXES:
        base = suffix.lstrip(".")
        if not base:
            continue
        if host == base or host.endswith("." + base):
            return True
    return False


def check_page_snapshot(
    snapshot: Optional[PageSnapshot],
    *,
    require_write: bool = False,
) -> List[Blocker]:
    """页面级检查：域名、登录态、风控页、遮挡弹层。

    ``snapshot`` 为 ``None`` 表示尚未连接页面（纯静态阶段），此时不产出页面类阻塞项。
    """

    if snapshot is None:
        return []

    blockers: List[Blocker] = []
    url = str(snapshot.url or "")
    lower = url.lower()

    if not url:
        blockers.append(
            Blocker(
                code="WRONG_PAGE",
                field="page.url",
                detail="页面 URL 为空，无法确认当前所处页面",
                source="preflight.check_page_snapshot",
            )
        )
        return blockers

    # 风控优先于登录判断：风控页上做任何判断都没有意义，且必须立刻停手。
    for marker in RISK_CONTROL_URL_MARKERS:
        if marker in lower:
            blockers.append(
                Blocker(
                    code="RISK_CONTROL_HIT",
                    field="page.url",
                    detail=f"URL 命中风控标记 {marker!r}；停止自动化，交由人工处理",
                    source="preflight.check_page_snapshot",
                )
            )
            return blockers

    for marker in LOGIN_URL_MARKERS:
        if marker in lower:
            blockers.append(
                Blocker(
                    code="LOGIN_REQUIRED",
                    field="page.url",
                    detail=f"URL 命中登录页标记 {marker!r}",
                    source="preflight.check_page_snapshot",
                )
            )
            return blockers

    if not is_allowed_host(url):
        blockers.append(
            Blocker(
                code="WRONG_PAGE",
                field="page.url",
                detail=f"host {host_of(url)!r} 不在淘宝/天猫域名白名单内",
                source="preflight.check_page_snapshot",
            )
        )

    if snapshot.has_blocking_overlay is True:
        blockers.append(
            Blocker(
                code="WRONG_PAGE",
                field="page.overlay",
                detail="页面存在遮挡表单的弹层；需人工处理后重试，不做自动关闭",
                source="preflight.check_page_snapshot",
            )
        )
    elif snapshot.has_blocking_overlay is None:
        blocker = Blocker(
            code="WRONG_PAGE",
            field="page.overlay",
            detail="尚未评估页面是否存在遮挡弹层（需要 Node 探针做 DOM 评估）",
            severity=SEVERITY_BLOCKER if require_write else SEVERITY_WARNING,
            source="preflight.check_page_snapshot",
        )
        blockers.append(blocker)

    return blockers


def check_workbench_ready(
    snapshot: Optional[PageSnapshot],
    *,
    require_write: bool = False,
) -> List[Blocker]:
    """确认发布工作台真的渲染出来了。

    抖店侧踩过「页面看似正常、实际表单没加载」的坑，这里用显式事实判定，
    而不是靠等待时长。

    三态语义见 :class:`PageSnapshot`：``None``（未评估）在只读预检下是告警，
    真实写入前升级为阻塞——**不能因为「还没测」就当「没问题」**。
    """

    if snapshot is None:
        return []

    if snapshot.has_workbench_root is True:
        return []

    # **停在类目搜索页是合法的起点**：流水线的第一步 `select_category`
    # 就是从这里搜索并导航到填写页。把这一状态判成 WRONG_PAGE 会把整条流水线
    # 拦在门口（实测踩过）。
    if snapshot.has_category_page is True:
        return []

    if snapshot.has_workbench_root is False:
        return [
            Blocker(
                code="WRONG_PAGE",
                field="page.workbench",
                detail="既不在发布工作台、也不在类目搜索页；不要基于未渲染的页面继续操作",
                source="preflight.check_workbench_ready",
            )
        ]

    return [
        Blocker(
            code="WRONG_PAGE",
            field="page.workbench",
            detail="尚未确认发布工作台根节点是否存在（需要 Node 探针做 DOM 评估）",
            severity=SEVERITY_BLOCKER if require_write else SEVERITY_WARNING,
            source="preflight.check_workbench_ready",
        )
    ]


def check_authorization(
    authorization: WriteAuthorization,
    required_operations: Sequence[str] = WRITE_OPERATIONS,
) -> Tuple[List[Blocker], List[Blocker]]:
    """检查写权限。

    :param required_operations: **本次运行真的会执行**的写操作。
        缺省是全部——但那对「提交前截停」的运行来说是过严的：明明不会提交，
        却要求 ``submit_publish`` 授权，于是 `require_write=True` 下永远过不了预检。
        调用方应当传入由**阶段计划**推导出的操作集合（见
        :func:`taobao_publish.pipeline.run` 里的 ``ctx.scratch["stage_plan"]``）。

    :return: ``(blockers, warnings)``。

    未授权**不是**阻塞项——只读预检是合法且推荐的用法。它只在调用方声明
    「本次要写」时（``run_preflight(require_write=True)``）才转成阻塞。
    这里只产出 warning，把「要不要因此停下」的决定权留给调用方。
    """

    warnings: List[Blocker] = []
    for operation in required_operations:
        if authorization.is_granted(operation):
            continue
        warnings.append(
            Blocker(
                code="WRITE_NOT_AUTHORIZED" if operation != "submit_publish" else "SUBMIT_NOT_AUTHORIZED",
                field=f"authorization.{operation}",
                detail=authorization.missing_reason(operation),
                severity=SEVERITY_WARNING,
                source="preflight.check_authorization",
            )
        )
    return [], warnings


# ---------------------------------------------------------------------------
# 汇总
# ---------------------------------------------------------------------------
@dataclass
class PreflightResult:
    """预检结果。``ready`` 只由 blockers 决定，warnings 不影响。"""

    ready: bool = False
    blockers: List[Blocker] = field(default_factory=list)
    warnings: List[Blocker] = field(default_factory=list)
    checks: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ready": self.ready,
            "blockers": [item.to_dict() for item in self.blockers],
            "warnings": [item.to_dict() for item in self.warnings],
            "checks": dict(self.checks),
        }

    def render_lines(self) -> List[str]:
        lines = [f"{'通过' if self.ready else '未通过'}：发布前置检查"]
        for item in self.blockers:
            lines.append(f"  [阻塞] {item.render()}")
        for item in self.warnings:
            lines.append(f"  [告警] {item.render()}")
        if not self.blockers and not self.warnings:
            lines.append("  （无阻塞项）")
        return lines


def run_static_preflight(
    item: PublishItem,
    *,
    contracts: Optional[Contracts] = None,
    include_unmapped_contract_fields: bool = True,
    check_images: bool = True,
    require_write: bool = False,
) -> PreflightResult:
    """不依赖页面的静态检查。**必须在连接浏览器之前跑。**

    :param require_write: 决定证据缺口是阻塞项还是告警。见
        :func:`taobao_publish.mapping.collect_unmapped_fields` 的说明。
    """

    data = contracts if contracts is not None else load_contracts()
    collected: List[Blocker] = []
    collected.extend(validate_title(item, data))
    collected.extend(validate_skus(item, data))
    if check_images:
        collected.extend(validate_images(item, data))
    if include_unmapped_contract_fields:
        collected.extend(
            collect_unmapped_fields(
                data,
                INTENT_ALL,
                severity=SEVERITY_BLOCKER if require_write else SEVERITY_WARNING,
            )
        )

    unique = dedupe_blockers(collected)
    blockers, warnings = split_by_severity(unique)
    return PreflightResult(
        ready=not blockers,
        blockers=blockers,
        warnings=warnings,
        checks={
            "stage": "static",
            "require_write": bool(require_write),
            "title_length": count_title_units((item.title or "").strip()),
            "sku_count": len(item.skus),
            "main_image_count": len(item.images.main),
            "unmapped_contract_fields": len(collect_unmapped_fields(data, INTENT_ALL)),
        },
    )


def run_preflight(
    item: PublishItem,
    *,
    snapshot: Optional[PageSnapshot] = None,
    authorization: Optional[WriteAuthorization] = None,
    contracts: Optional[Contracts] = None,
    require_write: bool = False,
    include_unmapped_contract_fields: bool = True,
    check_images: bool = True,
    required_operations: Optional[Sequence[str]] = None,
) -> PreflightResult:
    """完整预检。

    :param snapshot: 页面快照；``None`` 表示当前只做静态检查。
    :param require_write: 本次是否要真的写平台。为 ``True`` 时，任何未授权的
        写操作都会升级为阻塞项。
    :param required_operations: 本次运行真的会执行的写操作。
        ``None`` 表示按**全部**写操作检查（保守，用于独立的只读预检）。
        流水线会传入由阶段计划推导出的集合——**提交前截停的运行不该被要求
        提交授权**，否则写模式的预检永远过不了。
    """

    data = contracts if contracts is not None else load_contracts()
    collected: List[Blocker] = []

    # 1) 页面事实（若已连接）
    collected.extend(check_page_snapshot(snapshot, require_write=require_write))
    collected.extend(check_workbench_ready(snapshot, require_write=require_write))

    # 2) 静态数据
    collected.extend(validate_title(item, data))
    collected.extend(validate_skus(item, data))
    if check_images:
        collected.extend(validate_images(item, data))

    # 3) 契约证据门
    if include_unmapped_contract_fields:
        collected.extend(
            collect_unmapped_fields(
                data,
                INTENT_ALL,
                severity=SEVERITY_BLOCKER if require_write else SEVERITY_WARNING,
            )
        )

    # 4) 授权
    authorization = authorization if authorization is not None else WriteAuthorization.none()
    auth_blockers, auth_warnings = check_authorization(
        authorization,
        required_operations=(
            tuple(required_operations) if required_operations is not None else WRITE_OPERATIONS
        ),
    )
    if require_write:
        # 要写却没授权 → 升级为阻塞项（保留原因文案）。
        for warning in auth_blockers + auth_warnings:
            collected.append(
                Blocker(
                    code=warning.code,
                    field=warning.field,
                    detail=warning.detail,
                    source="preflight.run_preflight(require_write=True)",
                )
            )
    else:
        collected.extend(auth_warnings)

    unique = dedupe_blockers(collected)
    blockers, warnings = split_by_severity(unique)

    return PreflightResult(
        ready=not blockers,
        blockers=blockers,
        warnings=warnings,
        checks={
            "stage": "full",
            "require_write": bool(require_write),
            "read_only": authorization.is_read_only,
            "authorization": authorization.to_dict(),
            "page_checked": snapshot is not None,
            "title_length": count_title_units((item.title or "").strip()),
            "sku_count": len(item.skus),
            "main_image_count": len(item.images.main),
        },
    )

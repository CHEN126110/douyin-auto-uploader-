# -*- coding: utf-8 -*-
"""淘宝发布的数据契约。

分三层，边界刻意画死：

1. :class:`LocalProduct` —— **本地既有资产**的只读投影（来自 SQLite ``record`` 表与
   采集目录）。这一层不允许出现任何平台字段名。
2. :class:`PublishItem` —— **平台无关的发布意图**。由 :mod:`taobao_publish.mapping`
   从 :class:`LocalProduct` 映射而来，仍然不含淘宝字段名。
3. 淘宝载荷 —— 由 ``mapping.build_platform_payload`` 产出，字段名来自
   ``contracts/field_mapping.json``（当前全部 ``unknown``，见 blockers）。

这样分层的原因：淘宝写接口的字段名目前**一条都没实证**。把平台字段名写在
dataclass 里会诱导后人把它们当成事实，所以平台字段名只允许出现在契约 JSON 里。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .text_rules import count_title_units
from .constants import (
    EVIDENCE_UNKNOWN,
    STAGE_LABELS,
    STAGE_ORDER,
    STAGE_WRITE_OPERATION,
)


# ---------------------------------------------------------------------------
# 第 1 层：本地资产投影
# ---------------------------------------------------------------------------
@dataclass(slots=True)
class LocalSku:
    """本地 ``record.content`` 里的一条 SKU 条目。

    真实结构（已在 ``sqlite.db`` 实测）：``{dir_name, file_name, name, path, price}``。
    """

    name: str
    path: str
    price: Optional[float] = None
    dir_name: str = ""
    file_name: str = ""


@dataclass(slots=True)
class LocalProduct:
    """本地一件待发布商品。字段名与 ``src/orm.py`` 的 ``Record`` 一致。"""

    record_id: int
    record_name: str
    title: str = ""
    clazz: Optional[int] = None
    remark: Optional[str] = None
    shipping_template: str = ""
    source_url: str = ""
    product_dir: str = ""
    skus: List[LocalSku] = field(default_factory=list)
    #: 采集目录下按角色归好类的本地图片绝对路径。
    main_images: List[str] = field(default_factory=list)
    detail_images: List[str] = field(default_factory=list)
    white_bg_image: str = ""
    square_images: List[str] = field(default_factory=list)
    captured_attributes: Optional[Dict[str, Any]] = None


# ---------------------------------------------------------------------------
# 第 2 层：平台无关的发布意图
# ---------------------------------------------------------------------------
@dataclass(slots=True)
class EvidenceRef:
    """一条证据引用。写入 ``field_mapping.json`` 与运行时产物都复用这个形状。"""

    level: str = EVIDENCE_UNKNOWN
    source: str = ""
    note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {"level": self.level, "source": self.source, "note": self.note}


@dataclass(slots=True)
class CategoryRef:
    """类目引用。

    ``category_id`` 是平台叶子类目 ID，**必须**由类目接口实时拉取后填进来；
    ``path`` 是人类可读的类目路径，只用于展示与人工核对，不做程序判定。
    """

    category_id: str = ""
    path: Tuple[str, ...] = ()
    evidence: EvidenceRef = field(default_factory=EvidenceRef)
    #: 用户在共同类目下拉中选择的名称，仅用于搜索；完整路径和 ID 从候选回读。
    search_keyword: str = ""


@dataclass(slots=True)
class PropEntry:
    """一条类目属性。

    ``prop_id`` / ``value_id`` 是平台侧 ID。红线：属性值必须来自该类目的属性值
    列表，**不可硬编码**；拿不到就是 ``unknown``，进 blockers。
    """

    prop_name: str
    value_name: str
    prop_id: str = ""
    value_id: str = ""
    evidence: EvidenceRef = field(default_factory=EvidenceRef)


@dataclass(slots=True)
class SkuEntry:
    """一条销售规格。

    ``spec_values`` 是「销售属性名 → 属性值名」，例如 ``{"颜色": "黑色", "尺码": "均码"}``。
    平台侧的 ``prop_id``/``value_id`` 在属性阶段统一解析，这里只表达意图。
    """

    spec_values: Dict[str, str] = field(default_factory=dict)
    price: Optional[float] = None
    stock: Optional[int] = None
    outer_id: str = ""
    image_path: str = ""


@dataclass(slots=True)
class ImageSet:
    """按平台用途归类的图片。``role`` 取值固定，避免各处自造字符串。"""

    main: List[str] = field(default_factory=list)
    #: 被 ``main`` 让位的原图（3:4）。只有当主图目录里同时存在 ``_1x1`` 方图时才有值——
    #: 那时 ``main`` 取方图（淘宝 1:1 主图必填），原图留在这里备用。
    main_plain: List[str] = field(default_factory=list)
    detail: List[str] = field(default_factory=list)
    sku: List[str] = field(default_factory=list)
    white_bg: str = ""

    def iter_all(self) -> List[str]:
        result = list(self.main) + list(self.detail) + list(self.sku)
        if self.white_bg:
            result.append(self.white_bg)
        return result


@dataclass(slots=True)
class PublishItem:
    """平台无关的发布意图。流水线各阶段只读这个对象。"""

    record_id: int
    record_name: str
    title: str = ""
    category: CategoryRef = field(default_factory=CategoryRef)
    props: List[PropEntry] = field(default_factory=list)
    skus: List[SkuEntry] = field(default_factory=list)
    images: ImageSet = field(default_factory=ImageSet)
    freight_template_name: str = ""
    freight_template_id: str = ""
    #: 导购标题。**选填**——空着就不填，不编造。
    #:
    #: 实测表单上有这一行（``MEASURED_ROW_LABELS["导购标题"]["controls"] == 1``），
    #: 而界面一直在收集它却**从未传给流水线**——操作人填了会被静默丢弃。
    guide_title: str = ""

    outer_id: str = ""
    # 已删除：`notice: str = ""`（购买须知，E-304 加入）。界面在 E-318 撤掉了入口，
    # 侧车的淘宝请求白名单也没有它——**没有任何调用方能给出非空值**，留着就是把死值
    # 写进死行。删掉的是这段通路，不是那条事实：平台表单上「购买须知」行仍在
    # （`locating.VERIFIED_LABELS['fill_price_stock']` 含它，`MEASURED_ROW_LABELS` 控件数 1）。
    # 要重新接上，五处缺一不可：模型字段 / `mapping.build_publish_item` 的解析 /
    # `stage_fill_price_stock` 的写入 / `expected_field_values` 的回读期望 / 契约条目。
    source_url: str = ""
    #: 桌面单名称 SKU 使用 custom；旧调用方仍明确采用 standard。
    sku_mode: str = "standard"
    captured_attributes: Optional[Dict[str, Any]] = None

    def summary(self) -> Dict[str, Any]:
        """用于进度上报的摘要。**不含任何敏感数据。**"""

        return {
            "record_id": self.record_id,
            "record_name": self.record_name,
            "title_length": count_title_units((self.title or "").strip()),
            "category_id": self.category.category_id,
            "prop_count": len(self.props),
            "sku_count": len(self.skus),
            "main_image_count": len(self.images.main),
            "detail_image_count": len(self.images.detail),
            "has_white_bg": bool(self.images.white_bg),
            "freight_template_id": self.freight_template_id,
        }


# ---------------------------------------------------------------------------
# 第 3 层：流水线运行态
# ---------------------------------------------------------------------------
#: 阶段状态取值。与抖店 v4 保持一致，前端 ``UploadStepInfo`` 可零改动复用。
STEP_RUNNING = "running"
STEP_OK = "ok"
STEP_FAILED = "failed"
STEP_SKIPPED = "skipped"
#: 收到取消请求后**未被执行的**阶段。
#:
#: 与 ``skipped`` 分开：``skipped`` 是「按计划就不做」（例如 dry-run 跳过写阶段），
#: ``cancelled`` 是「本来要做，但用户叫停了」。把两者混起来，前端就没法区分
#: 「这个阶段不需要跑」和「这个阶段还没跑」。
STEP_CANCELLED = "cancelled"

#: 单调递增的进度锚点（百分比）。与抖店 v4 的 ``step_pcts`` 同构。
STAGE_PCTS: Tuple[int, ...] = (5, 12, 30, 40, 52, 64, 74, 82, 88, 94, 100)


@dataclass
class StepRecord:
    """一个阶段的执行记录。字段名对齐抖店 v4 的 ``steps[]`` 元素。"""

    name: str
    status: str = STEP_RUNNING
    elapsed_ms: int = 0
    summary: str = ""
    error_code: str = ""
    #: 阶段的**诊断明细**（如 `fill_required_attrs` 的逐项结果）。
    #:
    #: 为什么步骤要能带数据：失败时早先只留 `summary` + `blockers`，
    #: 于是"逐项为什么没成功"这种内部明细**在失败时全部丢失**，只能重跑猜。
    #: 只在非空时进产物，避免把成功步骤的 `steps[]` 撑大。
    data: Dict[str, Any] = field(default_factory=dict)

    @property
    def label(self) -> str:
        return STAGE_LABELS.get(self.name, self.name)

    @property
    def write_operation(self) -> Optional[str]:
        return STAGE_WRITE_OPERATION.get(self.name)

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "name": self.name,
            "label": self.label,
            "status": self.status,
            "elapsed_ms": self.elapsed_ms,
            "summary": self.summary,
        }
        if self.error_code:
            payload["error_code"] = self.error_code
        if self.data:
            payload["data"] = self.data
        return payload


@dataclass
class PipelineResult:
    """流水线返回值。``success`` 为假时 ``error`` 必填。"""

    success: bool
    stage: str = ""
    error: Dict[str, Any] = field(default_factory=dict)
    steps: List[StepRecord] = field(default_factory=list)
    blockers: List[Dict[str, Any]] = field(default_factory=list)
    dry_run: bool = True
    stopped_before_submit: bool = False
    data: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "stage": self.stage,
            "error": dict(self.error),
            "steps": [step.to_dict() for step in self.steps],
            "blockers": list(self.blockers),
            "dry_run": self.dry_run,
            "stopped_before_submit": self.stopped_before_submit,
            "data": dict(self.data),
        }


def build_stage_plan(include_submit: bool = True) -> List[str]:
    """产出本次要执行的阶段序列。

    :param include_submit: 为 ``False`` 时截掉 ``submit`` 阶段（``stop_before_submit``
        语义）。这是唯一允许裁剪的阶段——其余阶段缺一步都会让发布结果不可解释。
    """

    stages = list(STAGE_ORDER)
    if not include_submit and stages and stages[-1] == "submit":
        stages.pop()
    return stages

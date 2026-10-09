# -*- coding: utf-8 -*-
"""本地商品 → 发布意图 → 平台载荷。

三条硬规则（都来自 ``taobao-publisher/AGENTS.md``）：

1. **平台字段名只能来自契约**。本模块不出现任何字面量形式的淘宝字段名。
2. **缺证据就阻塞**。必填字段拿不到 ``write_eligible`` 的平台字段名时，产出
   ``EVIDENCE_INSUFFICIENT`` 阻塞项，而不是编一个默认值。
3. **不按名称猜 ID**。运费模板这类「本地只有中文名、平台只认 ID」的映射，
   匹配不到就终止。抖店侧已经因为猜模板发错店铺（见
   ``protocol-research-clean-20260505/scripts/fxg_protocol_v4.py:1063`` 注释），
   淘宝侧不重复这个错误。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .text_rules import count_title_units
from .constants import EVIDENCE_UNKNOWN
from .contracts import Contracts, FieldSpec, load_contracts, validate_contracts
from .errors import (
    SEVERITY_BLOCKER,
    SEVERITY_WARNING,
    Blocker,
    dedupe_blockers,
)
from .models import (
    CategoryRef,
    EvidenceRef,
    ImageSet,
    LocalProduct,
    PropEntry,
    PublishItem,
    SkuEntry,
)

#: 契约里的 intent 标识。集中在此，避免各处拼字符串拼错。
INTENT_TITLE: str = "item.title"
INTENT_CATEGORY_ID: str = "item.category_id"
INTENT_CATEGORY_PATH: str = "item.category_path"
INTENT_OUTER_ID: str = "item.outer_id"
INTENT_PROPS: str = "item.props"
INTENT_SALE_PROPS: str = "item.sale_props"
INTENT_SALE_PROP_VALUES: str = "item.sale_prop_values"
INTENT_SKU_PRICE: str = "sku.price"
INTENT_SKU_STOCK: str = "sku.stock"
INTENT_SKU_OUTER_ID: str = "sku.outer_id"
INTENT_MAIN_IMAGES: str = "media.main_images"
INTENT_DETAIL_IMAGES: str = "media.detail_images"
INTENT_WHITE_BG: str = "media.white_bg_image"
INTENT_FREIGHT_ID: str = "logistics.freight_template_id"
INTENT_DELIVERY_TIME: str = "logistics.delivery_time"
INTENT_LISTING_MODE: str = "publish.listing_mode"

#: 与某个发布意图相关的全部契约 intent。用于「按阶段汇报阻塞项」。
INTENT_ALL: Tuple[str, ...] = (
    INTENT_TITLE,
    INTENT_CATEGORY_ID,
    INTENT_CATEGORY_PATH,
    INTENT_OUTER_ID,
    INTENT_PROPS,
    INTENT_SALE_PROPS,
    INTENT_SALE_PROP_VALUES,
    INTENT_SKU_PRICE,
    INTENT_SKU_STOCK,
    INTENT_SKU_OUTER_ID,
    INTENT_MAIN_IMAGES,
    INTENT_DETAIL_IMAGES,
    INTENT_WHITE_BG,
    INTENT_FREIGHT_ID,
    INTENT_DELIVERY_TIME,
    INTENT_LISTING_MODE,
)


# ---------------------------------------------------------------------------
# 构建发布意图
# ---------------------------------------------------------------------------
@dataclass
class BuildOutcome:
    """构建结果。``item`` 可能非空但 ``blockers`` 非空——是否可继续由预检决定。"""

    item: Optional[PublishItem] = None
    blockers: List[Blocker] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.blockers


def _as_float(value: Any) -> Optional[float]:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> Optional[int]:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def build_publish_item(
    local: LocalProduct,
    request: Mapping[str, Any],
    *,
    contracts: Optional[Contracts] = None,
) -> BuildOutcome:
    """把「本地资产 + 请求参数」合成 :class:`PublishItem`。

    标题优先取请求里的值（用户在界面上改过的），为空时回落到本地记录的标题。
    """

    data = contracts if contracts is not None else load_contracts()
    blockers: List[Blocker] = []

    # 先 strip 再判空：只填空格等于没填，必须回落到本地标题。
    request_title = str(request.get("title") or "").strip()
    title = request_title or str(local.title or "").strip()
    # 导购标题**只从请求取**：本地资料里没有这个概念，不去猜。
    guide_title = str(request.get("guide_title") or "").strip()
    category_raw = request.get("category") or {}
    category_id = str(category_raw.get("category_id") or "").strip()
    category_path = tuple(str(item) for item in (category_raw.get("path") or []))

    props: List[PropEntry] = []
    for raw in request.get("props") or []:
        if not isinstance(raw, Mapping):
            blockers.append(
                Blocker(
                    code="CONTRACT_INVALID",
                    field="props",
                    detail=f"props 元素不是对象：{raw!r}",
                    source="mapping.build_publish_item",
                )
            )
            continue
        props.append(
            PropEntry(
                prop_name=str(raw.get("prop_name") or "").strip(),
                value_name=str(raw.get("value_name") or "").strip(),
                prop_id=str(raw.get("prop_id") or "").strip(),
                value_id=str(raw.get("value_id") or "").strip(),
                evidence=EvidenceRef(
                    level=str(raw.get("evidence_level") or EVIDENCE_UNKNOWN),
                    source=str(raw.get("evidence_source") or ""),
                ),
            )
        )

    skus: List[SkuEntry] = []
    for index, raw in enumerate(request.get("skus") or []):
        if not isinstance(raw, Mapping):
            blockers.append(
                Blocker(
                    code="SKU_INVALID",
                    field=f"skus[{index}]",
                    detail=f"skus 元素不是对象：{raw!r}",
                    source="mapping.build_publish_item",
                )
            )
            continue
        spec_values_raw = raw.get("spec_values") or {}
        if not isinstance(spec_values_raw, Mapping):
            blockers.append(
                Blocker(
                    code="SKU_INVALID",
                    field=f"skus[{index}].spec_values",
                    detail="spec_values 必须是对象",
                    source="mapping.build_publish_item",
                )
            )
            spec_values_raw = {}
        skus.append(
            SkuEntry(
                spec_values={str(k).strip(): str(v).strip() for k, v in spec_values_raw.items()},
                price=_as_float(raw.get("price")),
                stock=_as_int(raw.get("stock")),
                outer_id=str(raw.get("outer_id") or "").strip(),
                image_path=str(raw.get("image_path") or "").strip(),
            )
        )

    # --- SKU 输入的自洽性校验 -----------------------------------------------
    #
    # 三条都是**输入本身自相矛盾**，原先一条都不报，于是：
    #   * 全空规格值 → ``_desired_specs()`` 为 ``{}``，规格表建不出来；
    #   * 规格值重复 → 两条 SKU 塌成一条，**操作人说 2 个、流水线建 1 行**；
    #   * 属性集不一致 → 拼不出一张统一的规格表。
    #
    # 红线：输入不对就**显式报阻塞**，不许猜一个默认值让它跑通。
    if len(skus) > 1:
        empty_indexes = [i for i, sku in enumerate(skus) if not sku.spec_values]
        if empty_indexes:
            blockers.append(
                Blocker(
                    code="SKU_INVALID",
                    field="skus[{}].spec_values".format(empty_indexes[0]),
                    detail="第 {} 条 SKU 没有规格值；每条 SKU 都必须写明"
                           "「属性名=属性值」，否则规格表建不出来".format(
                               "、".join(str(i + 1) for i in empty_indexes)),
                    source="mapping.build_publish_item",
                )
            )

        seen: dict = {}
        for index, sku in enumerate(skus):
            if not sku.spec_values:
                continue
            key = tuple(sorted(sku.spec_values.items()))
            if key in seen:
                blockers.append(
                    Blocker(
                        code="SKU_INVALID",
                        field="skus[{}].spec_values".format(index),
                        detail="第 {} 条与第 {} 条 SKU 的规格值完全相同（{}）；"
                               "平台不存在两行同规格的 SKU，会静默少建一行".format(
                                   seen[key] + 1, index + 1,
                                   "、".join("{}={}".format(k, v) for k, v in key)),
                        source="mapping.build_publish_item",
                    )
                )
            else:
                seen[key] = index

        attribute_sets = {frozenset(sku.spec_values) for sku in skus if sku.spec_values}
        if len(attribute_sets) > 1:
            described = " / ".join(
                "{" + "、".join(sorted(names)) + "}"
                for names in sorted(attribute_sets, key=lambda s: sorted(s))
            )
            blockers.append(
                Blocker(
                    code="SKU_INVALID",
                    field="skus",
                    detail="各条 SKU 的属性名不一致（{}）；必须所有 SKU 用同一组属性名，"
                           "否则拼不出一张统一的规格表".format(described),
                    source="mapping.build_publish_item",
                )
            )
    elif len(skus) == 1 and not skus[0].spec_values:
        # 只有一条 SKU 却给了空规格值：多半是操作人忘了填。
        # **不报阻塞**（单 SKU 无规格是合法场景），但记一条供排查。
        pass

    images_raw = request.get("images") or {}
    if not isinstance(images_raw, Mapping):
        blockers.append(
            Blocker(
                code="CONTRACT_INVALID",
                field="images",
                detail="images 必须是对象",
                source="mapping.build_publish_item",
            )
        )
        images_raw = {}

    # 区分「请求里没写 images.main」与「请求里明确写了 images.main = []」。
    # 用 ``or`` 会把后者也回落到本地图片——等于用户说「不要主图」，我们却把他
    # 采集来的图传上去了。显式空列表必须被尊重。
    def pick_images(key: str, fallback: List[str]) -> List[str]:
        if key in images_raw:
            raw_value = images_raw.get(key)
            if raw_value is None:
                return list(fallback)
            if isinstance(raw_value, str):
                return [raw_value] if raw_value else []
            return [str(item) for item in raw_value]
        return list(fallback)

    images = ImageSet(
        main=pick_images("main", local.main_images),
        detail=pick_images("detail", local.detail_images),
        sku=pick_images("sku", list(dict.fromkeys(sku.image_path for sku in skus if sku.image_path))),
        white_bg=str(images_raw.get("white_bg") or local.white_bg_image or ""),
    )

    sku_mode = request.get('sku_mode', 'standard')
    if sku_mode not in ('standard', 'custom'):
        blockers.append(Blocker(code='CONTRACT_INVALID', field='sku_mode',
                                detail='规格模式必须是 standard 或 custom',
                                source='mapping.build_publish_item'))

    item = PublishItem(
        record_id=local.record_id,
        record_name=local.record_name,
        title=title,
        guide_title=guide_title,
        sku_mode=sku_mode,
        category=CategoryRef(
            category_id=category_id,
            path=category_path,
            evidence=EvidenceRef(level=_field_level(data, INTENT_CATEGORY_ID), source="contracts/field_mapping.json"),
            search_keyword=str(category_raw.get("search_keyword") or "").strip(),
        ),
        props=props,
        captured_attributes=local.captured_attributes,
        skus=skus,
        images=images,
        # 桌面自定义模式不把旧记录里未绑定平台的模板当作淘宝模板。
        # 没有明确请求值时，由当前账户页面的已选模板决定；不猜列表默认项。
        freight_template_name=str(request.get("freight_template_name") or (
            local.shipping_template if sku_mode == 'standard' else '') or "").strip(),
        outer_id=str(request.get("outer_id") or "").strip(),
        # 已删除：`notice=str(request.get("notice") or "").strip()`。请求里不会再有这个
        # 键（界面不收集、侧车不转发，见 models.PublishItem 的说明），解析它只是把死值
        # 搬进一个已经删掉的字段。
        source_url=str(request.get("source_url") or local.source_url or ""),
    )

    return BuildOutcome(item=item, blockers=dedupe_blockers(blockers))


def _field_level(contracts: Contracts, intent: str) -> str:
    spec = contracts.field_mapping.maybe(intent)
    return spec.evidence_level if spec else EVIDENCE_UNKNOWN


# ---------------------------------------------------------------------------
# 校验
# ---------------------------------------------------------------------------
def validate_title(item: PublishItem, contracts: Contracts) -> List[Blocker]:
    """标题长度与空值校验。

    ``guide_title`` 是**选填**：空着不报，填了才校验长度——
    契约里 ``guide_title_max_chars`` 是 ``hard: true``，不能只在人工准备路径上查。
    """

    blockers: List[Blocker] = []
    title = (item.title or "").strip()
    title_units = count_title_units(title)
    min_chars = contracts.rules.integer("title_min_chars")
    max_chars = contracts.rules.integer("title_max_chars")
    rule = contracts.rules.get("title_max_chars")
    if title_units < min_chars:
        blockers.append(
            Blocker(
                code="REQUIRED_FIELD_MISSING",
                field="title",
                detail="标题为空",
                source="mapping.validate_title",
            )
        )
    elif title_units > max_chars:
        suffix = "" if rule.evidence_level == "verified" else f"（该上限证据等级为 {rule.evidence_level}，请以类目实时 schema 为准）"
        blockers.append(
            Blocker(
                code="REQUIRED_FIELD_MISSING",
                field="title",
                detail=f"标题长度 {title_units} 超过上限 {max_chars}{suffix}",
                evidence=rule.evidence_level,
                source="mapping.validate_title",
            )
        )

    guide = (getattr(item, "guide_title", "") or "").strip()
    if guide:
        guide_rule = contracts.rules.get("guide_title_max_chars")
        if guide_rule is not None and guide_rule.hard:
            guide_max = guide_rule.integer()
            if count_title_units(guide) > guide_max:
                blockers.append(
                    Blocker(
                        code="TITLE_TOO_LONG",
                        field="guide_title",
                        detail="导购标题长度 {} 超过上限 {}".format(count_title_units(guide), guide_max),
                        evidence=guide_rule.evidence_level,
                        source="mapping.validate_title",
                    )
                )
    return blockers


def validate_skus(item: PublishItem, contracts: Contracts) -> List[Blocker]:
    """SKU 结构校验：数量、价格、库存、规格一致性、重复组合。"""

    blockers: List[Blocker] = []
    skus = item.skus
    min_count = contracts.rules.integer("sku_min_count")
    price_min = contracts.rules.number("sku_price_min")

    if len(skus) < min_count:
        blockers.append(
            Blocker(
                code="SKU_INVALID",
                field="skus",
                detail=f"至少需要 {min_count} 条 SKU，当前 {len(skus)} 条",
                source="mapping.validate_skus",
            )
        )
        return blockers

    max_count_rule = contracts.rules.get("sku_max_count")
    if len(skus) > max_count_rule.integer():
        # 只告警不阻塞：该数字来自第三方实测，未经本仓库复核。
        blockers.append(
            Blocker(
                code="SKU_INVALID",
                field="skus",
                detail=(
                    f"SKU 数量 {len(skus)} 超过 {max_count_rule.integer()} 条；"
                    "平台可能出现懒加载，需要走虚拟滚动路径"
                    f"（该阈值证据等级 {max_count_rule.evidence_level}，仅告警）"
                ),
                severity=SEVERITY_WARNING,
                evidence=max_count_rule.evidence_level,
                source="mapping.validate_skus",
            )
        )

    spec_key_sets = set()
    seen_combos: Dict[Tuple[Tuple[str, str], ...], int] = {}
    for index, sku in enumerate(skus):
        field_prefix = f"skus[{index}]"
        if sku.price is None:
            blockers.append(
                Blocker(
                    code="REQUIRED_FIELD_MISSING",
                    field=f"{field_prefix}.price",
                    detail="SKU 缺少价格；本地没有可靠默认值，必须显式提供",
                    source="mapping.validate_skus",
                )
            )
        elif sku.price < price_min:
            blockers.append(
                Blocker(
                    code="PRICE_INVALID",
                    field=f"{field_prefix}.price",
                    detail=f"价格 {sku.price} 小于下限 {price_min}",
                    source="mapping.validate_skus",
                )
            )
        if sku.stock is None:
            blockers.append(
                Blocker(
                    code="REQUIRED_FIELD_MISSING",
                    field=f"{field_prefix}.stock",
                    detail="SKU 缺少库存；本地 record 表无库存字段，必须显式提供",
                    source="mapping.validate_skus",
                )
            )
        elif sku.stock < 0:
            blockers.append(
                Blocker(
                    code="PRICE_INVALID",
                    field=f"{field_prefix}.stock",
                    detail=f"库存为负数：{sku.stock}",
                    source="mapping.validate_skus",
                )
            )

        for key, value in sku.spec_values.items():
            if not key.strip() or not value.strip():
                blockers.append(
                    Blocker(
                        code="SKU_INVALID",
                        field=f"{field_prefix}.spec_values",
                        detail=f"销售属性名或值为空：{key!r}={value!r}",
                        source="mapping.validate_skus",
                    )
                )
        spec_key_sets.add(tuple(sorted(sku.spec_values.keys())))
        combo = tuple(sorted(sku.spec_values.items()))
        if combo in seen_combos:
            blockers.append(
                Blocker(
                    code="SKU_INVALID",
                    field=f"{field_prefix}.spec_values",
                    detail=f"规格组合与 skus[{seen_combos[combo]}] 重复：{dict(sku.spec_values)}",
                    source="mapping.validate_skus",
                )
            )
        else:
            seen_combos[combo] = index

    # 单条无规格 SKU 是合法的（平台会用默认规格）；多条则规格维度必须一致。
    non_empty_sets = {keys for keys in spec_key_sets if keys}
    if len(skus) > 1 and len(non_empty_sets) > 1:
        blockers.append(
            Blocker(
                code="SKU_INVALID",
                field="skus",
                detail=(
                    "多条 SKU 的销售属性维度不一致："
                    + "、".join("/".join(keys) or "(空)" for keys in sorted(spec_key_sets))
                ),
                source="mapping.validate_skus",
            )
        )
    if len(skus) > 1 and any(not keys for keys in spec_key_sets):
        blockers.append(
            Blocker(
                code="SKU_INVALID",
                field="skus",
                detail="多条 SKU 中存在没有任何销售属性的行，平台无法建立规格表",
                source="mapping.validate_skus",
            )
        )

    return blockers


def validate_images(item: PublishItem, contracts: Contracts) -> List[Blocker]:
    """主图数量、尺寸与体积校验。

    尺寸校验依赖 Pillow。**Pillow 不可用时直接阻塞**，不静默跳过——
    跳过会让「没检查」被误读成「检查通过」。
    """

    blockers: List[Blocker] = []
    min_count = contracts.rules.integer("main_image_min_count")
    max_count = contracts.rules.integer("main_image_max_count")
    min_side = contracts.rules.integer("main_image_min_side_px")

    main = list(item.images.main)
    if len(main) < min_count:
        blockers.append(
            Blocker(
                code="REQUIRED_FIELD_MISSING",
                field="images.main",
                detail=f"主图至少 {min_count} 张，当前 {len(main)} 张",
                source="mapping.validate_images",
            )
        )
    if len(main) > max_count:
        blockers.append(
            Blocker(
                code="REQUIRED_FIELD_MISSING",
                field="images.main",
                detail=f"主图最多 {max_count} 张，当前 {len(main)} 张",
                source="mapping.validate_images",
            )
        )

    try:
        from PIL import Image  # type: ignore
    except ImportError:
        blockers.append(
            Blocker(
                code="EVIDENCE_INSUFFICIENT",
                field="images.main",
                detail="缺少 Pillow，无法校验主图尺寸；不允许跳过校验后继续",
                source="mapping.validate_images",
            )
        )
        return blockers

    from pathlib import Path

    ratio_rule = contracts.rules.get("main_image_aspect_ratio")
    tolerance = ratio_rule.tolerance if ratio_rule.tolerance is not None else 0.02
    target_ratio = ratio_rule.number()

    # 这两条以前**没有执行**，而契约里都是 hard: true——实测一个 3.71 MB 的图
    # 或一个 .bmp 能一路通过静态预检，到平台上才被拒。
    max_bytes = contracts.rules.integer("main_image_max_bytes")
    formats_rule = contracts.rules.get("main_image_formats")
    allowed_formats = formats_rule.strings() if formats_rule is not None else ()

    for index, path in enumerate(main):
        field_name = f"images.main[{index}]"
        candidate = Path(path)
        if not candidate.is_file():
            blockers.append(
                Blocker(
                    code="REQUIRED_FIELD_MISSING",
                    field=field_name,
                    detail=f"主图文件不存在：{path}",
                    source="mapping.validate_images",
                )
            )
            continue
        try:
            with Image.open(candidate) as handle:
                width, height = handle.size
        except OSError as exc:
            blockers.append(
                Blocker(
                    code="IMAGE_UPLOAD_FAILED",
                    field=field_name,
                    detail=f"主图无法解码：{path}（{exc}）",
                    source="mapping.validate_images",
                )
            )
            continue
        suffix = candidate.suffix.lower().lstrip(".")
        if allowed_formats and suffix not in allowed_formats:
            blockers.append(
                Blocker(
                    code="IMAGE_UPLOAD_FAILED",
                    field=field_name,
                    detail="主图格式 {!r} 不在允许范围 {}：{}".format(
                        suffix, "、".join(allowed_formats), candidate.name),
                    source="mapping.validate_images",
                )
            )

        try:
            size_bytes = candidate.stat().st_size
        except OSError as exc:
            blockers.append(
                Blocker(
                    code="IMAGE_UPLOAD_FAILED",
                    field=field_name,
                    detail="主图无法读取体积：{}（{}）".format(path, exc),
                    source="mapping.validate_images",
                )
            )
            size_bytes = 0
        if size_bytes > max_bytes:
            blockers.append(
                Blocker(
                    code="IMAGE_UPLOAD_FAILED",
                    field=field_name,
                    detail="主图 {:.2f} MB 超过上限 {:.2f} MB：{}".format(
                        size_bytes / 1024 / 1024, max_bytes / 1024 / 1024,
                        candidate.name),
                    source="mapping.validate_images",
                )
            )

        if min(width, height) < min_side:
            blockers.append(
                Blocker(
                    code="IMAGE_UPLOAD_FAILED",
                    field=field_name,
                    detail=f"主图最小边 {min(width, height)}px 小于 {min_side}px：{candidate.name}",
                    source="mapping.validate_images",
                )
            )
        if height > 0:
            ratio = width / height
            if abs(ratio - target_ratio) > tolerance:
                blockers.append(
                    Blocker(
                        code="IMAGE_UPLOAD_FAILED",
                        field=field_name,
                        detail=(
                            f"主图宽高比 {ratio:.4f} 偏离 {target_ratio:.2f}"
                            f"（容差 {tolerance}）：{candidate.name}"
                        ),
                        source="mapping.validate_images",
                    )
                )

    return blockers


# ---------------------------------------------------------------------------
# 运费模板：严格匹配，匹配不到就终止
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class FreightMatch:
    """运费模板匹配结果。"""

    matched_id: str = ""
    matched_name: str = ""
    candidates: Tuple[str, ...] = ()
    blocked: bool = True
    reason: str = ""


def match_freight_template(
    configured_name: str,
    options: Sequence[Mapping[str, Any]],
) -> FreightMatch:
    """把本地运费模板**名称**匹配到平台模板 **ID**。

    规则（比抖店 v3 更严，因为猜错模板会直接把货运费算错）：

    1. 名称精确相等（去首尾空白）→ 唯一命中才算成功。
    2. 否则按「包含」匹配；**命中多于一个即视为歧义，直接失败**。
    3. 都不中 → 失败。

    任何失败都返回 ``blocked=True``，由调用方转成阻塞项。
    **绝不返回默认模板 ID。**
    """

    name = (configured_name or "").strip()
    if not name:
        return FreightMatch(blocked=True, reason="本地未配置运费模板名称")

    normalized: List[Tuple[str, str]] = []
    for option in options or []:
        if not isinstance(option, Mapping):
            continue
        option_name = str(option.get("name") or "").strip()
        option_id = str(option.get("id") or option.get("template_id") or "").strip()
        if option_name and option_id:
            normalized.append((option_name, option_id))

    if not normalized:
        return FreightMatch(blocked=True, reason="平台未返回任何可用运费模板")

    all_names = tuple(sorted(item[0] for item in normalized))

    exact = [item for item in normalized if item[0] == name]
    if len(exact) == 1:
        return FreightMatch(
            matched_id=exact[0][1],
            matched_name=exact[0][0],
            candidates=all_names,
            blocked=False,
        )
    if len(exact) > 1:
        return FreightMatch(
            candidates=all_names,
            blocked=True,
            reason=f"平台存在 {len(exact)} 个同名运费模板「{name}」，无法判定用哪个",
        )

    contained = [item for item in normalized if name in item[0] or item[0] in name]
    if len(contained) == 1:
        return FreightMatch(
            matched_id=contained[0][1],
            matched_name=contained[0][0],
            candidates=all_names,
            blocked=False,
        )
    if len(contained) > 1:
        return FreightMatch(
            candidates=all_names,
            blocked=True,
            reason=f"运费模板「{name}」模糊匹配到 {len(contained)} 个候选，拒绝猜测",
        )

    return FreightMatch(
        candidates=all_names,
        blocked=True,
        reason=f"运费模板「{name}」在平台模板列表中不存在",
    )


# ---------------------------------------------------------------------------
# 契约门：能不能真的写
# ---------------------------------------------------------------------------
def collect_unmapped_fields(
    contracts: Contracts,
    intents: Sequence[str] = INTENT_ALL,
    *,
    severity: str = SEVERITY_BLOCKER,
) -> List[Blocker]:
    """收集所有「不可写」字段的阻塞项。

    无论本次请求是否用到了这些字段，都回报——因为它们是**真实发布前必须解决**
    的清单，藏起来只会让人以为流水线已经可用了。

    :param severity: 证据缺口的严重级别。**真实写入前传 ``blocker``**；
        只做数据校验时传 ``warning``，因为「数据本身对不对」与「这条路能不能走」
        是两个问题，混在一起会让 dry-run 永远失败、失去意义。

    ## 认路线（2026-10-03 修正）

    字段证据**两条路线各有一套**：

    * **协议路线**：``field_mapping.json`` 的 ``platform_field`` + ``verified`` + 来源；
    * **DOM 路线**：该字段所属阶段的**写关键选择器全部就位**
      （见 :meth:`SelectorContract.dom_ready_stages`）。

    两条**任一条**成立即视为有证据——原来只认协议路线，导致 DOM 路线证据齐了
    字段照样被判为不可写、真实写入永远被拦。``field_mapping.json`` 里那些
    ``blocker_hint`` 早就写着「**或在 DOM 路线中确认……**」，这里只是把
    那句话落到实处。
    """

    #: DOM 路线已就绪的阶段集合
    dom_stages = contracts.selectors.dom_ready_stages()

    blockers: List[Blocker] = []
    for intent in intents:
        spec: Optional[FieldSpec] = contracts.field_mapping.maybe(intent)
        if spec is None:
            blockers.append(
                Blocker(
                    code="CONTRACT_INVALID",
                    field=intent,
                    detail="契约里没有该 intent",
                    source="mapping.collect_unmapped_fields",
                )
            )
            continue
        if spec.write_eligible:
            continue
        # DOM 路线的证据：该字段所属阶段的选择器齐了。
        if spec.stage and spec.stage in dom_stages:
            continue
        blockers.append(
            Blocker(
                code="EVIDENCE_INSUFFICIENT",
                field=intent,
                detail=(
                    f"两条路线都没有该字段的证据（platform_field={spec.platform_field!r}，"
                    f"evidence={spec.evidence_level}；阶段 {spec.stage!r} 的写关键选择器也未齐）。"
                    f"{spec.blocker_hint}"
                ).strip(),
                severity=severity,
                evidence=spec.evidence_level,
                source="contracts/field_mapping.json",
                extra={"required": spec.required, "stage": spec.stage},
            )
        )
    return blockers


def build_platform_payload(
    item: PublishItem,
    contracts: Optional[Contracts] = None,
) -> Tuple[Dict[str, Any], List[Blocker]]:
    """按契约产出平台载荷。

    :return: ``(payload, blockers)``。``payload`` 只包含**已实证可写**的字段；
        必填但不可写的字段会出现在 ``blockers`` 里。调用方在 ``blockers`` 非空时
        **必须**拒绝进入写操作。

    **契约自检不通过时直接返回空载荷**：一条「标为 verified 但没有 evidence.source」
    的问题如果只是被打印出来，字段照样能进载荷，那自检就没有任何强制力
    （对抗性审查 2026-10-02，F8）。宁可拒绝组装，也不产出无法追溯到证据的字段。
    """

    data = contracts if contracts is not None else load_contracts()

    contract_problems = validate_contracts(data)
    if contract_problems:
        return {}, [
            Blocker(
                code="CONTRACT_INVALID",
                field="contracts",
                detail=(
                    "契约自检未通过，拒绝组装平台载荷："
                    + "；".join(contract_problems)
                ),
                source="mapping.build_platform_payload",
            )
        ]

    payload: Dict[str, Any] = {}
    blockers: List[Blocker] = []

    def place(intent: str, value: Any) -> None:
        spec = data.field_mapping.maybe(intent)
        if spec is None:
            blockers.append(
                Blocker(
                    code="CONTRACT_INVALID",
                    field=intent,
                    detail="契约里没有该 intent",
                    source="mapping.build_platform_payload",
                )
            )
            return
        if not spec.write_eligible:
            blockers.append(
                Blocker(
                    code="EVIDENCE_INSUFFICIENT",
                    field=intent,
                    detail=(
                        f"字段「{intent}」的平台字段名未实证"
                        f"（platform_field={spec.platform_field!r}，evidence={spec.evidence_level}）"
                    ),
                    evidence=spec.evidence_level,
                    source="contracts/field_mapping.json",
                    extra={"required": spec.required, "stage": spec.stage},
                )
            )
            return
        payload[str(spec.platform_field)] = value

    place(INTENT_TITLE, item.title)
    place(INTENT_CATEGORY_ID, item.category.category_id)
    if item.category.path:
        place(INTENT_CATEGORY_PATH, list(item.category.path))
    if item.outer_id:
        place(INTENT_OUTER_ID, item.outer_id)
    if item.props:
        place(INTENT_PROPS, [prop_to_payload_entry(prop, data) for prop in item.props])
    if item.skus:
        place(INTENT_SALE_PROPS, sorted({key for sku in item.skus for key in sku.spec_values}))
        place(
            INTENT_SALE_PROP_VALUES,
            sorted({value for sku in item.skus for value in sku.spec_values.values()}),
        )
        place(INTENT_SKU_PRICE, [sku.price for sku in item.skus])
        place(INTENT_SKU_STOCK, [sku.stock for sku in item.skus])
    if item.freight_template_id:
        place(INTENT_FREIGHT_ID, item.freight_template_id)
    if item.images.main:
        place(INTENT_MAIN_IMAGES, list(item.images.main))
    if item.images.detail:
        place(INTENT_DETAIL_IMAGES, list(item.images.detail))
    if item.images.white_bg:
        place(INTENT_WHITE_BG, item.images.white_bg)

    return payload, dedupe_blockers(blockers)


def prop_to_payload_entry(prop: PropEntry, contracts: Contracts) -> Dict[str, Any]:
    """把一条属性转成载荷条目。

    属性 ID/值 ID 缺失时**保留名称并标记缺 ID**，由后续阶段或人工补齐——
    这里不生成假的 ID。真正的 ID 解析属于 ``fill_props`` 阶段（需要平台查表）。
    """

    return {
        "prop_name": prop.prop_name,
        "value_name": prop.value_name,
        "prop_id": prop.prop_id,
        "value_id": prop.value_id,
        "evidence": prop.evidence.to_dict(),
        "ids_resolved": bool(prop.prop_id and prop.value_id),
    }

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable

from .schema_mapping import NO_BRAND_VALUE, SchemaMappingError, build_attribute_plan, infer_enum_property_from_text


class ProtocolDryRunError(ValueError):
    """Raised when local product data cannot be converted into a dry-run plan."""


@dataclass(slots=True)
class SkuDryRunItem:
    index: int
    name: str
    local_path: str
    price: str
    stock: int
    file_name: str = ""
    dir_name: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class RecordDryRunSnapshot:
    record_id: int | None
    name: str
    title: str
    path: str
    type: int | None
    clazz: str
    remark: str
    stock: int
    shipping_template: str
    sku_list: list[SkuDryRunItem] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["sku_list"] = [item.to_dict() for item in self.sku_list]
        return payload


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _read_field(record: Any, field_name: str, default: Any = None) -> Any:
    if isinstance(record, dict):
        return record.get(field_name, default)
    return getattr(record, field_name, default)


def _parse_decimal_text(value: Any, *, label: str) -> str:
    raw = _normalize_text(value)
    if raw == "":
        raise ProtocolDryRunError(f"{label}不能为空")
    try:
        amount = Decimal(raw)
    except (InvalidOperation, ValueError):
        raise ProtocolDryRunError(f"{label}必须是数字：{raw}") from None
    if amount < 0:
        raise ProtocolDryRunError(f"{label}不能小于 0：{raw}")
    normalized = format(amount, "f")
    if "." in normalized:
        normalized = normalized.rstrip("0").rstrip(".")
    return normalized or "0"


def _parse_stock(value: Any) -> int:
    raw = _normalize_text(value)
    if raw == "":
        raise ProtocolDryRunError("库存不能为空")
    try:
        stock = int(Decimal(raw))
    except (InvalidOperation, ValueError):
        raise ProtocolDryRunError(f"库存必须是整数：{raw}") from None
    if stock < 0:
        raise ProtocolDryRunError(f"库存不能小于 0：{raw}")
    return stock


def _parse_sku_content(content: Any) -> list[dict[str, Any]]:
    if isinstance(content, str):
        try:
            content = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ProtocolDryRunError(f"SKU JSON 解析失败：{exc}") from exc
    if not isinstance(content, list):
        raise ProtocolDryRunError("SKU 内容必须是数组")
    return [item for item in content if isinstance(item, dict)]


def _parse_record_stock(record: Any) -> int:
    raw_repo = _read_field(record, "repo")
    if raw_repo not in (None, ""):
        return _parse_stock(raw_repo)
    raw_stock = _read_field(record, "stock")
    if raw_stock not in (None, ""):
        return _parse_stock(raw_stock)
    raise ProtocolDryRunError("库存不能为空")


def _parse_record_sku_items(record: Any) -> list[dict[str, Any]]:
    raw_content = _read_field(record, "content")
    if raw_content not in (None, "", []):
        return _parse_sku_content(raw_content)

    raw_sku_list = _read_field(record, "sku_list", [])
    if not isinstance(raw_sku_list, list):
        raise ProtocolDryRunError("SKU 列表必须是数组")

    normalized_items: list[dict[str, Any]] = []
    for item in raw_sku_list:
        if not isinstance(item, dict):
            continue
        normalized_items.append({
            "name": item.get("name"),
            "path": item.get("path") or item.get("local_path"),
            "price": item.get("price"),
            "file_name": item.get("file_name"),
            "dir_name": item.get("dir_name"),
        })
    return normalized_items


def normalize_record_snapshot(record: Any) -> RecordDryRunSnapshot:
    title = _normalize_text(_read_field(record, "title"))
    if not title:
        raise ProtocolDryRunError("商品标题不能为空")

    path = _normalize_text(_read_field(record, "path"))
    if not path:
        raise ProtocolDryRunError("商品目录不能为空")

    stock = _parse_record_stock(record)
    raw_skus = _parse_record_sku_items(record)
    if not raw_skus:
        raise ProtocolDryRunError("SKU 列表不能为空")

    sku_items: list[SkuDryRunItem] = []
    for index, item in enumerate(raw_skus, start=1):
        name = _normalize_text(item.get("name"))
        local_path = _normalize_text(item.get("path"))
        if not name:
            raise ProtocolDryRunError(f"第 {index} 个 SKU 名称为空")
        if not local_path:
            raise ProtocolDryRunError(f"第 {index} 个 SKU 图片路径为空")
        sku_items.append(
            SkuDryRunItem(
                index=index,
                name=name,
                local_path=local_path,
                price=_parse_decimal_text(item.get("price"), label=f"第 {index} 个 SKU 价格"),
                stock=stock,
                file_name=_normalize_text(item.get("file_name")),
                dir_name=_normalize_text(item.get("dir_name")),
            )
        )

    return RecordDryRunSnapshot(
        record_id=_read_field(record, "id"),
        name=_normalize_text(_read_field(record, "name")),
        title=title,
        path=path,
        type=_read_field(record, "type"),
        clazz=_normalize_text(_read_field(record, "clazz")),
        remark=_normalize_text(_read_field(record, "remark")),
        stock=stock,
        shipping_template=_normalize_text(_read_field(record, "shipping_template")) or "中通包邮",
        sku_list=sku_items,
    )


def _schema_category(schema_summary: dict[str, Any]) -> dict[str, Any]:
    category = schema_summary.get("category")
    if not isinstance(category, dict):
        raise ProtocolDryRunError("schema 缺少 category")

    leaf_id = category.get("categoryLeafId") or category.get("fourth_cid") or category.get("third_cid")
    if not leaf_id:
        raise ProtocolDryRunError("schema category 缺少叶子类目 ID")

    return {
        "category_leaf_id": int(leaf_id),
        "first_cid": category.get("first_cid"),
        "first_cname": category.get("first_name"),
        "second_cid": category.get("second_cid"),
        "second_cname": category.get("second_name"),
        "third_cid": category.get("third_cid"),
        "third_cname": category.get("third_name"),
        "fourth_cid": category.get("fourth_cid"),
        "fourth_cname": category.get("fourth_name"),
    }


def _infer_tube_height(schema_summary: dict[str, Any], snapshot: RecordDryRunSnapshot) -> str:
    category = schema_summary.get("category") if isinstance(schema_summary.get("category"), dict) else {}
    leaf = _normalize_text(category.get("fourth_name") or category.get("third_name"))
    if leaf in ("长筒袜", "中筒袜", "短筒袜"):
        return leaf
    if leaf in ("短袜", "船袜", "袜套"):
        return "短筒袜"

    clazz_map = {
        "1": "短筒袜",
        "2": "中筒袜",
        "3": "长筒袜",
        "4": "短筒袜",
    }
    return clazz_map.get(snapshot.clazz, "")


def _tube_height_from_record(snapshot: RecordDryRunSnapshot) -> str:
    clazz_map = {
        "1": "短筒袜",
        "2": "中筒袜",
        "3": "长筒袜",
        "4": "短筒袜",
    }
    return clazz_map.get(snapshot.clazz, "")


def _tube_height_from_schema_category(schema_summary: dict[str, Any]) -> str:
    category = schema_summary.get("category") if isinstance(schema_summary.get("category"), dict) else {}
    leaf = _normalize_text(category.get("fourth_name") or category.get("third_name"))
    if leaf in ("长筒袜", "中筒袜", "短筒袜"):
        return leaf
    if leaf in ("短袜", "船袜", "袜套"):
        return "短筒袜"
    return ""


def _validate_record_schema_category_alignment(
    *,
    schema_summary: dict[str, Any],
    snapshot: RecordDryRunSnapshot,
    explicit_tube_height: str,
) -> None:
    schema_tube_height = _tube_height_from_schema_category(schema_summary)
    record_tube_height = _tube_height_from_record(snapshot)
    if not schema_tube_height or not record_tube_height:
        return
    if explicit_tube_height:
        return
    if schema_tube_height != record_tube_height:
        raise ProtocolDryRunError(
            "商品记录类目与当前 schema 不一致："
            f"record.clazz={snapshot.clazz} 推断为 {record_tube_height}，"
            f"schema 类目推断为 {schema_tube_height}。"
            "请先用匹配该商品类目的 schema 重新生成 dry-run，或显式传入 --tube-height 后再审计。"
        )


def _infer_gender_from_title(title: str) -> str:
    title = _normalize_text(title)
    if "男" in title and "女" in title:
        return "通用"
    if "男" not in title and "女" not in title:
        return "通用"
    if "男" in title:
        return "男"
    return "女"


def _infer_thickness_from_title(schema_summary: dict[str, Any], title: str) -> str:
    inferred = infer_enum_property_from_text(
        schema_summary,
        label="厚度",
        text=title,
    )
    if not inferred:
        return ""
    return inferred.value_name


def _default_materials(materials: Iterable[tuple[str, int | float | str]] | None) -> list[tuple[str, int | float | str]]:
    if materials is None:
        return [("棉", 75), ("氨纶", 25)]
    return list(materials)


def _media_local_assets(assets: dict[str, Any] | None) -> dict[str, Any]:
    assets = assets or {}
    return {
        "pic": list(assets.get("main_pic_list") or []),
        "main_image_three_to_four": list(assets.get("sub_pic_list") or []),
        "description_images": list(assets.get("detail_pic_list") or []),
        "white_background_pic": assets.get("white_pic"),
        "main_pic_video": assets.get("my_video"),
        "qualification_image": assets.get("diaopai_pic") or assets.get("wash_label_tag_image_path"),
    }


def _split_sku_name(name: str) -> tuple[str, str]:
    parts = [
        _normalize_text(part)
        for part in _normalize_text(name).replace("／", "/").split("/")
        if _normalize_text(part)
    ]
    if not parts:
        return "", "均码"
    if len(parts) == 1:
        return parts[0], "均码"
    return parts[0], parts[1]


def _unique_named_values(values: Iterable[tuple[str, int | None, str | None]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for name, source_index, local_path in values:
        normalized_name = _normalize_text(name)
        if not normalized_name or normalized_name in seen:
            continue
        seen.add(normalized_name)
        result.append({
            "name": normalized_name,
            "source_index": source_index,
            "local_image_path": local_path,
        })
    return result


def _build_axis_value_candidates(
    *,
    axis_id: str,
    axis_name: str,
    sku_items: list[SkuDryRunItem],
    tube_height_value: str,
) -> list[dict[str, Any]]:
    color_values = _unique_named_values(
        (_split_sku_name(item.name)[0], item.index, item.local_path)
        for item in sku_items
    )
    size_values = _unique_named_values(
        (_split_sku_name(item.name)[1], None, None)
        for item in sku_items
    )
    if not size_values:
        size_values = [{"name": "均码", "source_index": None, "local_image_path": None}]

    if axis_name == "颜色分类":
        raw_values = color_values
    elif axis_name in ("码数", "规格"):
        raw_values = size_values
    elif axis_name == "筒高长度":
        raw_values = [{"name": tube_height_value, "source_index": None, "local_image_path": None}] if tube_height_value else []
    else:
        raw_values = []

    values: list[dict[str, Any]] = []
    for index, item in enumerate(raw_values, start=1):
        values.append({
            "source_index": item["source_index"] if item["source_index"] is not None else index,
            "id": f"dry_{axis_id}_{index}",
            "name": item["name"],
            "img_url": None,
            "measure_info": None,
            "local_image_path": item["local_image_path"],
        })
    return values


def _build_spec_detail_candidate(
    schema_summary: dict[str, Any],
    sku_items: list[SkuDryRunItem],
    tube_height_value: str,
) -> list[dict[str, Any]]:
    spec_items = schema_summary.get("specDetail")
    if not isinstance(spec_items, list):
        spec_items = []

    result: list[dict[str, Any]] = []
    for spec in spec_items:
        if not isinstance(spec, dict):
            continue
        name = _normalize_text(spec.get("name"))
        axis_id = _normalize_text(spec.get("id")) or f"axis_{len(result) + 1}"
        spec_values = _build_axis_value_candidates(
            axis_id=axis_id,
            axis_name=name,
            sku_items=sku_items,
            tube_height_value=tube_height_value,
        )

        result.append(
            {
                "id": axis_id,
                "cp_id": spec.get("cp_id"),
                "name": name,
                "spec_values": spec_values,
                "field_shape_evidence": "front-end model schema",
                "protocol_value_ids_verified": False,
            }
        )
    return result


def _first_spec_value_id(axis: dict[str, Any], value_name: str = "") -> str:
    values = axis.get("spec_values") if isinstance(axis.get("spec_values"), list) else []
    if value_name:
        matched = next(
            (
                item
                for item in values
                if isinstance(item, dict) and _normalize_text(item.get("name")) == value_name
            ),
            None,
        )
        if isinstance(matched, dict):
            return _normalize_text(matched.get("id"))
    first_value = values[0] if values else {}
    return _normalize_text(first_value.get("id")) if isinstance(first_value, dict) else ""


def _build_sku_detail_candidate(
    sku_items: list[SkuDryRunItem],
    spec_detail_candidate: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in sku_items:
        color_name, size_name = _split_sku_name(item.name)
        spec_detail_ids: list[str] = []
        spec_names: dict[str, str] = {}
        for axis in spec_detail_candidate:
            axis_name = _normalize_text(axis.get("name"))
            value_name = ""
            if axis_name == "颜色分类":
                value_name = color_name
            elif axis_name in ("码数", "规格"):
                value_name = size_name
            elif axis_name == "筒高长度":
                values = axis.get("spec_values") if isinstance(axis.get("spec_values"), list) else []
                value_name = _normalize_text(values[0].get("name")) if values and isinstance(values[0], dict) else ""

            value_id = _first_spec_value_id(axis, value_name)
            if value_id:
                spec_detail_ids.append(value_id)
            if value_name:
                spec_names[axis_name] = value_name

        result.append({
            "id": f"dry_sku_{item.index}",
            "source_index": item.index,
            "spec_detail_ids": spec_detail_ids,
            "sku_pic": [],
            "spec_names": spec_names,
            "price": item.price,
            "stock_info": {"stock_num": int(item.stock)},
            "sku_status": True,
            "confirm_no_barcode": False,
            "local_image_path": item.local_path,
            "field_shape_evidence": "front-end model schema",
            "protocol_value_ids_verified": False,
            "id_note": "dry-run placeholder ID; real body uses platform-generated UUID-like strings assembled from hex segments",
            "spec_detail_ids_note": "dry-run placeholder IDs; real body uses platform-generated numeric IDs",
        })
    return result


def _field_detail_map(schema_summary: dict[str, Any]) -> dict[str, Any]:
    details = schema_summary.get("fieldDetails")
    if not isinstance(details, list):
        return {}
    result: dict[str, Any] = {}
    for item in details:
        if not isinstance(item, dict):
            continue
        key = _normalize_text(item.get("key"))
        if key:
            result[key] = {
                "required": item.get("required"),
                "additionKeys": item.get("additionKeys") or [],
                "extraKeys": item.get("extraKeys") or [],
                "columns": item.get("columns") or [],
                "optionCount": item.get("optionCount"),
                "optionPreview": item.get("optionPreview") or [],
            }
    return result


def _field_detail_by_key(schema_summary: dict[str, Any], key: str) -> dict[str, Any]:
    details = schema_summary.get("fieldDetails")
    if isinstance(details, list):
        for item in details:
            if isinstance(item, dict) and _normalize_text(item.get("key")) == key:
                return item

    model = schema_summary.get("model")
    if isinstance(model, dict):
        item = model.get(key)
        if isinstance(item, dict):
            return item
    return {}


def _resolve_publish_control_from_schema(schema_summary: dict[str, Any], key: str) -> dict[str, Any]:
    runtime_controls = schema_summary.get("publishControls")
    runtime_control = runtime_controls.get(key) if isinstance(runtime_controls, dict) else None
    field_detail = _field_detail_by_key(schema_summary, key)
    runtime_field = runtime_control if isinstance(runtime_control, dict) else {}
    value = _normalize_text(runtime_field.get("valueSample") or runtime_field.get("value") or field_detail.get("valueSample") or field_detail.get("value"))
    options = runtime_field.get("optionPreview") if isinstance(runtime_field.get("optionPreview"), list) else []
    if not options:
        options = field_detail.get("optionPreview") if isinstance(field_detail.get("optionPreview"), list) else []

    matched = None
    if value:
        matched = next(
            (
                item
                for item in options
                if isinstance(item, dict) and _normalize_text(item.get("value_id") or item.get("value")) == value
            ),
            None,
        )

    return {
        "key": key,
        "label": _normalize_text(runtime_field.get("label") or field_detail.get("label")),
        "required": bool(runtime_field.get("required") if "required" in runtime_field else field_detail.get("required")),
        "protocol_value": value or None,
        "protocol_value_verified": bool(value),
        "option_count": len(options),
        "option_name": _normalize_text(matched.get("value_name")) if isinstance(matched, dict) else "",
        "field_shape_evidence": "live schema initial value" if value else "",
    }


def _resolve_schema_field_initial_value(schema_summary: dict[str, Any], key: str) -> dict[str, Any]:
    field_detail = _field_detail_by_key(schema_summary, key)
    if not isinstance(field_detail, dict):
        return {
            "key": key,
            "required": False,
            "protocol_value": None,
            "value_verified": False,
            "field_shape_evidence": "",
        }

    has_value_sample = "valueSample" in field_detail
    protocol_value = field_detail.get("valueSample") if has_value_sample else field_detail.get("value")
    return {
        "key": key,
        "required": bool(field_detail.get("required")),
        "protocol_value": protocol_value,
        "value_verified": has_value_sample or protocol_value is not None,
        "field_shape_evidence": "live schema initial value" if has_value_sample or protocol_value is not None else "",
    }


def _read_request_default_value(request_defaults: dict[str, Any] | None, key: str) -> dict[str, Any]:
    if not isinstance(request_defaults, dict) or key not in request_defaults:
        return {
            "key": key,
            "protocol_value": None,
            "value_verified": False,
            "field_shape_evidence": "",
        }
    return {
        "key": key,
        "protocol_value": request_defaults.get(key),
        "value_verified": True,
        "field_shape_evidence": "captured addWithSchema body sample",
    }


def _build_publish_control_plan(schema_summary: dict[str, Any]) -> tuple[dict[str, str], dict[str, Any], list[dict[str, str]]]:
    verified_patch: dict[str, str] = {}
    evidence: dict[str, Any] = {}
    blockers: list[dict[str, str]] = []
    control_keys = ("pickup_method", "start_sale_type", "product_type", "presell_type", "sale_channel_type")
    for key in control_keys:
        resolved = _resolve_publish_control_from_schema(schema_summary, key)
        evidence[key] = resolved
        if resolved["protocol_value_verified"]:
            verified_patch[key] = str(resolved["protocol_value"])
            continue
        if resolved["required"]:
            blockers.append({
                "field": key,
                "reason": "live schema 标记为必填，但当前没有可验证初始值或枚举值，必须通过真实提交样例确认，不能猜默认值",
            })
    return verified_patch, evidence, blockers


def _required_category_property_blockers(schema_summary: dict[str, Any], mapped_properties: dict[str, Any]) -> list[dict[str, str]]:
    blockers: list[dict[str, str]] = []
    for prop in schema_summary.get("categoryProperties") or []:
        if not isinstance(prop, dict) or not prop.get("required"):
            continue
        prop_id = _normalize_text(prop.get("id"))
        label = _normalize_text(prop.get("label") or prop.get("name"))
        if prop_id and prop_id in mapped_properties:
            continue
        blockers.append({
            "field": f"category_properties.{prop_id or label}",
            "reason": f"必填类目属性“{label or prop_id}”尚无明确业务来源或精确映射值，不能用固定兜底值掩盖",
        })
    return blockers


def _extract_freight_options(schema_summary: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[Any] = []

    runtime_probe = schema_summary.get("runtimeProbe")
    if isinstance(runtime_probe, dict):
        candidates.append(runtime_probe.get("optionPreview"))
        freight_field = runtime_probe.get("freightField")
        if isinstance(freight_field, dict):
            candidates.append(freight_field.get("optionPreview"))

    freight_summary = schema_summary.get("freight")
    if isinstance(freight_summary, dict):
        candidates.append(freight_summary.get("options"))

    for field in schema_summary.get("fieldDetails") or []:
        if isinstance(field, dict) and _normalize_text(field.get("key")) == "freight_id":
            candidates.append(field.get("optionPreview"))

    for key in ("freightOptions", "freight_options"):
        candidates.append(schema_summary.get(key))

    options: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for candidate in candidates:
        if not isinstance(candidate, list):
            continue
        for item in candidate:
            if not isinstance(item, dict):
                continue
            value_id = _normalize_text(item.get("value_id") or item.get("id") or item.get("value") or item.get("freight_id"))
            value_name = _normalize_text(item.get("value_name") or item.get("name") or item.get("label") or item.get("template_name"))
            if not value_id or not value_name:
                continue
            marker = (value_id, value_name)
            if marker in seen:
                continue
            seen.add(marker)
            options.append({
                "value_id": value_id,
                "value_name": value_name,
                "disabled": bool(item.get("disabled")),
            })
    return options


def _resolve_freight_template(schema_summary: dict[str, Any], template_name: str) -> dict[str, Any]:
    template_name = _normalize_text(template_name)
    options = _extract_freight_options(schema_summary)
    matched = next((item for item in options if _normalize_text(item.get("value_name")) == template_name), None)
    if not matched:
        return {
            "template_name": template_name,
            "protocol_value": None,
            "protocol_value_verified": False,
            "option_count": len(options),
        }
    if matched.get("disabled"):
        raise ProtocolDryRunError(f"运费模板不可用：{template_name}")
    return {
        "template_name": template_name,
        "protocol_value": matched["value_id"],
        "protocol_value_verified": True,
        "option_count": len(options),
        "field_shape_evidence": "freight_template_options_load",
    }


def merge_freight_probe_summary(schema_summary: dict[str, Any], freight_probe: dict[str, Any] | None) -> dict[str, Any]:
    if not freight_probe:
        return dict(schema_summary)
    merged = dict(schema_summary)
    if "freight" in freight_probe:
        merged["freight"] = freight_probe["freight"]
    if "runtimeProbe" in freight_probe:
        merged["runtimeProbe"] = freight_probe["runtimeProbe"]
    if "freightActions" in freight_probe:
        merged["freightActions"] = freight_probe["freightActions"]
    return merged


def merge_runtime_probe_summary(schema_summary: dict[str, Any], runtime_probe: dict[str, Any] | None) -> dict[str, Any]:
    if not runtime_probe:
        return dict(schema_summary)
    merged = dict(schema_summary)
    for key in ("freight", "publishControls", "requiredCategoryProperties", "specAxes", "skuColumns"):
        if key in runtime_probe:
            merged[key] = runtime_probe[key]
    if "categoryProperties" in runtime_probe and "categoryProperties" not in merged:
        merged["categoryProperties"] = runtime_probe["categoryProperties"]
    return merged


def _diagnose_local_files(snapshot: RecordDryRunSnapshot, assets: dict[str, Any] | None) -> list[dict[str, Any]]:
    diagnostics: list[dict[str, Any]] = []
    for sku in snapshot.sku_list:
        if not os.path.isfile(sku.local_path):
            diagnostics.append({
                "level": "warning",
                "field": f"sku[{sku.index}].path",
                "message": "本地 SKU 图片不存在，协议上传前必须修正",
                "path": sku.local_path,
            })

    for field_name, value in _media_local_assets(assets).items():
        values = value if isinstance(value, list) else [value]
        for local_path in values:
            if local_path and not os.path.isfile(str(local_path)):
                diagnostics.append({
                    "level": "warning",
                    "field": field_name,
                    "message": "本地素材不存在，协议上传前必须修正",
                    "path": str(local_path),
                })
    return diagnostics


def _candidate_protocol_value(value: Any) -> Any:
    if isinstance(value, dict) and "protocol_value" in value:
        return value.get("protocol_value")
    return value


def _candidate_local_source(value: Any) -> Any:
    if not isinstance(value, dict):
        return None
    if "local_files" in value:
        return value.get("local_files")
    if "local_file" in value:
        return value.get("local_file")
    return None


def _has_local_source(value: Any) -> bool:
    source = _candidate_local_source(value)
    if isinstance(source, list):
        return any(bool(_normalize_text(item)) for item in source)
    return bool(_normalize_text(source))


def _build_proposed_submit_model(
    verified_model_patch: dict[str, Any],
    candidate_model_patch: dict[str, Any],
) -> dict[str, Any]:
    model = dict(verified_model_patch)
    for field_name, value in candidate_model_patch.items():
        protocol_value = _candidate_protocol_value(value)
        if protocol_value is not None:
            model[field_name] = protocol_value
        elif field_name in ("spec_detail", "sku_detail"):
            model[field_name] = value
        else:
            model[field_name] = None
    return model


def _build_field_verification_report(
    *,
    verified_model_patch: dict[str, Any],
    candidate_model_patch: dict[str, Any],
    protocol_blockers: list[dict[str, str]],
) -> dict[str, Any]:
    blocked_fields = {_normalize_text(item.get("field")) for item in protocol_blockers if isinstance(item, dict)}
    verified_fields = [
        {
            "field": field_name,
            "status": "verified",
            "can_submit": True,
            "reason": "来自 live schema、业务记录或已验证映射，可进入拟提交模型",
        }
        for field_name in verified_model_patch
    ]

    missing_fields: list[dict[str, Any]] = []
    cannot_submit_fields: list[dict[str, Any]] = []
    for field_name, value in candidate_model_patch.items():
        protocol_value = _candidate_protocol_value(value)
        has_local_source = _has_local_source(value)
        if protocol_value is None and not has_local_source and field_name not in ("spec_detail", "sku_detail", "freight_id"):
            missing_fields.append({
                "field": field_name,
                "status": "missing",
                "can_submit": False,
                "reason": "本地商品没有提供该字段素材或值，且当前没有可验证协议值",
            })
            continue

        can_submit = bool(protocol_value is not None)
        if field_name == "freight_id" and isinstance(value, dict):
            can_submit = bool(value.get("protocol_value_verified"))
        if field_name in ("spec_detail", "sku_detail"):
            can_submit = False

        if can_submit:
            verified_fields.append({
                "field": field_name,
                "status": "verified",
                "can_submit": True,
                "reason": "已解析到可验证协议值，可进入拟提交模型；仍受完整 addWithSchema 截停样例总门禁约束",
            })
            continue

        cannot_submit_fields.append({
            "field": field_name,
            "status": "unverified" if field_name not in blocked_fields else "blocked",
            "can_submit": False,
            "reason": "已有候选来源，但缺少本地截停请求体或平台返回证据，不能进入真实提交",
        })

    return {
        "submit_ready": False,
        "verified_fields": verified_fields,
        "missing_fields": missing_fields,
        "cannot_submit_fields": cannot_submit_fields,
    }


def build_protocol_dry_run(
    *,
    schema_summary: dict[str, Any],
    record: Any,
    assets: dict[str, Any] | None = None,
    request_defaults: dict[str, Any] | None = None,
    materials: Iterable[tuple[str, int | float | str]] | None = None,
    tube_height_value: str = "",
    brand_value: str = "",
    gender_value: str = "",
    thickness_value: str = "",
) -> dict[str, Any]:
    snapshot = normalize_record_snapshot(record)
    _validate_record_schema_category_alignment(
        schema_summary=schema_summary,
        snapshot=snapshot,
        explicit_tube_height=_normalize_text(tube_height_value),
    )
    inferred_tube_height = tube_height_value or _infer_tube_height(schema_summary, snapshot)
    if not inferred_tube_height:
        raise ProtocolDryRunError("无法从 schema/记录推断筒高")
    resolved_brand_value = NO_BRAND_VALUE
    resolved_gender_value = _normalize_text(gender_value or _read_field(record, "gender") or _read_field(record, "sex"))
    if not resolved_gender_value:
        resolved_gender_value = _infer_gender_from_title(snapshot.title)
    resolved_thickness_value = _normalize_text(thickness_value)
    if not resolved_thickness_value:
        resolved_thickness_value = _infer_thickness_from_title(schema_summary, snapshot.title)

    try:
        attribute_plan = build_attribute_plan(
            schema_summary,
            tube_height_value=inferred_tube_height,
            materials=_default_materials(materials),
            brand_value=resolved_brand_value,
            gender_value=resolved_gender_value,
            thickness_value=resolved_thickness_value,
        )
    except SchemaMappingError as exc:
        raise ProtocolDryRunError(str(exc)) from exc

    goods_category = _schema_category(schema_summary)
    media_assets = _media_local_assets(assets)
    spec_detail_candidate = _build_spec_detail_candidate(schema_summary, snapshot.sku_list, inferred_tube_height)
    sku_detail_candidate = _build_sku_detail_candidate(snapshot.sku_list, spec_detail_candidate)
    freight_candidate = _resolve_freight_template(schema_summary, snapshot.shipping_template)
    publish_control_patch, publish_control_evidence, publish_control_blockers = _build_publish_control_plan(schema_summary)
    qualification_initial = _resolve_schema_field_initial_value(schema_summary, "qualification")
    request_default_keys = ("delivery_delay_day", "reduce_type", "reference_price_enable", "short_product_name")
    request_default_values = {
        key: _read_request_default_value(request_defaults, key)
        for key in request_default_keys
    }
    protocol_blockers = [
        {
            "field": "pic/main_image_three_to_four/white_background_pic/main_pic_video/description",
            "reason": "已通过 2026-05-04 本地截停样例+成功样本确认：5张主图先走 /product/img/batchupload，再触发 34智能裁剪、视频一键生成、白底检测，最终成功发出 addWithSchema。description 完整序列化格式为 HTML 含 <img> 标签；qualification 在此成功样本中为空{}。main_pic_video.resource_id 与 AI 视频任务的精确映射仍未闭环",
        },
        {
            "field": "spec_detail/sku_detail",
            "reason": "已通过真实 addWithSchema 截停样例确认 spec_detail 与 sku_detail 格式：sku_detail 每行含 id(平台生成 UUID 类串)/stock_info({stock_num:N})/sku_status:true/confirm_no_barcode:false/spec_detail_ids(平台生成数字串)/price(字符串)。dry_run 的格式已对齐真实 body（stock_info 嵌套、sku_status、confirm_no_barcode 均已补齐），但 spec_values[].id、sku_detail[].id、spec_detail_ids 均为 dry-run 占位值；真实 ID 由平台在规格填写阶段生成，无法离线构造，当前仍不能协议写入",
        },
        {
            "field": "category_properties.785.measure_info",
            "reason": "已通过 2026-05-04 deep submit-only 截停样例确认 785 item 级 measure_info 结构：template_id=873，values[] 含 module_id=1854(材质名) 与 module_id=1855(数值百分比, unit_id=15, unit_name=%)。进一步在编辑页对 editWithSchema 做 CDP 拦截 + python_http replay 时，baseline 与 swap_order 都只报“内容未修改”；sum_not_100/value_name_mismatch/material_name_mismatch，以及非 785 的 title_ascii_append/title_suffix_ascii_append/title_use_brand_name_true，都会优先触发 10001010A。继续补做 top_level_schema_last/schema_model_keys_sorted/property_785_item_keys_reordered 三个仅改 JSON 序列化形态、不改业务值的变体后，也同样触发 10001010A。说明当前命中的是编辑态协议改写风控，且敏感点不只在字段语义，还包含部分请求体原始形态；字段级 measure_info 后端校验规则仍未拆明",
        },
        {
            "field": "addWithSchema",
            "reason": "已通过 2026-05-04 本地截停样例确认 addWithSchema 的真实 query 参数与 body 顶层 envelope；但请求仍是被本地中止的安全样例，尚未证明未截停时可被平台接受，不能启用正式提交",
        },
    ]
    protocol_blockers.extend(_required_category_property_blockers(schema_summary, attribute_plan["category_properties"]))
    protocol_blockers.extend(publish_control_blockers)
    if not freight_candidate["protocol_value_verified"]:
        protocol_blockers.insert(
            2,
            {
                "field": "freight_id",
                "reason": "需要先运行运费模板探针，并精确匹配运费模板名称到 freight_id",
            },
        )

    verified_model_patch = {
        "title": snapshot.title,
        "goods_category": goods_category,
        "category_properties": attribute_plan["category_properties"],
        **publish_control_patch,
    }
    for key, resolved in request_default_values.items():
        if resolved["value_verified"]:
            verified_model_patch[key] = resolved["protocol_value"]
    candidate_model_patch = {
        "pic": {
            "local_files": media_assets["pic"],
            "field_shape": "array<{ url: string }>",
            "protocol_value": None,
        },
        "main_image_three_to_four": {
            "local_files": media_assets["main_image_three_to_four"],
            "field_shape": "array<{ url: string }>",
            "protocol_value": None,
        },
        "white_background_pic": {
            "local_file": media_assets["white_background_pic"],
            "field_shape": "array<{ url: string }>",
            "protocol_value": None,
        },
        "main_pic_video": {
            "local_file": media_assets["main_pic_video"],
            "field_shape": (
                "array<{ resource_id: string, video_choice?: number, "
                "video_source?: string, video_application_type?: enum }>"
            ),
            "protocol_value": None,
        },
        "description": {
            "local_files": media_assets["description_images"],
            "protocol_value": None,
        },
        "qualification": {
            "local_file": media_assets["qualification_image"],
            "field_shape": "record<string, unknown>",
            "protocol_value": qualification_initial["protocol_value"] if qualification_initial["value_verified"] else None,
            "field_shape_evidence": qualification_initial["field_shape_evidence"],
        },
        "spec_detail": spec_detail_candidate,
        "sku_detail": sku_detail_candidate,
        "freight_id": freight_candidate,
    }
    proposed_submit_model = _build_proposed_submit_model(verified_model_patch, candidate_model_patch)
    field_verification_report = _build_field_verification_report(
        verified_model_patch=verified_model_patch,
        candidate_model_patch=candidate_model_patch,
        protocol_blockers=protocol_blockers,
    )

    return {
        "mode": "dry_run",
        "submit_enabled": False,
        "record": snapshot.to_dict(),
        "verified_model_patch": verified_model_patch,
        "candidate_model_patch": candidate_model_patch,
        "proposed_submit_model": proposed_submit_model,
        "field_verification_report": field_verification_report,
        "evidence": {
            "attribute_plan": attribute_plan["evidence"],
            "publish_controls": publish_control_evidence,
            "schema_initial_values": {
                "qualification": qualification_initial,
            },
            "request_default_values": request_default_values,
            "image_upload": {
                "endpoint": "/product/img/batchupload",
                "single_form_field": "image",
                "batch_form_field": "image[index]",
                "extra": {"request_source": "pc"},
                "return_shape_verified": True,
                "return_shape": "code=0; data is an array of image URL strings",
                "evidence_files": [
                    "tmp_runtime_probe_live/fxg_upload_sample_single_verify.json",
                    "tmp_runtime_probe_live/fxg_upload_sample_batch_verify.json",
                ],
            },
            "material_type_constants": {
                "verified_by": "cdp_fxg_material_probe",
                "evidence_file": "tmp_runtime_probe_live/fxg_material_probe_v4.json",
                "source_module": "86908.M",
                "values": {
                    "main_pic_video": 0,
                    "white_background_pic": 1,
                    "long_pic": 4,
                    "pic": 9,
                    "main_image_three_to_four": 10,
                    "decorate_main_pic": 29,
                },
                "note": "已确认素材类型枚举来源；2026-05-04 受控主链成功样本中也未观察到 saveMaterial/materialDetail/batchApplyMaterial，且 main_pic_video 仍可进入 addWithSchema，说明 saveMaterial 至少不是当前样本的显式必经链，但素材 URL/AI 结果到最终字段的精确映射仍未拆明",
            },
            "white_image_flow": {
                "verified_by": "cdp_fxg_material_probe",
                "evidence_file": "tmp_runtime_probe_live/fxg_material_probe_v4.json",
                "source_module": "55060",
                "submitWhiteImg": {
                    "endpoint": "/product/tproduct/submitWhiteImg",
                    "request_shape": {
                        "name": "whiteImgUrl",
                        "product_id": "productId",
                        "action_list": "actionList",
                    },
                },
                "batchApprovalWhiteImgs": {
                    "endpoint": "/product/tproduct/batchApprovalWhiteImgs",
                    "request_shape": {"approval_materials": "approval material list"},
                },
                "latest_success_path_observation": {
                    "evidence_file": "2026-05-04 controlled upload task cd0d5944 + prior submit-only block sample",
                    "observed_quality_check_endpoint": "/common/img/IsWhiteBackgroundPic",
                    "observed_submit_endpoint": "/product/tproduct/addWithSchema",
                    "submitWhiteImg_seen": False,
                    "batchApprovalWhiteImgs_seen": False,
                    "task_status": "success",
                },
                "unresolved": [
                    "submitWhiteImg.action_list concrete values",
                    (
                        "current successful sample shows white_background_pic entered "
                        "addWithSchema after batchupload + IsWhiteBackgroundPic, without observed "
                        "submitWhiteImg/batchApprovalWhiteImgs; still need more samples to decide "
                        "whether those endpoints belong to an optional audit path or only appear "
                        "under different page operations"
                    ),
                ],
            },
            "measure_property_785_capture": {
                "verified_by": "submit-only deep capture",
                "evidence_file": "tmp_runtime_probe_live/fxg_protocol_submit_only_deep_9222_2026-05-04_09-55-56.json",
                "path": "schema.model.category_properties.value['785'][*]",
                "item_shape": {
                    "measure_info.template_id": 873,
                    "measure_info.values": [
                        {
                            "module_id": 1854,
                            "meaning": "material name",
                        },
                        {
                            "module_id": 1855,
                            "meaning": "percentage value",
                            "unit_id": 15,
                            "unit_name": "%",
                        },
                    ],
                    "value_id": "",
                    "value_name_examples": ["棉75%", "氨纶25%"],
                },
                "note": "当前真实样例确认 measure_info 位于 785 item 级别，不在外层 additions；样例类目为中筒袜",
            },
            "white_image_component": {
                "verified_by": "cdp_fxg_material_probe",
                "evidence_file": "tmp_runtime_probe_live/fxg_material_probe_v4.json",
                "source_module": "9559",
                "chunk": "goods-components-MaterialImg",
                "form_key": ["white_background_pic"],
                "value_mapping": "url string array -> array<{ url: string }>",
                "aspect_validation": {
                    "source_module": "12274",
                    "export": "QG",
                },
                "quality_check": {
                    "source_module": "71532",
                    "endpoint": "/common/img/IsWhiteBackgroundPic",
                    "request_shape": {
                        "url": "image url list or value from MaterialImg validator",
                        "high_quality_check": True,
                        "shop_id": "current shop id",
                        "product_id": "product id",
                        "product_name": "product title",
                    },
                },
                "unresolved": [
                    "MaterialImg confirms component value mapping, not the accepted final addWithSchema request",
                    "submitWhiteImg.action_list concrete values were not found in MaterialImg chunk",
                ],
            },
            "white_image_deep_scan": {
                "verified_by": "cdp_fxg_material_probe",
                "evidence_file": "tmp_runtime_probe_live/fxg_material_probe_v4.json",
                "related_chunk_count": 76,
                "loaded_chunk_count": 76,
                "failed_chunk_count": 0,
                "result": (
                    "submitWhiteImg/action_list still only appeared in wrapper module 55060 "
                    "after related async chunks were loaded"
                ),
            },
            "submit_model_field_shapes": {
                "verified_by": "cdp_fxg_submit_probe",
                "evidence_file": "tmp_runtime_probe_live/fxg_submit_probe_v4.json",
                "source_module": "90665",
                "fields": {
                    "pic": "array<{ url: string }>",
                    "main_image_three_to_four": "array<{ url: string }>",
                    "long_pic": "array<{ url: string }>",
                    "white_background_pic": "array<{ url: string }>",
                    "description": "string",
                    "main_pic_video": (
                        "array<{ resource_id: string, video_choice?: number, "
                        "video_source?: string, video_application_type?: enum }>"
                    ),
                    "qualification": "record<string, unknown>",
                },
                "note": "字段形状来自前端提交 schema，并已被 2026-05-04 addWithSchema 截停样例再次侧证；但样例内容经过去敏与截断，仍不能替代完整协议闭环",
            },
            "submit_envelope": {
                "verified_by": "cdp_fxg_submit_probe + submit-preflight capture",
                "evidence_file": [
                    "tmp_runtime_probe_live/fxg_submit_probe_v4.json",
                    "tmp_runtime_probe_live/fxg_protocol_submit_only_block_9222_2026-05-04_08-51-48.json",
                ],
                "source_module": "51313",
                "addWithSchema": {
                    "endpoint": "/product/tproduct/addWithSchema?check_status=<check_status>",
                    "verified_query_keys": [
                        "check_status",
                        "appid",
                        "__token",
                        "_bid",
                        "_lid",
                        "verifyFp",
                        "fp",
                        "msToken",
                        "a_bogus",
                    ],
                    "body_merge_order": [
                        "{ schema: model }",
                        "{ category_id, context: { ...schema.context, gray_components: undefined } }",
                        "{ pass_through_extra, optional recruit_info }",
                        "submit options object containing check_status",
                    ],
                    "captured_model_keys": [
                        "sku_detail",
                        "spec_detail",
                        "white_background_pic",
                        "title",
                        "pic",
                        "category_properties",
                        "description",
                        "goods_category",
                        "main_image_three_to_four",
                        "main_pic_video",
                        "qualification",
                    "category_properties.785.measure_info",
                    ],
                },
                "note": "已确认前端封装形状，并已通过本地截停拿到真实 addWithSchema 请求摘要；但该样例被安全中止且正文存在去敏/截断，仍未证明完整提交可被平台接受",
            },
            "schema_model_key_count": schema_summary.get("modelKeyCount"),
            "schema_category": schema_summary.get("category"),
            "schema_field_details": _field_detail_map(schema_summary),
            "freight_template": {
                "matched": freight_candidate["protocol_value_verified"],
                "option_count": freight_candidate["option_count"],
            },
        },
        "protocol_blockers": protocol_blockers,
        "diagnostics": _diagnose_local_files(snapshot, assets),
    }

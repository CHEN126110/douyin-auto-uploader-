from __future__ import annotations

import copy
from typing import Any, Callable


def normalize_text(value: Any) -> str:
    return str(value or "").strip()


def extract_submit_body(capture: dict[str, Any]) -> dict[str, Any]:
    requests = capture.get("requests")
    if not isinstance(requests, list):
        raise ValueError("capture.requests 不是数组")
    for request in requests:
        if not isinstance(request, dict):
            continue
        url = request.get("url") if isinstance(request.get("url"), dict) else {}
        path = normalize_text(url.get("path") or url.get("sanitized"))
        if "/product/tproduct/addWithSchema" not in path and "/product/tproduct/editWithSchema" not in path:
            continue
        post_data = request.get("postData") if isinstance(request.get("postData"), dict) else {}
        value = post_data.get("value")
        if isinstance(value, dict):
            return copy.deepcopy(value)
    raise ValueError("未在 capture 中找到 addWithSchema/editWithSchema 的 JSON 请求体")


def schema_model(body: dict[str, Any]) -> dict[str, Any]:
    schema = body.get("schema")
    if not isinstance(schema, dict):
        raise ValueError("请求体缺少 schema")
    model = schema.get("model")
    if isinstance(model, dict):
        return model
    return schema


def property_785_items(model: dict[str, Any]) -> list[dict[str, Any]]:
    category_properties = model.get("category_properties") if isinstance(model.get("category_properties"), dict) else {}
    value = category_properties.get("value") if isinstance(category_properties.get("value"), dict) else {}
    items = value.get("785")
    if not isinstance(items, list):
        raise ValueError("请求体缺少 category_properties.value['785']")
    normalized: list[dict[str, Any]] = []
    for item in items:
        if isinstance(item, dict):
            normalized.append(item)
    if not normalized:
        raise ValueError("category_properties.value['785'] 为空")
    return normalized


def measure_info_summary(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summary: list[dict[str, Any]] = []
    for item in items:
        measure_info = item.get("measure_info") if isinstance(item.get("measure_info"), dict) else {}
        values = measure_info.get("values") if isinstance(measure_info.get("values"), list) else []
        summary.append(
            {
                "value_id": item.get("value_id"),
                "value_name": item.get("value_name"),
                "template_id": measure_info.get("template_id"),
                "values": [
                    {
                        "module_id": value.get("module_id"),
                        "value": value.get("value"),
                        "unit_id": value.get("unit_id"),
                        "unit_name": value.get("unit_name"),
                    }
                    for value in values
                    if isinstance(value, dict)
                ],
            }
        )
    return summary


def _ensure_second_item(items: list[dict[str, Any]]) -> dict[str, Any]:
    if len(items) < 2:
        raise ValueError("785 item 数量不足 2，无法构造当前变体")
    return items[1]


def _set_item_percent(item: dict[str, Any], percent: str) -> None:
    measure_info = item.get("measure_info") if isinstance(item.get("measure_info"), dict) else {}
    values = measure_info.get("values") if isinstance(measure_info.get("values"), list) else []
    for value in values:
        if isinstance(value, dict) and value.get("module_id") == 1855:
            value["value"] = str(percent)
            return
    raise ValueError("785 item 缺少 module_id=1855 的百分比模块")


def _set_item_material(item: dict[str, Any], material_name: str) -> None:
    measure_info = item.get("measure_info") if isinstance(item.get("measure_info"), dict) else {}
    values = measure_info.get("values") if isinstance(measure_info.get("values"), list) else []
    for value in values:
        if isinstance(value, dict) and value.get("module_id") == 1854:
            value["value"] = str(material_name)
            return
    raise ValueError("785 item 缺少 module_id=1854 的材质模块")


def _set_title_value(body: dict[str, Any], suffix: str) -> None:
    model = schema_model(body)
    title = model.get("title")
    if not isinstance(title, dict):
        raise ValueError("请求体缺少 title 字段")
    current_value = str(title.get("value") or "")
    title["value"] = f"{current_value}{suffix}"


def _set_model_field_value(body: dict[str, Any], field_name: str, new_value: Any) -> None:
    model = schema_model(body)
    field = model.get(field_name)
    if not isinstance(field, dict):
        raise ValueError(f"请求体缺少 {field_name} 字段")
    field["value"] = new_value


def _move_dict_key_to_end(mapping: dict[str, Any], key_name: str) -> None:
    if key_name not in mapping:
        raise ValueError(f"请求体缺少 {key_name} 字段")
    value = mapping.pop(key_name)
    mapping[key_name] = value


def _replace_dict_in_order(mapping: dict[str, Any], ordered_pairs: list[tuple[str, Any]]) -> None:
    mapping.clear()
    mapping.update(ordered_pairs)


def _deep_sort_mapping_keys(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _deep_sort_mapping_keys(value[key])
            for key in sorted(value.keys(), key=lambda item: str(item))
        }
    if isinstance(value, list):
        return [_deep_sort_mapping_keys(item) for item in value]
    return value


def _sort_model_keys(body: dict[str, Any]) -> None:
    model = schema_model(body)
    sorted_model = _deep_sort_mapping_keys(model)
    if not isinstance(sorted_model, dict):
        raise ValueError("排序后的 model 不是对象")
    _replace_dict_in_order(model, list(sorted_model.items()))


def _reorder_785_item_keys(items: list[dict[str, Any]]) -> None:
    for item in items:
        ordered_pairs: list[tuple[str, Any]] = []
        seen: set[str] = set()
        for key_name in ("measure_info", "value_name", "value_id", "tags", "diy_type"):
            if key_name in item:
                ordered_pairs.append((key_name, item[key_name]))
                seen.add(key_name)
        for key_name, value in item.items():
            if key_name in seen:
                continue
            ordered_pairs.append((key_name, value))
        _replace_dict_in_order(item, ordered_pairs)


def _variant_definitions() -> list[tuple[str, str, str, Callable[[dict[str, Any], list[dict[str, Any]]], None]]]:
    return [
        ("baseline", "semantic_control", "原始样例，不做修改", lambda body, items: None),
        (
            "sum_not_100",
            "business_semantic_change",
            "将第二项百分比改为 20，测试百分比合计不为 100 的后续行为",
            lambda body, items: _set_item_percent(_ensure_second_item(items), "20"),
        ),
        (
            "value_name_mismatch",
            "business_semantic_change",
            "只改第二项的 value_name，不同步 measure_info，制造 value_name 与 measure_info 不一致",
            lambda body, items: _ensure_second_item(items).__setitem__("value_name", "氨纶20%"),
        ),
        (
            "material_name_mismatch",
            "business_semantic_change",
            "只改第二项 measure_info 材质名，不同步 value_name，制造材质名不一致",
            lambda body, items: _set_item_material(_ensure_second_item(items), "锦纶"),
        ),
        (
            "swap_order",
            "serialization_shape_only",
            "交换 785 两个 item 的顺序，观察后续是否存在顺序依赖",
            lambda body, items: items.reverse(),
        ),
        (
            "title_ascii_append",
            "business_semantic_change",
            "只在标题末尾追加 ASCII 后缀 A，验证非 785 语义改动是否也会触发同类风控",
            lambda body, items: _set_title_value(body, "A"),
        ),
        (
            "title_suffix_ascii_append",
            "business_semantic_change",
            "只在 title_suffix 中追加 ASCII 字符 A，验证标题附加位的小改动是否会触发风控",
            lambda body, items: _set_model_field_value(body, "title_suffix", "A"),
        ),
        (
            "title_use_brand_name_true",
            "business_semantic_change",
            "仅将 title_use_brand_name 从 false 改为 true，验证标题布尔位改动是否会触发风控",
            lambda body, items: _set_model_field_value(body, "title_use_brand_name", True),
        ),
        (
            "top_level_schema_last",
            "serialization_shape_only",
            "仅把顶层 schema 键移动到请求体末尾，验证顶层 JSON 键顺序是否影响编辑态 replay",
            lambda body, items: _move_dict_key_to_end(body, "schema"),
        ),
        (
            "schema_model_keys_sorted",
            "serialization_shape_only",
            "仅对 schema.model 内所有对象键做递归排序，验证语义不变的 JSON 键顺序是否仍会触发差异响应",
            lambda body, items: _sort_model_keys(body),
        ),
        (
            "property_785_item_keys_reordered",
            "serialization_shape_only",
            "仅重排 785 item 内 measure_info/value_name/value_id 等键的序列化顺序，不改任何业务值",
            lambda body, items: _reorder_785_item_keys(items),
        ),
    ]


def available_variant_names() -> list[str]:
    return [name for name, _, _, _ in _variant_definitions()]


def build_named_variant(body: dict[str, Any], name: str) -> dict[str, Any]:
    normalized_name = normalize_text(name)
    for variant_name, mutation_scope, description, mutator in _variant_definitions():
        if variant_name != normalized_name:
            continue
        variant_body = copy.deepcopy(body)
        items = property_785_items(schema_model(variant_body))
        mutator(variant_body, items)
        return {
            "name": variant_name,
            "mutation_scope": mutation_scope,
            "description": description,
            "property_785": measure_info_summary(items),
            "request_body": variant_body,
        }
    raise ValueError(f"不支持的变体: {name}")


def build_measure_info_variants_from_body(body: dict[str, Any]) -> dict[str, Any]:
    variants = [build_named_variant(body, name) for name in available_variant_names()]
    return {
        "mode": "measure_info_variants",
        "variant_count": len(variants),
        "variants": variants,
        "note": "该文件只用于离线审计和后续受控 live 实验准备，不会直接发送到平台",
    }


def build_measure_info_variants(capture: dict[str, Any]) -> dict[str, Any]:
    result = build_measure_info_variants_from_body(extract_submit_body(capture))
    result["source_capture_profile"] = capture.get("captureProfile")
    result["source_target"] = capture.get("target")
    return result

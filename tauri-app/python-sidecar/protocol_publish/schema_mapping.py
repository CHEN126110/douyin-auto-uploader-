from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable

NO_BRAND_VALUE = "无品牌"


class SchemaMappingError(ValueError):
    """Raised when a protocol schema field cannot be mapped exactly."""


@dataclass(slots=True)
class EnumPropertyValue:
    property_id: str
    property_label: str
    value_id: str
    value_name: str

    def to_protocol_value(self) -> dict[str, Any]:
        return {
            "diy_type": 0,
            "measure_info": None,
            "tags": None,
            "value_id": self.value_id,
            "value_name": self.value_name,
        }


@dataclass(slots=True)
class MaterialMeasureValue:
    material: str
    percentage: str
    property_id: str
    schema_value_id: str
    template_id: int
    material_module_id: int
    percentage_module_id: int
    percentage_unit_id: int
    percentage_unit_name: str = "%"

    def to_protocol_value(self) -> dict[str, Any]:
        # The schema stores the selected material in measure_info; captured FXG
        # requests keep the top-level property value id empty for this field.
        return {
            "value_id": "",
            "value_name": f"{self.material}{self.percentage}%",
            "measure_info": {
                "template_id": self.template_id,
                "values": [
                    {
                        "module_id": self.material_module_id,
                        "prefix": "",
                        "suffix": "",
                        "value": self.material,
                    },
                    {
                        "module_id": self.percentage_module_id,
                        "prefix": "",
                        "suffix": "",
                        "value": self.percentage,
                        "unit_id": self.percentage_unit_id,
                        "unit_name": self.percentage_unit_name,
                    },
                ],
            },
        }


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def get_category_properties(schema_summary: dict[str, Any]) -> list[dict[str, Any]]:
    properties = schema_summary.get("categoryProperties")
    if isinstance(properties, list):
        return [item for item in properties if isinstance(item, dict)]

    model = schema_summary.get("model")
    if isinstance(model, dict):
        items = model.get("category_properties", {}).get("items")
        return [item for item in _as_list(items) if isinstance(item, dict)]

    return []


def find_category_property(schema_summary: dict[str, Any], *, property_id: str = "", label: str = "") -> dict[str, Any]:
    property_id = _normalize_text(property_id)
    label = _normalize_text(label)
    for item in get_category_properties(schema_summary):
        if property_id and _normalize_text(item.get("id")) == property_id:
            return item
        if label and _normalize_text(item.get("label") or item.get("name")) == label:
            return item
    target = property_id or label
    raise SchemaMappingError(f"未找到类目属性：{target}")


def _iter_option_matches(property_item: dict[str, Any]) -> Iterable[dict[str, Any]]:
    matches = property_item.get("optionMatches")
    if isinstance(matches, list):
        yielded = False
        for item in matches:
            if isinstance(item, dict):
                yielded = True
                yield item
        if yielded:
            return

    for key in ("optionPreview", "options", "values", "value_options", "select_options"):
        for item in _as_list(property_item.get(key)):
            if isinstance(item, dict):
                yield {
                    "value_id": item.get("value_id") or item.get("id") or item.get("value"),
                    "value_name": item.get("value_name") or item.get("name") or item.get("label"),
                    "matchType": "raw",
                }


def find_exact_option(property_item: dict[str, Any], value_name: str) -> dict[str, Any]:
    expected = _normalize_text(value_name)
    for item in _iter_option_matches(property_item):
        if _normalize_text(item.get("value_name")) == expected:
            if item.get("matchType") not in ("exact", "raw", None):
                raise SchemaMappingError(f"属性 {property_item.get('label')} 的值 {expected} 不是精确匹配")
            return item
    raise SchemaMappingError(f"属性 {property_item.get('label')} 未找到精确值：{expected}")


def map_enum_property(schema_summary: dict[str, Any], *, property_id: str = "", label: str = "", value_name: str) -> EnumPropertyValue:
    prop = find_category_property(schema_summary, property_id=property_id, label=label)
    option = find_exact_option(prop, value_name)
    return EnumPropertyValue(
        property_id=_normalize_text(prop.get("id")),
        property_label=_normalize_text(prop.get("label") or prop.get("name")),
        value_id=_normalize_text(option.get("value_id")),
        value_name=_normalize_text(option.get("value_name")),
    )


def infer_enum_property_from_text(
    schema_summary: dict[str, Any],
    *,
    property_id: str = "",
    label: str = "",
    text: str,
) -> EnumPropertyValue | None:
    prop = find_category_property(schema_summary, property_id=property_id, label=label)
    source_text = _normalize_text(text)
    if not source_text:
        return None

    matched: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in _iter_option_matches(prop):
        keyword = _normalize_text(item.get("keyword"))
        if not keyword or keyword not in source_text:
            continue
        match_type = item.get("matchType")
        if match_type not in ("exact", "raw", None):
            continue
        value_id = _normalize_text(item.get("value_id"))
        value_name = _normalize_text(item.get("value_name"))
        dedupe_key = (value_id, value_name)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        matched.append(item)

    if not matched:
        return None
    if len(matched) > 1:
        raise SchemaMappingError(
            f"属性 {prop.get('label') or prop.get('name') or property_id} 在文本中命中多个 schema keyword，无法安全推断"
        )

    option = matched[0]
    return EnumPropertyValue(
        property_id=_normalize_text(prop.get("id")),
        property_label=_normalize_text(prop.get("label") or prop.get("name")),
        value_id=_normalize_text(option.get("value_id")),
        value_name=_normalize_text(option.get("value_name")),
    )


def _pick_material_template(property_item: dict[str, Any]) -> tuple[int, int, int, int]:
    templates = _as_list(property_item.get("measureTemplates"))
    if not templates:
        additions = property_item.get("additions") if isinstance(property_item.get("additions"), dict) else {}
        templates = _as_list(additions.get("measure_templates"))

    for template in templates:
        if not isinstance(template, dict):
            continue
        template_id = template.get("template_id")
        modules = _as_list(template.get("modules") or template.get("value_modules"))
        material_module = next((item for item in modules if item.get("input_type") == "enum_diy"), None)
        percentage_module = next((item for item in modules if item.get("input_type") == "input"), None)
        if template_id and material_module and percentage_module:
            unit_options = _as_list(percentage_module.get("unitOptions") or percentage_module.get("unit_options"))
            percent_unit = next((item for item in unit_options if item.get("label") == "%"), None)
            if not percent_unit:
                raise SchemaMappingError("面料材质模板缺少 % 单位")
            return (
                int(template_id),
                int(material_module["module_id"]),
                int(percentage_module["module_id"]),
                int(percent_unit["value"]),
            )
    raise SchemaMappingError("面料材质模板缺少可用的材质/百分比模块")


def map_material_values(
    schema_summary: dict[str, Any],
    materials: Iterable[tuple[str, int | float | str]],
) -> list[MaterialMeasureValue]:
    prop = find_category_property(schema_summary, label="面料材质")
    template_id, material_module_id, percentage_module_id, percentage_unit_id = _pick_material_template(prop)

    mapped: list[MaterialMeasureValue] = []
    total = 0.0
    for material, percentage in materials:
        material_name = _normalize_text(material)
        percentage_text = _normalize_text(percentage)
        if not material_name or not percentage_text:
            raise SchemaMappingError("面料材质和百分比不能为空")
        total += float(percentage_text)
        option = find_exact_option(prop, material_name)
        mapped.append(
            MaterialMeasureValue(
                material=material_name,
                percentage=percentage_text,
                property_id=_normalize_text(prop.get("id")),
                schema_value_id=_normalize_text(option.get("value_id")),
                template_id=template_id,
                material_module_id=material_module_id,
                percentage_module_id=percentage_module_id,
                percentage_unit_id=percentage_unit_id,
            )
        )

    if round(total, 2) != 100.0:
        raise SchemaMappingError(f"面料材质含量总和必须为 100，当前为 {total:g}")
    return mapped


def build_attribute_plan(
    schema_summary: dict[str, Any],
    *,
    tube_height_value: str,
    materials: Iterable[tuple[str, int | float | str]],
    brand_value: str = "",
    gender_value: str = "",
    thickness_value: str = "",
) -> dict[str, Any]:
    tube_height = map_enum_property(schema_summary, label="筒高", value_name=tube_height_value)
    mapped_materials = map_material_values(schema_summary, materials)
    material_property_id = mapped_materials[0].property_id if mapped_materials else ""
    mapped_brand = map_enum_property(schema_summary, label="品牌", value_name=NO_BRAND_VALUE)
    mapped_gender = map_enum_property(schema_summary, label="适用性别", value_name=gender_value) if _normalize_text(gender_value) else None
    mapped_thickness = map_enum_property(schema_summary, label="厚度", value_name=thickness_value) if _normalize_text(thickness_value) else None

    category_properties = {
        tube_height.property_id: [tube_height.to_protocol_value()],
        material_property_id: [item.to_protocol_value() for item in mapped_materials],
    }
    if mapped_brand:
        category_properties[mapped_brand.property_id] = [mapped_brand.to_protocol_value()]
    if mapped_gender:
        category_properties[mapped_gender.property_id] = [mapped_gender.to_protocol_value()]
    if mapped_thickness:
        category_properties[mapped_thickness.property_id] = [mapped_thickness.to_protocol_value()]

    return {
        "category_properties": category_properties,
        "evidence": {
            "tube_height": asdict(tube_height),
            "materials": [asdict(item) for item in mapped_materials],
            "brand": asdict(mapped_brand),
            "brand_policy": {
                "mode": "forced_no_brand",
                "forced_value": NO_BRAND_VALUE,
                "ignored_input": _normalize_text(brand_value),
            },
            "gender": asdict(mapped_gender) if mapped_gender else None,
            "thickness": asdict(mapped_thickness) if mapped_thickness else None,
        },
    }


def build_long_sock_attribute_plan(schema_summary: dict[str, Any]) -> dict[str, Any]:
    return build_attribute_plan(
        schema_summary,
        tube_height_value="长筒袜",
        materials=[("棉", 75), ("氨纶", 25)],
    )

# -*- coding: utf-8 -*-

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PYTHON_SIDECAR_ROOT = PROJECT_ROOT / "tauri-app" / "python-sidecar"
for path in (PROJECT_ROOT, PYTHON_SIDECAR_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from protocol_publish.dry_run import build_protocol_dry_run  # noqa: E402
from protocol_publish.schema_mapping import build_attribute_plan  # noqa: E402


def _option(value_id: str, value_name: str, keyword: str = "") -> dict[str, str]:
    item = {
        "value_id": value_id,
        "value_name": value_name,
        "matchType": "exact",
    }
    if keyword:
        item["keyword"] = keyword
    return item


def _sock_schema() -> dict[str, Any]:
    return {
        "category": {
            "third_cid": 123,
            "third_name": "中筒袜",
        },
        "categoryProperties": [
            {
                "id": "1865",
                "label": "筒高",
                "required": True,
                "optionMatches": [_option("31904", "中筒袜")],
            },
            {
                "id": "785",
                "label": "面料材质",
                "required": True,
                "optionMatches": [
                    _option("cotton", "棉"),
                    _option("spandex", "氨纶"),
                ],
                "measureTemplates": [
                    {
                        "template_id": 873,
                        "modules": [
                            {"input_type": "enum_diy", "module_id": 1854},
                            {
                                "input_type": "input",
                                "module_id": 1855,
                                "unitOptions": [{"label": "%", "value": 15}],
                            },
                        ],
                    }
                ],
            },
            {
                "id": "1687",
                "label": "品牌",
                "required": True,
                "optionMatches": [
                    _option("596120136", "无品牌"),
                    _option("songmu", "songmu淞木"),
                ],
            },
            {
                "id": "1577",
                "label": "适用性别",
                "required": False,
                "optionMatches": [
                    _option("1991", "通用"),
                    _option("female", "女"),
                    _option("male", "男"),
                ],
            },
            {
                "id": "thickness",
                "label": "厚度",
                "required": False,
                "optionMatches": [_option("thin", "薄款", "薄款")],
            },
        ],
    }


class ProtocolNoBrandPolicyTest(unittest.TestCase):
    def test_attribute_plan_forces_no_brand_even_when_specific_brand_is_provided(self) -> None:
        plan = build_attribute_plan(
            _sock_schema(),
            tube_height_value="中筒袜",
            materials=[("棉", 75), ("氨纶", 25)],
            brand_value="songmu淞木",
            gender_value="女",
        )

        brand = plan["evidence"]["brand"]
        self.assertEqual(brand["property_id"], "1687")
        self.assertEqual(brand["value_id"], "596120136")
        self.assertEqual(brand["value_name"], "无品牌")
        self.assertEqual(
            plan["category_properties"]["1687"][0],
            {
                "diy_type": 0,
                "measure_info": None,
                "tags": None,
                "value_id": "596120136",
                "value_name": "无品牌",
            },
        )

    def test_protocol_dry_run_ignores_record_brand_field(self) -> None:
        dry_run = build_protocol_dry_run(
            schema_summary=_sock_schema(),
            record={
                "id": 1,
                "name": "ID-1",
                "title": "songmu淞木 布标薄款中筒袜女",
                "path": "E:/missing/product",
                "clazz": "2",
                "repo": 2,
                "brand": "songmu淞木",
                "brand_name": "songmu淞木",
                "content": [
                    {
                        "name": "黑色/均码",
                        "path": "E:/missing/product/sku.jpg",
                        "price": "9.9",
                    }
                ],
            },
        )

        brand = dry_run["evidence"]["attribute_plan"]["brand"]
        self.assertEqual(brand["value_id"], "596120136")
        self.assertEqual(brand["value_name"], "无品牌")
        self.assertEqual(dry_run["verified_model_patch"]["category_properties"]["1687"][0]["value_name"], "无品牌")


if __name__ == "__main__":
    unittest.main()

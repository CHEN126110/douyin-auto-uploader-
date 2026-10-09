# -*- coding: utf-8 -*-
"""SKU 输入的自洽性：**矛盾输入必须报阻塞，不许猜一个默认值让它跑通**。

实测（`scripts/probe-empty-spec-values.py` 修之前）：

| 用例 | 修之前 | 危害 |
|---|---|---|
| 两条 SKU 全空 ``spec_values`` | ``ok=True``、0 阻塞 | 规格表建不出来 |
| 两条 SKU 规格值完全相同 | ``ok=True``、0 阻塞 | **操作人说 2 个、流水线只建 1 行** |
| 一条空、一条正常 | ``ok=True``、0 阻塞 | 属性集不一致，拼不出表 |

第二条是最典型的「静默产出错误结果」——
`_desired_specs()` 把两条塌成 1 个值，而没有任何一处提示。

红线：「字段没有实证证据时必须显式记录为 blocker，不允许猜一个默认值让它跑通」。
"""

from __future__ import annotations

import pathlib
import sys
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SUBPROJECT = REPO_ROOT / "taobao-publisher"
if str(SUBPROJECT) not in sys.path:
    sys.path.insert(0, str(SUBPROJECT))

from taobao_publish.mapping import build_publish_item  # noqa: E402
from taobao_publish.models import LocalProduct  # noqa: E402


def build(skus):
    local = LocalProduct(record_id=1, record_name="ID-1", title="本地标题",
                         main_images=["a.jpg"], detail_images=[])
    return build_publish_item(local, {"title": "标题", "skus": skus})


def fields_of(outcome):
    return [b.field for b in outcome.blockers]


class SkuSelfConsistencyTest(unittest.TestCase):
    def test_all_empty_spec_values_is_a_blocker(self) -> None:
        out = build([
            {"spec_values": {}, "price": 16.8, "stock": 100},
            {"spec_values": {}, "price": 16.8, "stock": 100},
        ])
        self.assertFalse(out.ok)
        self.assertTrue(any("spec_values" in f for f in fields_of(out)))

    def test_duplicate_spec_values_is_a_blocker(self) -> None:
        """**两条 SKU 塌成一条**——最典型的静默丢数据。"""

        out = build([
            {"spec_values": {"尺码": "M(37-41)"}, "price": 16.8, "stock": 100},
            {"spec_values": {"尺码": "M(37-41)"}, "price": 16.8, "stock": 100},
        ])
        self.assertFalse(out.ok)
        detail = " ".join(b.detail for b in out.blockers)
        self.assertIn("静默少建一行", detail)

    def test_mixed_empty_and_filled_is_a_blocker(self) -> None:
        out = build([
            {"spec_values": {}, "price": 16.8, "stock": 100},
            {"spec_values": {"尺码": "M(37-41)"}, "price": 16.8, "stock": 100},
        ])
        self.assertFalse(out.ok)

    def test_inconsistent_attribute_names_is_a_blocker(self) -> None:
        """属性名不一致就拼不出一张统一的规格表。"""

        out = build([
            {"spec_values": {"尺码": "M(37-41)"}, "price": 16.8, "stock": 100},
            {"spec_values": {"颜色": "黑色"}, "price": 16.8, "stock": 100},
        ])
        self.assertFalse(out.ok)
        self.assertTrue(any(b.field == "skus" for b in out.blockers))

    def test_well_formed_skus_still_pass(self) -> None:
        """正常输入**不能**被这些校验误伤。"""

        out = build([
            {"spec_values": {"尺码": "M(37-41)"}, "price": 16.8, "stock": 100},
            {"spec_values": {"尺码": "L（45-47）"}, "price": 16.8, "stock": 100},
        ])
        self.assertTrue(out.ok, "正常 SKU 被误报阻塞：{}".format(fields_of(out)))
        self.assertEqual(len(out.item.skus), 2)

    def test_single_sku_without_spec_values_is_allowed(self) -> None:
        """单 SKU 无规格是合法场景（平台允许不分规格）。"""

        out = build([{"spec_values": {}, "price": 16.8, "stock": 100}])
        self.assertTrue(out.ok, "单 SKU 无规格不该被拦：{}".format(fields_of(out)))

    def test_blockers_explain_what_to_fix(self) -> None:
        """阻塞文案要能让人知道**该改什么**，不能只说「无效」。"""

        out = build([
            {"spec_values": {"尺码": "M(37-41)"}, "price": 16.8, "stock": 100},
            {"spec_values": {"尺码": "M(37-41)"}, "price": 16.8, "stock": 100},
        ])
        detail = out.blockers[0].detail
        self.assertIn("第 1 条与第 2 条", detail, "要点明是哪两条")
        self.assertIn("尺码=M(37-41)", detail, "要点明是哪组规格值")


if __name__ == "__main__":
    unittest.main()

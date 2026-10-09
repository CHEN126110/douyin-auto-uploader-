# -*- coding: utf-8 -*-
"""`readback` 的分派：**真实页面上的只读实机验证**，以及一个实机发现的边界。

## 实机验证（2026-10-03，只读）

逐个 kind 在真实发布页上跑 `_read_expected_value`：

```
宝贝标题     kind=text               -> ''
导购标题     kind=text               -> ''      ← 第 38 轮加的字段，读取器可用
一口价      kind=text               -> ''
总库存      kind=text               -> '1'     ← UI 预填的默认值
主图张数     kind=main_image_count   -> '0'
SKU 行数    kind=sku_row_count      -> '0'
运费模板     kind=freight_template   -> '极兔快递'
```

七条路径全部跑通，取值都合理。这是第 33 轮那次扩展（4 项 → 7 项）的实机复核。

## 实机发现的边界

**`read_sku_table` 在没有表格时根本不返回 `rowCount` 键**：

```js
if (!tables.length) {
  return { found: true, drawerOpen: open, tableCount: 0, wrapperText: ... };
  //                      ↑ 没有 rowCount
}
```

于是 `table.get("rowCount")` 是 `None`——我的代码写了 `or 0` 兜住，
但这属于**碰巧对了**：换个写法（例如 `int(table["rowCount"])`）就会 `TypeError`。
这里把它钉住。
"""

from __future__ import annotations

import pathlib
import sys
import unittest
from unittest import mock

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SUBPROJECT = REPO_ROOT / "taobao-publisher"
if str(SUBPROJECT) not in sys.path:
    sys.path.insert(0, str(SUBPROJECT))

from taobao_publish import page, stages  # noqa: E402


class FakeReaderClient:
    """最小的假客户端：`_read_expected_value` 只需要 `evaluate`。"""

    def __init__(self, responses):
        self.responses = responses

    def evaluate(self, expression, context_id=None):
        for needle, payload in self.responses.items():
            if needle in expression:
                return payload
        return {}


class ReadbackDispatchTest(unittest.TestCase):
    """分派要认识全部 kind，且对**实机见过的异常形状**也能给出字符串。"""

    def _read(self, entry, responses):
        client = FakeReaderClient(responses)
        return stages._read_expected_value(client, page, entry)

    def test_sku_specs_handles_missing_rows(self) -> None:
        """没有 `rows` 时如实报「0 行」，不编内容。"""

        with mock.patch.object(page, "read_sku_table",
                               return_value={"found": True, "tableCount": 0}):
            got = stages._read_expected_value(
                None, page, {"label": "SKU 规格值", "kind": "sku_specs"})
        self.assertEqual(got, "0 行：")

    def test_sku_specs_handles_none_rows(self) -> None:
        with mock.patch.object(page, "read_sku_table",
                               return_value={"found": True, "rows": None}):
            got = stages._read_expected_value(
                None, page, {"label": "SKU 规格值", "kind": "sku_specs"})
        self.assertEqual(got, "0 行：")

    def test_sku_specs_reads_the_values_not_just_the_count(self) -> None:
        """⚠️ **这一条是这一轮的核心。**

        旧版只核对 `rowCount`——于是「规格值填错」也能通过。
        现在读的是 `rows[].specs`，**内容参与比对**。
        """

        with mock.patch.object(page, "read_sku_table",
                               return_value={"found": True, "rowCount": 2, "rows": [
                                   {"specs": ["M(37-41)"]},
                                   {"specs": ["L(42-45)"]},
                               ]}):
            got = stages._read_expected_value(
                None, page, {"label": "SKU 规格值", "kind": "sku_specs"})
        self.assertEqual(got, "2 行：L(42-45)｜M(37-41)")

    def test_sku_specs_differs_when_the_values_differ(self) -> None:
        """行数相同、规格值不同 → 结果**必须不同**（否则这项没有判别力）。"""

        def read(specs):
            with mock.patch.object(page, "read_sku_table",
                                   return_value={"found": True, "rows": [
                                       {"specs": [specs]}]}):
                return stages._read_expected_value(
                    None, page, {"label": "SKU 规格值", "kind": "sku_specs"})

        self.assertNotEqual(read("M(37-41)"), read("L(42-45)"))
        self.assertEqual(read("M(37-41)"), "1 行：M(37-41)")

    def test_main_image_count_handles_missing_filled(self) -> None:
        """同理：`read_main_image_slots` 在没有主图区时也不返回 `filled`。"""

        with mock.patch.object(page, "read_main_image_slots",
                               return_value={"found": False, "reason": "no_area"}):
            got = stages._read_expected_value(
                None, page, {"label": "主图张数", "kind": "main_image_count"})
        self.assertEqual(got, "0")

    def test_freight_template_handles_none(self) -> None:
        """运费模板读不到时返回 `None`，要转成空串而不是 `'None'`。"""

        with mock.patch.object(page, "read_freight_template", return_value=None):
            got = stages._read_expected_value(
                None, page, {"label": "运费模板", "kind": "freight_template"})
        self.assertEqual(got, "")

    def test_every_kind_returns_a_string(self) -> None:
        """分派的产物必须是字符串——比较两边 `strip()` 的前提。"""

        responses = {
            "sku": {"found": True, "rowCount": 3},
            "main": {"found": True, "filled": 5},
        }
        cases = [
            ({"label": "SKU 规格值", "kind": "sku_specs"}, responses),
            ({"label": "主图张数", "kind": "main_image_count"}, responses),
        ]
        for entry, resp in cases:
            with self.subTest(kind=entry["kind"]):
                got = self._read(entry, resp)
                self.assertIsInstance(got, str)

    def test_unknown_kind_raises_instead_of_reading_as_text(self) -> None:
        """未知 kind 要**显式报错**，不能静默按文本读——那会变成一次假核对。"""

        with self.assertRaises(ValueError):
            stages._read_expected_value(
                FakeReaderClient({}), page, {"label": "X", "kind": "zz_unknown"})

    def test_every_expected_entry_declares_a_known_kind(self) -> None:
        """`expected_field_values` 产出的每一项，kind 都要在分派认识的范围里。"""

        from taobao_publish.models import ImageSet, PropEntry, PublishItem, SkuEntry

        item = PublishItem(
            record_id=1, record_name="ID-1", title="标题",
            images=ImageSet(main=["a.jpg", "b.jpg"], detail=[]),
            props=[PropEntry(prop_name="品牌", value_name="无品牌")],
            skus=[SkuEntry(spec_values={"尺码": "均码"}, price=1.0, stock=1)],
            freight_template_name="极兔快递",
            guide_title="导购",
        )
        ctx = stages.PipelineContext(item=item, dry_run=False)
        known = {"text", "main_image_count", "sku_specs", "sku_row_prices", "sku_row_values", "freight_template", "submit_ready"}
        for entry in stages.expected_field_values(ctx):
            self.assertIn(entry["kind"], known,
                          "条目 {!r} 的 kind 不在分派范围里".format(entry["label"]))


if __name__ == "__main__":
    unittest.main()

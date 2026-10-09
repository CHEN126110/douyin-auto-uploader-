# -*- coding: utf-8 -*-
"""填 SKU 行的价格与库存：**按规格值匹配行与 SKU，不按序号**。

## 为什么这一项曾经缺失

平台页面上**可见地**报着：

```
至少有一个sku的价格大于0，请先设置sku价格
```

而 SKU 行的价格列是空的——`fill_skus` 只创建规格行，
`fill_price_stock` 填的是**商品级**「一口价/总库存」，是另一张表。
**两边都被核对通过，而平台说不能提交。**

## 实测（2026-10-03）

```
设值之前：SKU 行 [{'price': '', 'stock': '0'}]   平台报错 ['至少有一个sku的价格大于0…']
设值之后：SKU 行 [{'price': '16.80', 'stock': '200'}]   平台报错 **（已消失）**
```

完整链条：

```
[OK] fill_skus  …；每行价格库存已填并回读
[OK] readback   回读核对通过：9 项全部一致（…、SKU 规格值、SKU 价格、…）
```
"""

from __future__ import annotations

import inspect
import pathlib
import sys
import unittest
from unittest import mock

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SUBPROJECT = REPO_ROOT / "taobao-publisher"
if str(SUBPROJECT) not in sys.path:
    sys.path.insert(0, str(SUBPROJECT))

from taobao_publish import page, stages  # noqa: E402
from taobao_publish.models import PublishItem, SkuEntry  # noqa: E402


class FakeClient:
    def __init__(self, rows, after=None):
        self.rows = rows
        self.after = after if after is not None else rows
        self.reads = 0
        self.sets = []

    def evaluate(self, expression, **_kwargs):
        if "read_sku_table" in expression or '"rows"' in expression:
            pass
        return None


def make_ctx(skus):
    item = PublishItem(record_id=1, record_name="X", title="t", skus=skus)
    return stages.PipelineContext(item=item, dry_run=False)


class SpecKeyTest(unittest.TestCase):
    def test_key_ignores_dict_order(self) -> None:
        """`spec_values` 的键序不保证稳定，键必须与顺序无关。"""

        first = stages._sku_spec_key({"尺码": "M", "颜色": "黑"})
        second = stages._sku_spec_key({"颜色": "黑", "尺码": "M"})
        self.assertEqual(first, second)

    def test_key_skips_blanks(self) -> None:
        self.assertEqual(stages._sku_spec_key({"尺码": "M", "颜色": "  "}), "M")

    def test_as_number_normalises(self) -> None:
        """`16.80` 与 `16.8` 必须视为相同。"""

        self.assertEqual(stages._as_number("16.80"), stages._as_number("16.8"))
        self.assertNotEqual(stages._as_number("16.80"), stages._as_number("16.81"))

    def test_as_number_keeps_garbage_as_text(self) -> None:
        self.assertEqual(stages._as_number("abc"), "abc")


class FillSkuRowNumbersTest(unittest.TestCase):
    """用替身驱动 `_fill_sku_row_numbers`。"""

    def _run(self, skus, table_rows, after_rows=None):
        ctx = make_ctx(skus)
        table = {"found": True, "tableCount": 1, "rowCount": len(table_rows),
                 "rows": table_rows}
        numbers = after_rows if after_rows is not None else table_rows
        with mock.patch.object(page, "read_sku_table", return_value=table), \
                mock.patch.object(page, "read_sku_row_numbers", return_value=numbers), \
                mock.patch.object(page, "set_sku_row_numbers") as setter:
            result = stages._fill_sku_row_numbers(object(), page, ctx)
        return result, setter

    def test_it_fills_by_spec_not_by_index(self) -> None:
        """⚠️ **行顺序与 `item.skus` 不同时，必须按规格值对上。**"""

        skus = [SkuEntry(spec_values={"尺码": "M"}, price=11.0, stock=100),
                SkuEntry(spec_values={"尺码": "L"}, price=22.0, stock=200)]
        # 表格里 L 在前、M 在后 —— 与 item.skus 相反
        table_rows = [{"specs": ["L"]}, {"specs": ["M"]}]
        numbers = [{"price": "22.00", "stock": "200"}, {"price": "11.00", "stock": "100"}]
        result, setter = self._run(skus, table_rows, numbers)

        calls = [(c.args[1], c.kwargs) for c in setter.call_args_list]
        self.assertEqual(calls[0], (0, {"price": "22.00", "stock": "200"}),
                         "第 0 行是 L，应当填 L 的价格")
        self.assertEqual(calls[1], (1, {"price": "11.00", "stock": "100"}))
        self.assertEqual([r["specs"] for r in result], ["L", "M"])

    def test_a_row_with_no_matching_sku_fails(self) -> None:
        """匹配不上就失败，**不猜**。"""

        skus = [SkuEntry(spec_values={"尺码": "M"}, price=11.0, stock=1)]
        with self.assertRaises(page.CandidateNotFound) as context:
            self._run(skus, [{"specs": ["XL"]}])
        self.assertIn("XL", str(context.exception))

    def test_duplicate_specs_in_the_item_are_ambiguous(self) -> None:
        """`item.skus` 里规格重复 → 有歧义 → 失败（不随便挑一条）。"""

        skus = [SkuEntry(spec_values={"尺码": "M"}, price=11.0, stock=1),
                SkuEntry(spec_values={"尺码": "M"}, price=22.0, stock=2)]
        with self.assertRaises(page.CandidateNotFound) as context:
            self._run(skus, [{"specs": ["M"]}])
        self.assertIn("匹配到 2 条", str(context.exception))

    def test_a_value_that_did_not_stick_is_a_failure(self) -> None:
        """「设了」不等于「设对了」——回读不符必须失败。"""

        skus = [SkuEntry(spec_values={"尺码": "M"}, price=16.8, stock=200)]
        with self.assertRaises(page.CandidateNotFound) as context:
            self._run(skus, [{"specs": ["M"]}], [{"price": "", "stock": "200"}])
        self.assertIn("价格没有设上", str(context.exception))

    def test_an_empty_table_returns_empty_instead_of_raising(self) -> None:
        """⚠️ **无行时返回空，不抛错**——让阶段报出更具体的诊断。

        「表格根本没出现」（`SKU_CREATE_SILENT_FAILURE`）比
        「没有行可以填价格」更有用；在这里抢先抛错会把它盖掉（实测过）。
        """

        skus = [SkuEntry(spec_values={"尺码": "M"}, price=1.0, stock=1)]
        result, setter = self._run(skus, [])
        self.assertEqual(result, [])
        setter.assert_not_called()

    def test_none_price_becomes_an_empty_string(self) -> None:
        """`price=None` 是「没给」，不是 0——**不能编一个 0 填上去**。"""

        skus = [SkuEntry(spec_values={"尺码": "M"}, price=None, stock=None)]
        _result, setter = self._run(skus, [{"specs": ["M"]}],
                                    [{"price": "", "stock": ""}])
        self.assertEqual(setter.call_args_list[0].kwargs, {"price": "", "stock": ""})


class StageWiringTest(unittest.TestCase):
    def test_fill_skus_calls_it(self) -> None:
        source = inspect.getsource(stages.stage_fill_skus)
        self.assertIn("_fill_sku_row_numbers", source)

    def test_the_result_is_recorded_and_reported(self) -> None:
        source = inspect.getsource(stages.stage_fill_skus)
        self.assertIn("filled_rows", source)
        self.assertIn("每行价格库存已填并回读", source)

    def test_the_setter_uses_native_setter_and_events(self) -> None:
        """React 受控输入：直接赋 `value` 不会触发框架状态更新。"""

        source = inspect.getsource(page.build_set_sku_row_numbers_expression)
        self.assertIn("getOwnPropertyDescriptor", source)
        for event in ("input", "change", "blur"):
            with self.subTest(event=event):
                self.assertIn("'{}'".format(event), source)

    def test_the_setter_locates_columns_by_unit_text(self) -> None:
        source = inspect.getsource(page.build_set_sku_row_numbers_expression)
        self.assertIn("元", source)
        self.assertIn("件", source)
        self.assertNotIn("nth-child", source)


if __name__ == "__main__":
    unittest.main()

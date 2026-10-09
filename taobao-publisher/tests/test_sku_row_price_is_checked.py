# -*- coding: utf-8 -*-
"""**平台说这张表单提交不了，而我们的核对说「8 项全部一致」。**

## 实机发现（2026-10-03）

完整链条跑完之后，页面上有一条**可见的**平台提示：

```
至少有一个sku的价格大于0，请先设置sku价格
   cls = next-message next-message-notice    h = 43    visible = true
```

而 SKU 表的实测结构（第 3 列单元格文本是 `元`，第 5 列是 `件`）：

```
第 1 行  specs=['M(37-41)']
   单元格 '元'  输入框 = ""    ← **价格是空的**
   单元格 '件'  输入框 = "0"   ← 库存 0
```

## 为什么所有核对都没发现

| 谁 | 它做什么 |
|---|---|
| `fill_skus` | 只创建规格行，**完全不碰价格库存** |
| `fill_price_stock` | 填**商品级**「一口价 / 总库存」✓ |
| `readback` | 只核对**商品级**字段，**从不看 SKU 行** |
| **平台** | **不能提交** |

**两张表不是一回事**：商品级的一口价填了 16.80 且核对通过，
而 SKU 行自己的价格列是空的——平台要的是后者。

**所以从第 60 轮起我一直报的「完整链条 8/8 通过」，掩盖了一个提交阻塞项。**

## 这一轮做了什么

把平台的判据**原样**搬进核对（`kind = "sku_row_prices"`）：

```
期望 = '至少一行价格大于 0'
实际 = '1 行价格都为空或 0'
→ 失败
```

完整链条现在**正确地停在这里**：

```
[FAIL] readback  回读核对未通过：一致 8 项，不一致 1 项
       期望 '至少一行价格大于 0'，实际 '1 行价格都为空或 0'
→ 这一步没通过，**停在这里**
```

**填 SKU 行的价格是下一步**——但先把静默失败变成明确阻塞项。
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
from taobao_publish.models import (  # noqa: E402
    CategoryRef,
    ImageSet,
    PublishItem,
    SkuEntry,
)


def make_item() -> PublishItem:
    return PublishItem(
        record_id=1, record_name="X", title="标题",
        category=CategoryRef(path=("a", "b"), category_id="1"),
        images=ImageSet(main=["m.jpg"], detail=[]),
        skus=[SkuEntry(spec_values={"尺码": "M(37-41)"}, price=16.8, stock=200)],
    )


class SkuRowPriceExpectationTest(unittest.TestCase):
    def test_the_platform_rule_is_among_the_expectations(self) -> None:
        ctx = stages.PipelineContext(item=make_item(), dry_run=False)
        entry = next(e for e in stages.expected_field_values(ctx)
                     if e["kind"] == "sku_row_prices")
        self.assertEqual(entry["value"], "至少一行价格大于 0")

    def test_its_source_quotes_the_platform(self) -> None:
        """`source` 要引**平台原文**——这不是我们自己编的规则。"""

        ctx = stages.PipelineContext(item=make_item(), dry_run=False)
        entry = next(e for e in stages.expected_field_values(ctx)
                     if e["kind"] == "sku_row_prices")
        self.assertIn("至少有一个sku的价格大于0", entry["source"])

    def test_it_is_not_veto_only(self) -> None:
        """⚠️ 它与「提交按钮」不同：那是只做否决，**这是硬判据**，必须计入。"""

        ctx = stages.PipelineContext(item=make_item(), dry_run=False)
        entry = next(e for e in stages.expected_field_values(ctx)
                     if e["kind"] == "sku_row_prices")
        self.assertFalse(entry.get("veto_only"))


class SkuRowPriceDispatchTest(unittest.TestCase):
    def _read(self, rows):
        with mock.patch.object(page, "read_sku_row_numbers", return_value=rows):
            return stages._read_expected_value(
                None, page, {"label": "SKU 价格", "kind": "sku_row_prices"})

    def test_a_positive_price_passes(self) -> None:
        self.assertEqual(self._read([{"price": "16.8", "stock": "200"}]),
                         "至少一行价格大于 0")

    def test_an_empty_price_fails(self) -> None:
        """**这一条就是实测的情形。**"""

        self.assertEqual(self._read([{"price": "", "stock": "0"}]),
                         "1 行价格都为空或 0")

    def test_a_zero_price_fails(self) -> None:
        self.assertEqual(self._read([{"price": "0", "stock": "5"}]),
                         "1 行价格都为空或 0")

    def test_one_positive_row_is_enough(self) -> None:
        """平台的判据是「**至少有一个**」，不是「全部」。"""

        self.assertEqual(
            self._read([{"price": "", "stock": "0"}, {"price": "9.9", "stock": "1"}]),
            "至少一行价格大于 0")

    def test_unreadable_rows_are_not_a_pass(self) -> None:
        """读不到行**不能**当成通过——那是把「不知道」当「没问题」。"""

        self.assertNotEqual(self._read([]), "至少一行价格大于 0")

    def test_garbage_price_is_not_a_pass(self) -> None:
        self.assertEqual(self._read([{"price": "abc"}]), "1 行价格都为空或 0")


class ReaderExpressionTest(unittest.TestCase):
    def test_the_reader_locates_columns_by_unit_text(self) -> None:
        """⚠️ **按单位字（`元` / `件`）判列，不按列序号**——列顺序会随设置变。"""

        source = inspect.getsource(page.build_read_sku_row_numbers_expression)
        self.assertIn("元", source)
        self.assertIn("件", source)
        self.assertNotIn("td:nth-child", source)

    def test_the_reader_returns_empty_on_a_missing_table(self) -> None:
        with mock.patch.object(page, "PageClient") as fake:
            fake.return_value.evaluate.return_value = {"ok": False}
            self.assertEqual(page.read_sku_row_numbers(fake.return_value), [])


if __name__ == "__main__":
    unittest.main()

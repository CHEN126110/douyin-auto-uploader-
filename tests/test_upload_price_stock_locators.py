# -*- coding: utf-8 -*-

from __future__ import annotations

import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_PATH = PROJECT_ROOT / "tauri-app" / "python-sidecar" / "app.py"


class UploadPriceStockLocatorTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = APP_PATH.read_text(encoding="utf-8")

    def test_price_stock_root_supports_new_publish_container(self) -> None:
        self.assertIn("def _find_price_stock_root", self.source)
        self.assertIn("goodsEditScrollContainer-价格库存", self.source)
        self.assertIn('attr-field-id="售卖价"', self.source)
        self.assertIn('attr-field-id="订单库存计数"', self.source)

    def test_sku_entry_switches_to_manual_mode_before_sku_form(self) -> None:
        self.assertIn("def _ensure_manual_sku_entry_mode", self.source)
        self.assertIn("切换手动填写", self.source)
        self.assertIn("skuValue-颜色分类", self.source)

        configure_body = self.source.split("def _configure_sku_entries", 1)[1].split(
            "def _sku_color_type_exists", 1
        )[0]
        self.assertIn("_scroll_to_price_stock_area", configure_body)
        self.assertIn("_ensure_manual_sku_entry_mode", configure_body)

    def test_price_stock_fill_uses_shared_root_finder(self) -> None:
        fill_body = self.source.split("def _fill_price_stock_and_delivery", 1)[1].split(
            "def _submit_publish", 1
        )[0]
        self.assertIn("_find_price_stock_root", fill_body)
        self.assertIn("跳过价格库存空白行", fill_body)
        self.assertNotIn(
            "main_tab.ele('xpath://div[@attr-field-id=\"价格与库存\"]')",
            fill_body,
        )


if __name__ == "__main__":
    unittest.main()

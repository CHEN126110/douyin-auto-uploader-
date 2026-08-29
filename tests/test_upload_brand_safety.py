# -*- coding: utf-8 -*-

from __future__ import annotations

import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_PATH = PROJECT_ROOT / "tauri-app" / "python-sidecar" / "app.py"


class UploadBrandSafetyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = APP_PATH.read_text(encoding="utf-8")

    def test_title_brand_name_checkbox_is_forced_off(self) -> None:
        self.assertIn("def _ensure_title_brand_name_disabled", self.source)
        self.assertIn("使用品牌名", self.source)

        fill_title_body = self.source.split("def _fill_title_for_record", 1)[1].split(
            "def _open_publish_page", 1
        )[0]
        self.assertIn("_ensure_title_brand_name_disabled", fill_title_body)

    def test_category_brand_is_always_no_brand(self) -> None:
        category_body = self.source.split("def _fill_category_attributes", 1)[1].split(
            "def _upload_media_assets", 1
        )[0]
        self.assertIn("ensure_no_brand(main_tab)", category_body)
        self.assertNotIn("select_text(main_tab, '品牌', record", category_body)
        self.assertNotIn("select_text(main_tab, '品牌'", category_body)

    def test_ensure_no_brand_targets_no_brand_only(self) -> None:
        """ensure_no_brand 只能设「无品牌」，且必须先收起会遮挡品牌字段的材质浮层。"""
        utils_source = (PROJECT_ROOT / "src" / "utils.py").read_text(encoding="utf-8")
        body = utils_source.split("def ensure_no_brand", 1)[1].split(chr(10) + "def ", 1)[0]
        self.assertIn("'无品牌'", body)
        self.assertIn("close_aurora_composition_panel", body)
        # 兜底分支必须以真实读回的当前值为结论，不能直接 return True
        self.assertIn("== '无品牌'", body)


if __name__ == "__main__":
    unittest.main()

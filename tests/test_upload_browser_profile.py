# -*- coding: utf-8 -*-

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src import shop_session  # noqa: E402
from src.utils import _get_persistent_browser_user_data_path  # noqa: E402


class UploadBrowserProfileTest(unittest.TestCase):
    def test_upload_browser_profile_uses_stable_data_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            old_value = os.environ.get("DOUYIN_DATA_DIR")
            os.environ["DOUYIN_DATA_DIR"] = tmp_dir
            try:
                profile_path = Path(_get_persistent_browser_user_data_path())
            finally:
                if old_value is None:
                    os.environ.pop("DOUYIN_DATA_DIR", None)
                else:
                    os.environ["DOUYIN_DATA_DIR"] = old_value

        self.assertEqual(profile_path, Path(tmp_dir) / "upload-browser-profile")
        self.assertNotIn("DrissionPage", str(profile_path))

    def test_browser_and_registry_resolve_the_same_profile_dir(self) -> None:
        """两处目录解析必须一致。

        店铺列表来自 shop_session，实际打开浏览器走 src.utils。两者算出不同目录，
        就会出现「界面显示 A 店、商品发到 B 店」，而且全程不报错。
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            old_value = os.environ.get("DOUYIN_DATA_DIR")
            os.environ["DOUYIN_DATA_DIR"] = tmp_dir
            try:
                for label in ["某某旗舰店", "另一家店", "Shop B", shop_session.DEFAULT_PROFILE_NAME]:
                    slug = shop_session.slugify_profile_name(label)
                    self.assertEqual(
                        Path(_get_persistent_browser_user_data_path(slug)),
                        Path(shop_session.profile_dir(slug)),
                        f"{label!r} 的目录解析不一致",
                    )
            finally:
                if old_value is None:
                    os.environ.pop("DOUYIN_DATA_DIR", None)
                else:
                    os.environ["DOUYIN_DATA_DIR"] = old_value


if __name__ == "__main__":
    unittest.main()

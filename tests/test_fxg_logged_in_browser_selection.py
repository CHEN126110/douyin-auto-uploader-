# -*- coding: utf-8 -*-

from __future__ import annotations

import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.utils import (  # noqa: E402
    is_logged_in_fxg_target_url,
    select_logged_in_fxg_debug_browser,
)


class FxgLoggedInBrowserSelectionTest(unittest.TestCase):
    def test_login_url_is_not_reusable_session(self) -> None:
        self.assertFalse(
            is_logged_in_fxg_target_url(
                "https://fxg.jinritemai.com/login/common?redirect_url=https%3A%2F%2Ffxg.jinritemai.com%2Fffa%2Fg%2Fcreate"
            )
        )
        self.assertTrue(
            is_logged_in_fxg_target_url("https://fxg.jinritemai.com/ffa/mshop/homepage/index")
        )

    def test_selects_logged_in_cdp_when_upload_browser_is_on_login_page(self) -> None:
        browsers = [
            {
                "debug_address": "127.0.0.1:9222",
                "user_data_dir": r"E:\Script Project\Dyin\beiufen\2.0\upload-browser-profile",
            },
            {
                "debug_address": "127.0.0.1:9333",
                "user_data_dir": r"E:\Script Project\Dyin\beiufen\2.0\.runtime\chrome-fxg-cdp",
            },
        ]
        targets_by_address = {
            "127.0.0.1:9222": [
                {
                    "type": "page",
                    "url": "https://fxg.jinritemai.com/login/common?redirect_url=https%3A%2F%2Ffxg.jinritemai.com",
                }
            ],
            "127.0.0.1:9333": [
                {
                    "type": "page",
                    "url": "https://fxg.jinritemai.com/ffa/mshop/homepage/index",
                }
            ],
        }

        selected = select_logged_in_fxg_debug_browser(browsers, targets_by_address)

        self.assertIsNotNone(selected)
        self.assertEqual(selected["debug_address"], "127.0.0.1:9333")
        self.assertEqual(selected["matched_url"], "https://fxg.jinritemai.com/ffa/mshop/homepage/index")

    def test_prefers_logged_in_upload_profile_when_available(self) -> None:
        browsers = [
            {
                "debug_address": "127.0.0.1:9222",
                "user_data_dir": r"E:\Script Project\Dyin\beiufen\2.0\upload-browser-profile",
            },
            {
                "debug_address": "127.0.0.1:9333",
                "user_data_dir": r"E:\Script Project\Dyin\beiufen\2.0\.runtime\chrome-fxg-cdp",
            },
        ]
        targets_by_address = {
            "127.0.0.1:9222": [
                {
                    "type": "page",
                    "url": "https://fxg.jinritemai.com/ffa/g/create",
                }
            ],
            "127.0.0.1:9333": [
                {
                    "type": "page",
                    "url": "https://fxg.jinritemai.com/ffa/mshop/homepage/index",
                }
            ],
        }

        selected = select_logged_in_fxg_debug_browser(browsers, targets_by_address)

        self.assertIsNotNone(selected)
        self.assertEqual(selected["debug_address"], "127.0.0.1:9222")


if __name__ == "__main__":
    unittest.main()

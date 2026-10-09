# -*- coding: utf-8 -*-
"""协议发布必须能找到任意店铺的浏览器。

原来这里只断言「扫描候选端口列表里包含调试浏览器端口段」。
2026-09-06 起每份店铺账号信息各占一个端口，写死的端口范围一定会漏，
所以主路径改成按进程枚举（Chrome 把调试端口写在命令行里，一定拿得全）。
候选端口列表仍作为兜底，范围也要跟着覆盖店铺端口段。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
APP_PATH = PROJECT_ROOT / "tauri-app" / "python-sidecar" / "app.py"

from src.utils import (  # noqa: E402
    _SHOP_BROWSER_PORT_END,
    _SHOP_BROWSER_PORT_START,
)


class SidecarProtocolPortsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.source = APP_PATH.read_text(encoding="utf-8")

    def _body(self, start: str, end: str) -> str:
        return self.source.split(start, 1)[1].split(end, 1)[0]

    def test_finder_discovers_browsers_by_process_enumeration(self) -> None:
        # 写死端口范围找不到落在其它端口上的店铺浏览器，必须走进程枚举。
        body = self._body("def _find_cdp_port_with_jinritemai():", "def _ensure_protocol_browser")
        self.assertIn("discover_debuggable_browsers", body)

    def test_finder_excludes_other_shops_browsers(self) -> None:
        # 多店铺并存时抢到别人的浏览器就会发错店。
        body = self._body("def _find_cdp_port_with_jinritemai():", "def _ensure_protocol_browser")
        self.assertIn("filter_browsers_for_profile", body)

    def test_candidate_ports_still_cover_every_range_we_launch(self) -> None:
        body = self._body("def _protocol_cdp_port_candidates():", "def _find_cdp_port_with_jinritemai")
        for marker in (
            "_DEBUG_BROWSER_PORT_START",
            "_DEBUG_BROWSER_PORT_END",
            "_CAPTURE_BROWSER_PORT_START",
            "_SHOP_BROWSER_PORT_START",
            "_SHOP_BROWSER_PORT_END",
        ):
            self.assertIn(marker, body, f"兜底端口列表漏了 {marker}")

    def test_shop_port_range_matches_the_browser_launcher(self) -> None:
        # 两边写死的范围必须一致，否则 sidecar 扫不到自己启的浏览器。
        self.assertIn(
            f"_SHOP_BROWSER_PORT_START = {_SHOP_BROWSER_PORT_START}",
            self.source,
        )
        self.assertIn(f"_SHOP_BROWSER_PORT_END = {_SHOP_BROWSER_PORT_END}", self.source)


if __name__ == "__main__":
    unittest.main()

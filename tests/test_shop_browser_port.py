# -*- coding: utf-8 -*-
"""每份账号信息必须独占一个调试端口。

DrissionPage 的 ChromiumOptions 默认固定用 127.0.0.1:9222，而它遇到
「端口上已有浏览器」时是**接管**那个浏览器，不是另开一个——传进去的
user_data_dir 会被完全忽略。

2026-09-06 实测事故：点「添加店铺」后打开的还是原来那家店，因为原店铺的
浏览器正占着 9222，新 profile 直接被接管掉了。
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.utils import (  # noqa: E402
    _DEFAULT_BROWSER_PROFILE_NAME,
    _LEGACY_BROWSER_PORT,
    _SHOP_BROWSER_PORT_START,
    _resolve_browser_port_for_profile,
)


BASE = os.path.join("C:\\", "data")


def _dir(name: str) -> str:
    return os.path.join(BASE, name)


def _browser(port: int, profile: str) -> dict:
    return {"debug_address": f"127.0.0.1:{port}", "user_data_dir": _dir(profile)}


class ShopBrowserPortTest(unittest.TestCase):
    def test_reuses_the_port_of_this_profiles_own_browser(self) -> None:
        # 同一家店不该开两个窗口。
        port = _resolve_browser_port_for_profile(
            _dir("shop-aaaa"),
            "shop-aaaa",
            running=[_browser(9222, "shop-aaaa")],
            port_is_free=lambda _p: True,
        )
        self.assertEqual(port, 9222)

    def test_never_lands_on_a_port_held_by_another_profile(self) -> None:
        # 落到别人的端口上就会接管别人的浏览器，等于打开了另一家店。
        occupied = [_browser(9222, "shop-other"), _browser(_SHOP_BROWSER_PORT_START, "shop-third")]
        port = _resolve_browser_port_for_profile(
            _dir("shop-new"), "shop-new", running=occupied, port_is_free=lambda _p: True
        )
        self.assertNotIn(port, {9222, _SHOP_BROWSER_PORT_START})

    def test_default_profile_keeps_the_legacy_port_when_it_is_free(self) -> None:
        # 历史上只有一份账号信息，一直在 9222；旧的复用与扫描逻辑按这个端口找它。
        port = _resolve_browser_port_for_profile(
            _dir(_DEFAULT_BROWSER_PROFILE_NAME),
            _DEFAULT_BROWSER_PROFILE_NAME,
            running=[],
            port_is_free=lambda _p: True,
        )
        self.assertEqual(port, _LEGACY_BROWSER_PORT)

    def test_new_profile_does_not_take_the_legacy_port(self) -> None:
        port = _resolve_browser_port_for_profile(
            _dir("shop-new"), "shop-new", running=[], port_is_free=lambda _p: True
        )
        self.assertEqual(port, _SHOP_BROWSER_PORT_START)

    def test_skips_ports_that_are_busy_even_without_a_known_browser(self) -> None:
        busy = {_SHOP_BROWSER_PORT_START, _SHOP_BROWSER_PORT_START + 1}
        port = _resolve_browser_port_for_profile(
            _dir("shop-new"),
            "shop-new",
            running=[],
            port_is_free=lambda p: p not in busy,
        )
        self.assertEqual(port, _SHOP_BROWSER_PORT_START + 2)

    def test_raises_when_no_port_is_available(self) -> None:
        with self.assertRaises(Exception):
            _resolve_browser_port_for_profile(
                _dir("shop-new"), "shop-new", running=[], port_is_free=lambda _p: False
            )


if __name__ == "__main__":
    unittest.main()

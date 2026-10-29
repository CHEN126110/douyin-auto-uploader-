# -*- coding: utf-8 -*-
"""账户菜单必须按后端的身份证据显示验证状态，而不是只认店铺 ID。"""

from pathlib import Path
import re
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SHOP_STATUS_BAR = PROJECT_ROOT / "tauri-app" / "src" / "components" / "ShopStatusBar.vue"


class ShopStatusBarTest(unittest.TestCase):
    def test_unverified_badge_uses_identity_source_not_only_shop_id(self) -> None:
        source = SHOP_STATUS_BAR.read_text(encoding="utf-8")
        match = re.search(
            r'<span\s+v-if="([^"]+)"\s+class="item-state">未验证登录</span>',
            source,
        )
        self.assertIsNotNone(match, "找不到账户列表的未验证状态标记")
        condition = match.group(1)
        self.assertEqual(condition, "profile.identity_source !== 'registry_last_seen'")
        self.assertNotIn("!profile.shop_id", condition)

    def test_no_browser_is_not_misreported_as_platform_logged_out(self) -> None:
        source = SHOP_STATUS_BAR.read_text(encoding="utf-8")
        self.assertIn('case "no_browser":', source)
        self.assertIn("浏览器未启动", source)
        self.assertIn('case "logged_out":', source)
        self.assertIn("正在恢复账户浏览器", source)

    def test_restore_runs_once_on_mount_not_during_regular_refresh(self) -> None:
        source = SHOP_STATUS_BAR.read_text(encoding="utf-8")
        mounted = source.split("onMounted(async () => {", 1)[1].split("onUnmounted", 1)[0]
        self.assertEqual(mounted.count("api.restoreShopSession()"), 1)
        regular_refresh = source.split("async function refresh", 1)[1].split("function stopLoginWatch", 1)[0]
        self.assertNotIn("restoreShopSession", regular_refresh)


if __name__ == "__main__":
    unittest.main()

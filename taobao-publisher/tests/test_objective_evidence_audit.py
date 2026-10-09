# -*- coding: utf-8 -*-
"""两个审计脚本要**保住可复跑**——它们回答的是「目标做到了没有」。

## `audit-objective-evidence.py`

逐条核对 objective 的六个子句，**每条给当前的真实状态**，不引用历史叙述。
它是「能不能说完成了」的依据，所以：

* 不许把「协议路线」的缺口说成本次的门；
* 不许把 `submit` 说成已完成。

## `audit-unwired-capabilities.py`

找「子项目有能力、Sidecar 没接」的地方。
第 66~68 轮零散撞到三次（主图取法 / `outer_id` / 淘宝运费模板），这是它的系统化版本。
"""

from __future__ import annotations

import pathlib
import subprocess
import sys
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SUBPROJECT = REPO_ROOT / "taobao-publisher"
if str(SUBPROJECT) not in sys.path:
    sys.path.insert(0, str(SUBPROJECT))

EVIDENCE = SUBPROJECT / "scripts" / "audit-objective-evidence.py"
UNWIRED = SUBPROJECT / "scripts" / "audit-unwired-capabilities.py"


class ObjectiveAuditScriptTest(unittest.TestCase):
    def setUp(self) -> None:
        self.source = EVIDENCE.read_text(encoding="utf-8")

    def test_it_covers_every_clause(self) -> None:
        for clause in ("1) 阶段", "2) 选择器证据", "3) platform_field",
                       "4) Sidecar 与前端", "5) 从本地商品一键发布", "6) 红线"):
            with self.subTest(clause=clause):
                self.assertIn(clause, self.source)

    def test_it_separates_the_two_routes(self) -> None:
        """⚠️ 不许把协议路线的字段缺口说成本次的门（第 41/42/64 轮修过三次）。"""

        self.assertIn("只关协议路线", self.source)
        self.assertIn("dom_write_ready", self.source)

    def test_it_does_not_claim_submit_is_done(self) -> None:
        self.assertIn("submit 未执行", self.source)

    def test_it_runs_clean(self) -> None:
        result = subprocess.run(
            [sys.executable, str(EVIDENCE)],
            cwd=str(SUBPROJECT), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=120,
        )
        self.assertEqual(result.returncode, 0, result.stderr[-800:])
        self.assertIn("目标证据盘点", result.stdout)


class UnwiredCapabilityAuditTest(unittest.TestCase):
    def test_script_exists_and_is_honest_about_being_a_list(self) -> None:
        source = UNWIRED.read_text(encoding="utf-8")
        self.assertIn("清单，不是结论", source,
                      "必须写明这只是清单——「Sidecar 没调」不等于「该接」")

    def test_it_runs_clean(self) -> None:
        result = subprocess.run(
            [sys.executable, str(UNWIRED)],
            cwd=str(SUBPROJECT), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=120,
        )
        self.assertEqual(result.returncode, 0, result.stderr[-800:])


class UserFlowReachableTest(unittest.TestCase):
    """用户描述过的流程（第 7 轮），每一步都要有落点。"""

    def setUp(self) -> None:
        self.app = (REPO_ROOT / "tauri-app" / "python-sidecar" / "app.py").read_text(
            encoding="utf-8")

    def test_add_shop_route_exists_and_launches_the_browser(self) -> None:
        """「添加店铺然后选择淘宝的话 **那么拉起来浏览器**」。"""

        self.assertIn("/api/shop/add", self.app)
        self.assertIn("open_browser", self.app)
        self.assertIn("_activate_shop_profile", self.app)

    def test_there_is_deliberately_no_login_route(self) -> None:
        """⚠️ **登录不该有接口**——红线是「不做登录绕过」。

        登录就是用户在拉起的窗口里**自己扫码**。
        这个测试是防「好心人」加一个自动登录接口。
        """

        for forbidden in ("/api/login", "/api/shop/login", "/api/taobao/login"):
            with self.subTest(route=forbidden):
                self.assertNotIn(forbidden, self.app)

    def test_shop_identity_routes_exist(self) -> None:
        for route in ("/api/shop/current", "/api/shop/profiles",
                      "/api/shop/freight-templates"):
            with self.subTest(route=route):
                self.assertIn(route, self.app)

    def test_frontend_can_reach_the_shop_routes(self) -> None:
        api_ts = (REPO_ROOT / "tauri-app" / "src" / "services" / "api.ts").read_text(
            encoding="utf-8")
        for route in ("/api/shop/add", "/api/shop/current",
                      "/api/shop/freight-templates"):
            with self.subTest(route=route):
                self.assertIn(route, api_ts)


if __name__ == "__main__":
    unittest.main()

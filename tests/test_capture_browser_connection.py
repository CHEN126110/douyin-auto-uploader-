# -*- coding: utf-8 -*-
"""采集浏览器的端口归属、Windows 占用检查和真实连接错误回归。"""

from __future__ import annotations

import ast
import os
import re
import socket
import unittest
from pathlib import Path
from unittest.mock import Mock


APP_PATH = Path(__file__).resolve().parents[1] / "tauri-app" / "python-sidecar" / "app.py"
HELPERS = {
    "_is_local_port_available",
    "_select_capture_browser_port",
    "_capture_failure_details",
    "_capture_task_recovery_info",
}


def load_helpers():
    # 避免导入 Flask 应用时初始化真实数据库、账号配置和后台线程。
    tree = ast.parse(APP_PATH.read_text(encoding="utf-8"))
    definitions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in HELPERS]
    assert {node.name for node in definitions} == HELPERS
    namespace = {"os": os, "re": re, "socket": socket}
    exec(compile(ast.Module(body=definitions, type_ignores=[]), str(APP_PATH), "exec"), namespace)
    return namespace


class CaptureBrowserPortTest(unittest.TestCase):
    def setUp(self):
        self.helpers = load_helpers()
        self.profile = str(Path("runtime") / "采集资料")
        self.verify = Mock(return_value={"ok": True})
        self.available = Mock(return_value=True)
        self.discover = Mock(return_value=[])
        self.helpers.update({
            "_CAPTURE_BROWSER_PORT_START": 9400,
            "_CAPTURE_BROWSER_PORT_END": 9402,
            "_DEBUG_BROWSER_HOST": "127.0.0.1",
            "_get_capture_browser_user_data_path": lambda: self.profile,
            "_normalize_debug_address": lambda address: address.replace("localhost", "127.0.0.1"),
            "discover_debuggable_browsers": self.discover,
            "_verify_debug_browser": self.verify,
            "_is_local_port_available": self.available,
        })

    def select(self):
        return self.helpers["_select_capture_browser_port"]()

    def browser(self, port, profile=None):
        return {"debug_address": f"127.0.0.1:{port}", "user_data_dir": profile or self.profile}

    def test_reuses_own_browser_even_when_lower_port_is_free(self):
        self.discover.return_value = [self.browser(9402, os.path.abspath(self.profile))]
        self.assertEqual(self.select(), 9402)
        self.available.assert_not_called()
        self.verify.assert_called_once_with("127.0.0.1:9402", timeout=2.0)

    def test_does_not_take_another_profiles_browser(self):
        self.discover.return_value = [self.browser(9400, "other-profile")]
        self.assertEqual(self.select(), 9401)
        self.verify.assert_not_called()

    def test_connection_failure_does_not_relaunch_same_profile_on_new_port(self):
        self.discover.return_value = [self.browser(9402)]
        self.verify.return_value = {"ok": False, "error": "[WinError 10048] address in use"}
        with self.assertRaisesRegex(RuntimeError, "127.0.0.1:9402.*WinError 10048"):
            self.select()
        self.available.assert_not_called()

    def test_unresponsive_browser_preserves_diagnostic(self):
        self.discover.return_value = [self.browser(9400)]
        self.verify.return_value = {"ok": False, "error": "timed out"}
        with self.assertRaisesRegex(RuntimeError, "timed out"):
            self.select()
        self.available.assert_not_called()

    def test_skips_other_services_without_probing_their_http_endpoints(self):
        self.available.side_effect = lambda host, port: port == 9402
        self.assertEqual(self.select(), 9402)
        self.verify.assert_not_called()

    def test_fails_when_no_port_is_free(self):
        self.available.return_value = False
        with self.assertRaisesRegex(RuntimeError, "未找到可用"):
            self.select()


class LocalPortAvailabilityTest(unittest.TestCase):
    def test_bound_socket_is_not_considered_available(self):
        is_available = load_helpers()["_is_local_port_available"]
        # 不设置 SO_EXCLUSIVEADDRUSE，才能暴露 Windows 上 SO_REUSEADDR 的误判。
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
            self.assertFalse(is_available("127.0.0.1", port))
            listener.listen(1)
            self.assertFalse(is_available("127.0.0.1", port))


class CaptureFailureDetailsTest(unittest.TestCase):
    def setUp(self):
        self.helpers = load_helpers()
        self.describe = self.helpers["_capture_failure_details"]

    def test_unwraps_hidden_socket_error_from_browser_exception_chain(self):
        socket_error = OSError("address in use")
        socket_error.winerror = 10048
        transport_error = RuntimeError("HTTP request failed")
        transport_error.__cause__ = socket_error
        browser_error = RuntimeError("浏览器连接失败，请确认浏览器已启动。")
        browser_error.__context__ = transport_error
        result = self.describe(browser_error)
        self.assertEqual(result["error_code"], "capture_network_resources_exhausted")
        self.assertIn("WinError 10048", result["message"])
        self.assertIn("网络连接资源不足", result["message"])

    def test_recognizes_flattened_port_probe_error(self):
        result = self.describe(RuntimeError("采集浏览器已启动：[WinError 10048] address in use"))
        self.assertEqual(result["error_code"], "capture_network_resources_exhausted")

    def test_recognizes_other_socket_resource_errors(self):
        for code in (10055, 10024):
            with self.subTest(code=code):
                result = self.describe(OSError(f"[WinError {code}] resources unavailable"))
                self.assertEqual(result["error_code"], "capture_network_resources_exhausted")
                self.assertIn(str(code), result["message"])

    def test_does_not_misclassify_other_failures(self):
        for message in ("[WinError 10061] connection refused", "商品 10048 数据缺失", "timed out"):
            with self.subTest(message=message):
                result = self.describe(ValueError(message))
                self.assertEqual(result, {"error_code": "ValueError", "message": f"采集失败: {message}"})

    def test_handles_exception_chain_cycles(self):
        error = RuntimeError("original error")
        error.__context__ = error
        self.assertEqual(self.describe(error)["error_code"], "RuntimeError")

    def test_recovery_hint_keeps_the_actual_error_visible(self):
        task = {"status": "failed", **self.describe(OSError("[WinError 10048] address in use"))}
        result = self.helpers["_capture_task_recovery_info"](task)
        self.assertTrue(result["can_retry"])
        self.assertTrue(result["user_action_required"])
        self.assertEqual(result["action_hint"], task["message"])


if __name__ == "__main__":
    unittest.main()

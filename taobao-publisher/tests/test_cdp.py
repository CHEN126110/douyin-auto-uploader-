# -*- coding: utf-8 -*-
"""CDP 环境探测测试。

用注入的假 opener 模拟 ``/json/list``，**不连接任何真实浏览器**。
"""

from __future__ import annotations

import json
import unittest
from urllib.error import URLError

from taobao_publish.cdp import (
    CdpError,
    assert_taobao_port,
    is_taobao_port,
    list_targets,
    probe_session,
    select_any_taobao_target,
    select_publish_target,
    snapshot_from_probe,
    taobao_port_of,
)
from taobao_publish.constants import TAOBAO_CDP_LIST_URL, TAOBAO_CDP_PORT


class FakeResponse:
    def __init__(self, payload: str) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return self._payload.encode("utf-8")

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None


def opener_returning(payload: object):
    text = payload if isinstance(payload, str) else json.dumps(payload)

    def _open(request, timeout=None):  # noqa: ANN001
        return FakeResponse(text)

    return _open


def failing_opener(exc: Exception):
    def _open(request, timeout=None):  # noqa: ANN001
        raise exc

    return _open


PUBLISH_TARGET = {
    "type": "page",
    "url": "https://item.upload.taobao.com/sell/ai/category.htm",
    "title": "发布商品",
    "webSocketDebuggerUrl": "ws://127.0.0.1:9334/devtools/page/1",
}


class PortGuardTest(unittest.TestCase):
    def test_rejects_douyin_port(self) -> None:
        """连着 9333（抖店）时必须立刻中止，不能拿它的登录态当淘宝用。"""

        with self.assertRaises(CdpError) as ctx:
            assert_taobao_port("http://127.0.0.1:9333/json/list")
        self.assertEqual(ctx.exception.code, "WRONG_CDP_PORT")

    def test_accepts_taobao_port(self) -> None:
        assert_taobao_port(TAOBAO_CDP_LIST_URL)
        self.assertIn(f":{TAOBAO_CDP_PORT}", TAOBAO_CDP_LIST_URL)

    def test_accepts_the_app_managed_desktop_account_ports(self) -> None:
        """应用给每个店铺账户开独立 profile 与端口（9500-9599），必须放行。

        不放行会导致「用户在应用里登录了淘宝、流水线却说你端口不对」——
        功能看起来实现了，实际一步都走不动。
        """

        for port in (9500, 9502, 9555, 9599):
            with self.subTest(port=port):
                assert_taobao_port(f"http://127.0.0.1:{port}/json/list")
                self.assertTrue(is_taobao_port(f"http://127.0.0.1:{port}/json/list"))

    def test_rejects_ports_outside_both_ranges(self) -> None:
        for port in (9499, 9600, 9222, 9333, 9335, 5001, 1420):
            with self.subTest(port=port):
                self.assertFalse(is_taobao_port(f"http://127.0.0.1:{port}/json/list"))
                with self.assertRaises(CdpError) as ctx:
                    assert_taobao_port(f"http://127.0.0.1:{port}/json/list")
                self.assertEqual(ctx.exception.code, "WRONG_CDP_PORT")

    def test_rejects_addresses_without_a_port(self) -> None:
        for url in ("", "http://127.0.0.1/json/list", "not-a-url", None):
            with self.subTest(url=url):
                self.assertFalse(is_taobao_port(url))
                with self.assertRaises(CdpError):
                    assert_taobao_port(url)

    def test_port_extraction_ignores_the_path(self) -> None:
        """``:9502/json/list`` 里的端口不能被路径里的数字干扰。"""

        self.assertEqual(taobao_port_of("http://127.0.0.1:9502/json/list"), 9502)
        self.assertEqual(taobao_port_of("http://127.0.0.1:9502/json/version"), 9502)
        self.assertIsNone(taobao_port_of("http://127.0.0.1/json/list"))

    def test_list_targets_checks_port_before_connecting(self) -> None:
        called = []

        def _open(request, timeout=None):  # noqa: ANN001
            called.append(request)
            return FakeResponse("[]")

        with self.assertRaises(CdpError):
            list_targets("http://127.0.0.1:9333/json/list", opener=_open)
        self.assertEqual(called, [], "端口校验必须先于任何网络调用")


class ListTargetsTest(unittest.TestCase):
    def test_parses_array(self) -> None:
        targets = list_targets(opener=opener_returning([PUBLISH_TARGET]))
        self.assertEqual(len(targets), 1)

    def test_unreachable_raises_with_hint(self) -> None:
        with self.assertRaises(CdpError) as ctx:
            list_targets(opener=failing_opener(URLError("connection refused")))
        self.assertEqual(ctx.exception.code, "CDP_UNREACHABLE")
        self.assertIn("start-taobao-cdp-chrome.mjs", str(ctx.exception))

    def test_non_json_raises(self) -> None:
        with self.assertRaises(CdpError):
            list_targets(opener=opener_returning("<html>hi</html>"))

    def test_non_array_json_raises(self) -> None:
        with self.assertRaises(CdpError):
            list_targets(opener=opener_returning({"a": 1}))

    def test_non_mapping_entries_are_filtered(self) -> None:
        targets = list_targets(opener=opener_returning([PUBLISH_TARGET, "junk", 5]))
        self.assertEqual(len(targets), 1)


class SelectTargetTest(unittest.TestCase):
    def test_prefers_taobao_publish_page_over_tmall(self) -> None:
        tmall = {"type": "page", "url": "https://item.upload.tmall.com/router/publish.htm"}
        chosen = select_publish_target([tmall, PUBLISH_TARGET])
        self.assertEqual(chosen["url"], PUBLISH_TARGET["url"])

    def test_falls_back_to_tmall_publish_page(self) -> None:
        tmall = {"type": "page", "url": "https://item.upload.tmall.com/router/publish.htm"}
        chosen = select_publish_target([tmall])
        self.assertIsNotNone(chosen)

    def test_ignores_non_page_targets(self) -> None:
        self.assertIsNone(select_publish_target([{**PUBLISH_TARGET, "type": "iframe"}]))

    def test_returns_none_when_absent(self) -> None:
        self.assertIsNone(select_publish_target([{"type": "page", "url": "https://www.baidu.com"}]))

    def test_any_taobao_target_accepts_item_page(self) -> None:
        item = {"type": "page", "url": "https://item.taobao.com/item.htm?id=1"}
        self.assertIsNotNone(select_any_taobao_target([item]))

    def test_any_taobao_target_rejects_foreign_host(self) -> None:
        self.assertIsNone(select_any_taobao_target([{"type": "page", "url": "https://evil.example.com/x"}]))


class ProbeSessionTest(unittest.TestCase):
    def test_ready_when_publish_page_present(self) -> None:
        probe = probe_session(
            opener=opener_returning([PUBLISH_TARGET]), require_publish_page=True
        )
        self.assertTrue(probe.ok)
        self.assertTrue(probe.publish_target_found)
        self.assertFalse(probe.login_required)

    def test_login_page_blocks(self) -> None:
        login = {"type": "page", "url": "https://login.taobao.com/member/login.jhtml"}
        probe = probe_session(opener=opener_returning([login]), require_publish_page=True)
        self.assertFalse(probe.ok)
        codes = {item.code for item in probe.blockers}
        self.assertIn("LOGIN_REQUIRED", codes)

    def test_risk_control_page_blocks_and_takes_priority(self) -> None:
        punish = {"type": "page", "url": "https://sec.taobao.com/punish?x=1"}
        probe = probe_session(opener=opener_returning([punish]))
        self.assertFalse(probe.ok)
        self.assertTrue(probe.risk_control_hit)
        self.assertEqual({item.code for item in probe.blockers}, {"RISK_CONTROL_HIT"})

    def test_cdp_down_blocks(self) -> None:
        probe = probe_session(opener=failing_opener(URLError("refused")))
        self.assertFalse(probe.ok)
        self.assertEqual(probe.blockers[0].code, "CDP_UNREACHABLE")

    def test_require_publish_page_blocks_when_only_item_page_open(self) -> None:
        item = {"type": "page", "url": "https://item.taobao.com/item.htm?id=1"}
        probe = probe_session(opener=opener_returning([item]), require_publish_page=True)
        self.assertFalse(probe.ok)
        self.assertIn("WRONG_PAGE", {entry.code for entry in probe.blockers})

    def test_no_pages_at_all_is_noted(self) -> None:
        probe = probe_session(opener=opener_returning([]))
        self.assertTrue(probe.ok)  # 只读探测本身不算失败
        self.assertTrue(any("没有" in note for note in probe.notes))

    def test_describe_does_not_leak_full_url(self) -> None:
        """探测结果只回 host，不回完整 URL——URL 上可能挂 token 参数。"""

        probe = probe_session(
            opener=opener_returning(
                [{"type": "page", "url": "https://item.taobao.com/x?token=deadbeef"}]
            )
        )
        rendered = json.dumps(probe.to_dict(), ensure_ascii=False)
        self.assertNotIn("deadbeef", rendered)
        self.assertIn("item.taobao.com", rendered)

    def test_snapshot_marks_dom_facts_as_unfilled(self) -> None:
        probe = probe_session(opener=opener_returning([PUBLISH_TARGET]))
        snapshot = snapshot_from_probe(probe)
        self.assertFalse(snapshot.has_workbench_root)
        self.assertTrue(any("Node 探针" in note for note in snapshot.notes))


if __name__ == "__main__":
    unittest.main()

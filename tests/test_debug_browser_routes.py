# -*- coding: utf-8 -*-
"""CDP 调试浏览器接口（src/sidecar/debug_browser_routes.py）回归：直接注册 Blueprint，假浏览器 + 虚拟时钟。

这 10 个 /api/debug/browser/* 接口以前一个测试都没有。重点守住：
1. URL / 方法不变（前端和 MCP 按它们调用）；
2. 没有浏览器、缺必填参数时返回明确的中文 / 英文原因，而不是 500；
3. 参数解析有上下限（limit / timeout / interval），非法值回落到默认值而不是抛错；
4. 查询 / 等待 / 操作失败时会截图留证（artifacts）并记事件，成功时只记事件；
5. 导入本模块不会连带加载浏览器自动化库或 app.py。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from flask import Flask

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from debug_browser_fakes import FakeClock, TickingDatetime, World  # noqa: E402
from src.sidecar import debug_browser_routes as routes_module  # noqa: E402
from src.sidecar import debug_browser_service as svc  # noqa: E402
from src.sidecar.debug_browser_routes import create_debug_browser_blueprint  # noqa: E402

B = "/api/debug/browser"
EXPECTED_ROUTES = {
    ("POST", B + "/ensure"), ("GET", B + "/discover"), ("POST", B + "/launch"), ("GET", B + "/session"),
    ("GET", B + "/context"), ("POST", B + "/query"), ("POST", B + "/wait"), ("POST", B + "/action"),
    ("POST", B + "/capture"), ("GET", B + "/last-error"),
}


@pytest.fixture()
def world(tmp_path):
    return World(tmp_path)


@pytest.fixture()
def api(world, monkeypatch):
    TickingDatetime.reset(1)
    monkeypatch.setattr(svc, "datetime", TickingDatetime)
    clock = FakeClock()
    monkeypatch.setattr(svc, "system_time", clock)
    monkeypatch.setattr(routes_module, "time", clock)             # 操作接口里那一小口 sleep(0.1)
    monkeypatch.setattr(subprocess, "Popen", world.popen)
    service = world.service()
    app = Flask("debug-browser-routes-test")
    app.register_blueprint(create_debug_browser_blueprint(service=service))
    return type("Api", (), {"client": app.test_client(), "app": app, "service": service, "clock": clock,
                            "world": world})


def call(api, method, path, body=None):
    response = api.client.get(path) if method == "GET" else api.client.post(path, json=body)
    assert response.status_code == 200, response.get_data(as_text=True)
    return response.get_json()


def ok(body):
    assert body["success"] is True, body
    return body["data"]


def failed(body, message=None):
    assert body["success"] is False, body
    if message is not None:
        assert body["msg"] == message
    return body.get("data")


def events(api):
    session = api.service.get_session()
    return [event["type"] for event in session["events"]] if session else []


# ====================================================================== 路由表

def test_route_table_is_exactly_the_ten_debug_routes(api):
    rules = {(method, rule.rule) for rule in api.app.url_map.iter_rules() if rule.rule.startswith(B)
             for method in rule.methods if method not in ("HEAD", "OPTIONS")}
    assert rules == EXPECTED_ROUTES


# ====================================================================== 没有浏览器 / 缺参数

@pytest.mark.parametrize("method,path,body,message", (
    ("GET", B + "/context", None, "Browser is not running."),
    ("POST", B + "/query", {"locator": "css:#a"}, "Browser is not running."),
    ("POST", B + "/wait", {"condition": "present", "locator": "css:#a"}, "Browser is not running."),
    ("POST", B + "/action", {"action": "click", "locator": "css:#a"}, "Browser is not running."),
    ("POST", B + "/capture", {}, "Browser is not running."),
    ("POST", B + "/query", {}, "Locator is required."),
    ("POST", B + "/wait", {}, "condition is required."),
    ("POST", B + "/action", {}, "Action is required."),
))
def test_requests_that_cannot_proceed_say_why(api, method, path, body, message):
    failed(call(api, method, path, body), message)
    assert api.world.calls == []                                   # 什么浏览器能力都没碰


def test_status_endpoints_work_before_anything_happened(api):
    data = ok(call(api, "GET", B + "/session"))
    assert data == {"session": None, "browser_instance": None, "last_error": None}
    body = call(api, "GET", B + "/last-error")
    assert body["success"] is True and body["data"] is None
    assert body["msg"] == "No browser debug error report is available."


def test_discover_passes_the_verify_flag_through(api):
    api.world.browsers = [{"debug_address": "127.0.0.1:9333", "pid": 11}]
    for query, expected in (("", True), ("?verify=0", False), ("?verify=false", False), ("?verify=1", True)):
        api.world.calls.clear()
        data = ok(call(api, "GET", B + "/discover" + query))
        assert data["count"] == 1 and data["browsers"][0]["pid"] == 11
        assert api.world.calls == [["discover", expected]]


# ====================================================================== ensure

def test_ensure_without_creating_still_opens_a_session_but_reports_the_missing_browser(api):
    failed(call(api, "POST", B + "/ensure", {"create_browser": False}),
           "Browser is not running. Set create_browser=true to launch it.")
    assert api.service.get_session() is not None                  # 先建会话再找浏览器，失败也留下记录


@pytest.mark.parametrize("body,message", (
    ({"mode": "bogus"}, "Failed to prepare browser: Unsupported browser mode: bogus"),
    ({"mode": "attach"}, "Failed to prepare browser: Attach mode requires debug_address."),
))
def test_ensure_rejects_bad_modes(api, body, message):
    failed(call(api, "POST", B + "/ensure", body), message)


def test_ensure_opens_the_publish_page_for_the_active_profile_and_reuses_it_later(api):
    data = ok(call(api, "POST", B + "/ensure", {"label": "主流程 调试", "limit": 99}))
    assert data["browser"]["created_browser"] is True and data["browser"]["debug_address"] == "127.0.0.1:9333"
    assert data["session"]["label"] == "主流程 调试" and data["session"]["event_count"] == 1
    assert data["snapshot"]["title"] == "抖店-发布商品"
    assert api.world.calls[0] == ["get_page", "https://fxg.jinritemai.com/ffa/g/create", "shop-aaaaaaaa"]
    assert events(api) == ["ensure_browser"]

    again = ok(call(api, "POST", B + "/ensure", {}))
    assert again["browser"]["reused_browser"] is True and again["browser"]["created_browser"] is False
    assert again["session"]["session_id"] == data["session"]["session_id"]       # 没要求新会话就沿用


def test_ensure_can_start_a_new_session_and_navigate(api):
    first = ok(call(api, "POST", B + "/ensure", {}))
    second = ok(call(api, "POST", B + "/ensure", {"new_session": True, "label": "第二个/会话",
                                                   "url": " https://x.test/a ", "navigate": "true"}))
    assert second["session"]["session_id"] != first["session"]["session_id"]
    assert second["browser"]["navigated"] is True
    assert ["tab.get", "https://x.test/a"] in api.world.calls


def test_ensure_attaches_to_an_existing_browser(api):
    api.world.browsers = [{"debug_address": "127.0.0.1:9334", "pid": 22, "browser_name": "Chrome"}]
    data = ok(call(api, "POST", B + "/ensure", {"mode": "attach", "debug_address": "http://127.0.0.1:9334/"}))
    assert data["browser"]["attached_browser"] is True and data["browser"]["debug_address"] == "127.0.0.1:9334"
    assert ["attach", "127.0.0.1:9334", True] in api.world.calls
    assert call(api, "GET", B + "/session")["data"]["browser_instance"]["pid"] == 22


@pytest.mark.parametrize("flag,message", (
    ("open_error", "Failed to prepare browser: 打不开浏览器"),
    ("attach_error", "Failed to prepare browser: 连接调试浏览器失败"),
))
def test_ensure_reports_browser_failures(api, flag, message):
    setattr(api.world, flag, RuntimeError(message.rsplit(": ", 1)[1]))
    body = {"mode": "attach", "debug_address": "127.0.0.1:9334"} if flag == "attach_error" else {}
    failed(call(api, "POST", B + "/ensure", body), message)


# ====================================================================== launch

def test_launch_reuses_a_running_browser_and_attaches_to_it(api):
    api.world.open_ports = {9333}
    data = ok(call(api, "POST", B + "/launch", {"label": "L", "limit": 3}))
    assert data["launched_browser"]["reused_existing"] is True and data["launched_browser"]["port"] == 9333
    assert data["browser"]["attached_browser"] is True and data["snapshot"]["title"] == "抖店-发布商品"
    assert events(api) == ["launch_browser"]
    assert call(api, "GET", B + "/session")["data"]["browser_instance"]["debug_address"] == "127.0.0.1:9333"


def test_launch_starts_a_new_browser_when_the_port_is_free(api):
    api.world.free_ports = {9333}
    api.world.ready_after_popen = True
    api.world.chrome = sys.executable
    data = ok(call(api, "POST", B + "/launch", {"url": "https://x.test/b", "navigate": True,
                                                 "profile_name": " 店铺 A ", "timeout": 5}))
    assert data["launched_browser"]["launched"] is True and data["launched_browser"]["port"] == 9333
    assert data["launched_browser"]["profile_name"] == "店铺 A"
    popen = next(c for c in api.world.calls if c[0] == "popen")
    assert popen[1][-1] == "https://x.test/b"
    assert ["tab.get", "https://x.test/b"] in api.world.calls


@pytest.mark.parametrize("body,flags,message", (
    ({"port": "abc"}, {}, "Failed to launch debug browser: Invalid debug port: abc"),
    ({"port": 70000}, {}, "Failed to launch debug browser: Invalid debug port: 70000"),
    ({"port": 9334}, {}, "Failed to launch debug browser: Port 9334 is already in use by another process."),
    ({}, {}, "Failed to launch debug browser: No available debug port was found in the configured range."),
    ({"port": 9334}, {"open_ports": {9334}, "reuse": False},
     "Failed to launch debug browser: Debug browser is already running at 127.0.0.1:9334."),
    ({"port": 9334}, {"free_ports": {9334}},
     "Failed to launch debug browser: Chrome executable was not found. Provide browser_path explicitly."),
))
def test_launch_failures_are_reported_not_raised(api, body, flags, message):
    if flags.get("reuse") is False:
        body = dict(body, reuse_existing=False)
    api.world.open_ports = flags.get("open_ports", set())
    api.world.free_ports = flags.get("free_ports", set())
    failed(call(api, "POST", B + "/launch", body), message)


def test_launch_timeout_and_early_exit(api):
    api.world.free_ports = {9333}
    api.world.chrome = sys.executable
    api.world.flags["proc_exit"] = 3
    failed(call(api, "POST", B + "/launch", {}), "Failed to launch debug browser: Debug browser exited early with code 3.")
    api.world.flags["proc_exit"] = None
    api.world.popen_started = False
    failed(call(api, "POST", B + "/launch", {"timeout": "bad"}),
           "Failed to launch debug browser: Debug browser did not become ready at 127.0.0.1:9333: timeout")


def test_launch_failing_to_attach_is_reported_as_a_launch_failure(api):
    api.world.free_ports = {9333}
    api.world.ready_after_popen = True
    api.world.chrome = sys.executable
    api.world.flags["tab_fail"] = True
    api.world.set_page("127.0.0.1:9333")
    failed(call(api, "POST", B + "/launch", {}), "Failed to launch debug browser: 标签页已关闭")


# ====================================================================== context

def test_context_reports_page_state_and_optionally_a_query(api):
    api.world.set_page()
    plain = ok(call(api, "GET", B + "/context"))
    assert plain["title"] == "抖店-发布商品" and "query" not in plain and "html_excerpt" not in plain
    detailed = ok(call(api, "GET", B + "/context?include_html=1&locator=%23a&locator_type=css&limit=1"))
    assert detailed["query"]["locator"] == "css:#a" and len(detailed["query"]["matches"]) == 1
    assert detailed["html_excerpt"].startswith("<html>")
    clamped = ok(call(api, "GET", B + "/context?locator=css:%23a&limit=0"))
    assert len(clamped["query"]["matches"]) == 1                     # limit 下限是 1
    assert ok(call(api, "GET", B + "/context?locator=css:.none"))["query"]["match_count"] == 0


def test_context_reports_a_dead_tab(api):
    api.world.set_page()
    api.world.flags["tab_fail"] = True
    failed(call(api, "GET", B + "/context"), "Failed to access browser: 标签页已关闭")


# ====================================================================== query

def test_query_defaults_to_visible_elements_and_records_an_event(api):
    api.service.create_session("q")
    api.world.set_page()
    data = ok(call(api, "POST", B + "/query", {"locator": "css:#a"}))
    assert data["query"]["match_count"] == 1 and data["query"]["matches"][0]["text"] == "第一个"
    assert data["snapshot"]["title"] == "抖店-发布商品"
    assert events(api) == ["query"]
    everything = ok(call(api, "POST", B + "/query", {"locator": "css:#a", "only_visible": False, "limit": 1,
                                                      "include_html": True}))
    assert everything["query"]["match_count"] == 2 and len(everything["query"]["matches"]) == 1
    assert everything["query"]["matches"][0]["outer_html"].startswith("<div")


@pytest.mark.parametrize("body,expected_timeout", (
    ({"timeout": 99}, 5.0), ({"timeout": "x"}, 1.0), ({"timeout": 0}, 1.0), ({"timeout": 0.01}, 0.1),
    ({"timeout": 2}, 2.0),
))
def test_query_clamps_its_timeout(api, body, expected_timeout):
    api.world.set_page()
    ok(call(api, "POST", B + "/query", dict(body, locator="css:#a")))
    assert ["eles", "css:#a", expected_timeout] in api.world.calls


def test_query_failure_leaves_artifacts_behind(api):
    api.world.set_page()
    data = failed(call(api, "POST", B + "/query", {"locator": "css:.boom"}),
                  "Failed to query browser elements: 定位器炸了")
    artifacts = data["artifacts"]
    assert Path(artifacts["screenshot_path"]).exists() and artifacts["screenshot_path"].endswith("_query_failed.png")
    assert Path(artifacts["html_path"]).exists() and Path(artifacts["context_path"]).exists()


def test_query_can_open_the_browser_on_request(api):
    ok(call(api, "POST", B + "/query", {"locator": "css:#a", "create_browser": True}))
    assert api.world.calls[0][0] == "get_page"


# ====================================================================== wait

def test_wait_matches_immediately_and_records_the_payload(api):
    api.service.create_session("w")
    api.world.set_page()
    data = ok(call(api, "POST", B + "/wait", {"condition": " VISIBLE ", "locator": "css:#a", "count": 1,
                                               "include_html": True}))
    result = data["result"]
    assert result["matched"] is True and result["condition"] == "visible" and result["timeout"] == 10.0
    assert result["interval"] == 0.1 and result["only_visible"] is True and result["browser"]["reused_browser"] is True
    assert data["snapshot"]["html_excerpt"].startswith("<html>")
    assert events(api) == ["wait"]


@pytest.mark.parametrize("body,timeout,interval", (
    ({"timeout": 999, "interval": 99}, 30.0, 1.0), ({"timeout": "bad", "interval": "bad"}, 10.0, 0.1),
    ({"timeout": 0.01, "interval": 0.001}, 0.1, 0.02), ({"timeout": 2, "interval": 0.5}, 2.0, 0.5),
))
def test_wait_clamps_timeout_and_interval(api, body, timeout, interval):
    api.world.set_page()
    data = ok(call(api, "POST", B + "/wait", dict(body, condition="url_contains", text="jinritemai")))
    assert data["result"]["timeout"] == timeout and data["result"]["interval"] == interval


def test_wait_timeout_captures_evidence_unless_told_not_to(api):
    api.world.set_page()
    data = failed(call(api, "POST", B + "/wait", {"condition": "visible", "locator": "css:.hidden", "timeout": 0.2}),
                  "Browser wait timed out: visible")
    assert data["result"]["matched"] is False
    assert Path(data["artifacts"]["screenshot_path"]).name.endswith("_wait_visible_timeout.png")
    assert "wait_timeout" in events(api)
    quiet = failed(call(api, "POST", B + "/wait", {"condition": "visible", "locator": "css:.hidden", "timeout": 0.2,
                                                    "capture_on_timeout": False}),
                   "Browser wait timed out: visible")
    assert quiet["artifacts"] is None and quiet["result"]["artifacts"] is None


@pytest.mark.parametrize("body,message", (
    ({"condition": "present"}, "Browser wait failed: locator is required for condition: present"),
    ({"condition": "bogus_condition"}, "Browser wait failed: Unsupported wait condition: bogus_condition"),
    ({"condition": "present", "locator": "css:.boom"}, "Browser wait failed: 定位器炸了"),
))
def test_wait_errors_capture_evidence_and_record_the_error(api, body, message):
    api.world.set_page()
    data = failed(call(api, "POST", B + "/wait", body), message)
    assert Path(data["artifacts"]["screenshot_path"]).exists()
    assert events(api)[-2:] == ["artifact", "wait_error"]


def test_wait_can_navigate_first(api):
    ok(call(api, "POST", B + "/wait", {"condition": "url_contains", "text": "x", "url": "https://fxg.jinritemai.com/n",
                                       "navigate": True, "create_browser": True}))
    assert ["tab.get", "https://fxg.jinritemai.com/n"] in api.world.calls


# ====================================================================== action

@pytest.mark.parametrize("action,expected_log", (
    ("click", ["click", True]), ("hover", ["hover"]), ("scroll", ["scroll.to_center"]), ("clear", ["clear", True]),
))
def test_element_actions_run_on_the_resolved_element(api, action, expected_log):
    api.service.create_session("a")
    api.world.set_page()
    data = ok(call(api, "POST", B + "/action", {"action": action.upper(), "locator": "css:#a"}))
    assert data["result"]["action"] == action and data["result"]["resolved_locator"] == "css:#a"
    assert data["result"]["match_count"] == 1 and data["result"]["index"] == 0
    assert ["element", "css:#a", 0, *expected_log] in api.world.calls
    assert events(api) == ["action"]


def test_click_options_and_input_values(api):
    api.world.set_page()
    ok(call(api, "POST", B + "/action", {"action": "click", "locator": "css:#a", "by_js": False,
                                          "only_visible": False, "index": 1}))
    assert ["element", "css:#a", 1, "click", False] in api.world.calls
    ok(call(api, "POST", B + "/action", {"action": "input", "locator": "css:#a", "value": 123, "clear": False}))
    assert ["element", "css:#a", 0, "input", "123", False] in api.world.calls
    ok(call(api, "POST", B + "/action", {"action": "input", "locator": "css:#a", "value": ""}))
    assert ["element", "css:#a", 0, "input", "", True] in api.world.calls


def test_navigate_action_needs_a_url(api):
    api.world.set_page()
    failed(call(api, "POST", B + "/action", {"action": "navigate"}), "url is required for navigate action.")
    data = ok(call(api, "POST", B + "/action", {"action": "navigate", "url": " https://fxg.jinritemai.com/nav "}))
    assert data["result"]["url"] == "https://fxg.jinritemai.com/nav"
    assert ["tab.get", "https://fxg.jinritemai.com/nav"] in api.world.calls


@pytest.mark.parametrize("body,message", (
    ({"action": "click"}, "Locator is required for this action."),
    ({"action": "input", "locator": "css:#a"}, "value is required for input action."),
    ({"action": "dance", "locator": "css:#a"}, "Unsupported action: dance"),
))
def test_action_validation_errors_do_not_capture_evidence(api, body, message):
    api.world.set_page()
    failed(call(api, "POST", B + "/action", body), message)
    assert api.service.get_session() is None or "action_error" not in events(api)


@pytest.mark.parametrize("locator,index,message", (
    ("css:.none", 0, "Browser action failed: No element matched locator: css:.none"),
    ("css:quirky", 0, "Browser action failed: No element matched locator: css:quirky"),
    ("css:.boom", 0, "Browser action failed: 定位器炸了"),
    ("css:fail", 0, "Browser action failed: 元素操作失败: click"),
    ("css:#a", 9, "Browser action failed: Element index 9 is out of range for locator: css:#a"),
))
def test_failing_actions_capture_evidence_and_record_the_error(api, locator, index, message):
    api.world.set_page()
    data = failed(call(api, "POST", B + "/action", {"action": "click", "locator": locator, "index": index}), message)
    assert Path(data["artifacts"]["screenshot_path"]).name.endswith("_action_click_failed.png")
    assert events(api)[-2:] == ["artifact", "action_error"]


def test_action_clamps_the_index_and_timeout(api):
    api.world.set_page()
    ok(call(api, "POST", B + "/action", {"action": "hover", "locator": "css:#a", "timeout": 99, "index": -5}))
    assert ["eles", "css:#a", 5.0] in api.world.calls
    assert ["element", "css:#a", 0, "hover"] in api.world.calls


# ====================================================================== capture / last-error

def test_capture_writes_artifacts_and_defaults_to_including_html(api):
    api.world.set_page()
    data = ok(call(api, "POST", B + "/capture", {}))
    assert Path(data["html_path"]).exists() and data["screenshot_path"].endswith("_manual_capture.png")
    assert api.service.get_session()["label"] == "manual"
    custom = ok(call(api, "POST", B + "/capture", {"label": "手动 截图", "include_html": 0,
                                                    "session_label": "另一个/会话"}))
    assert custom["html_path"] is None and custom["screenshot_path"].endswith("_手动_截图.png")


def test_capture_reports_each_artifact_failure(api):
    api.world.set_page()
    api.world.flags.update(screenshot_fail=True, html_fail=True)
    data = ok(call(api, "POST", B + "/capture", {}))
    assert data["screenshot_error"] == "截图失败" and data["html_error"] == "读取 html 失败"
    assert data["context_path"] is not None                         # 其它产物不受影响


def test_last_error_is_what_the_pipeline_recorded(api):
    tab = api.world.set_page().get_tab("tab-1")
    api.service.record_automation_error("upload_stage", RuntimeError("上传失败"), "Traceback (fake)", tab=tab,
                                        extra={"record_id": 7})
    body = call(api, "GET", B + "/last-error")
    assert body["msg"] == "Latest browser debug error report loaded."
    assert body["data"]["stage"] == "upload_stage" and body["data"]["extra"] == {"record_id": 7}
    status = ok(call(api, "GET", B + "/session"))
    assert status["last_error"]["stage"] == "upload_stage"
    assert status["session"]["label"] == "upload-error" and status["session"]["event_count"] >= 2


def test_session_status_lists_only_the_most_recent_events(api):
    api.service.create_session("many")
    for index in range(40):
        api.service.append_event("t", "m%d" % index)
    session = ok(call(api, "GET", B + "/session"))["session"]
    assert session["event_count"] == 40 and len(session["events"]) == 30
    assert session["events"][-1]["message"] == "m39"


# ====================================================================== 依赖边界

def test_importing_the_routes_does_not_load_the_browser_stack(tmp_path):
    code = (
        "import sys; sys.path.insert(0, %r); import src.sidecar.debug_browser_routes; "
        "bad = [m for m in ('DrissionPage', 'src.utils', 'PySide6', 'app') if m in sys.modules]; "
        "print('LOADED=' + ','.join(bad))" % str(REPO)
    )
    env = dict(os.environ, DOUYIN_DATA_DIR=str(tmp_path / "data"), PYTHONUTF8="1")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         encoding="utf-8", env=env, check=True)
    assert out.stdout.strip().splitlines()[-1] == "LOADED="

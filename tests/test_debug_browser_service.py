# -*- coding: utf-8 -*-
"""调试浏览器服务（src/sidecar/debug_browser_service.py）回归：假浏览器端口 + 隔离目录 + 虚拟时钟。

守住的几件事：
1. 调试会话 / 事件 / 错误报告 / 浏览器实例这些进程级状态属于服务实例，不同实例互不影响，
   对外返回的都是副本，改副本不会改到内部状态；
2. 会话最多留 8 个、每个会话最多留 200 条事件，超出时丢最旧的；
3. 浏览器怎么打开 / 连接 / 启动全部走注入的端口，服务本身不碰 Chrome、不碰网络；
4. 页面查询 / 等待 / 截图遇到坏元素、坏页面时降级而不是整体崩掉，并如实记下错误；
5. 导入本模块不会连带加载浏览器自动化库或 app.py。
"""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from debug_browser_fakes import FakeClock, TickingDatetime, World  # noqa: E402
from src.sidecar import debug_browser_service as svc  # noqa: E402


@pytest.fixture()
def world(tmp_path):
    return World(tmp_path)


@pytest.fixture()
def clock(monkeypatch):
    fake = FakeClock()
    monkeypatch.setattr(svc, "system_time", fake)
    return fake


@pytest.fixture()
def ticking(monkeypatch):
    TickingDatetime.reset(1)
    monkeypatch.setattr(svc, "datetime", TickingDatetime)
    return TickingDatetime


@pytest.fixture()
def service(world, ticking):
    return world.service()


# ====================================================================== 纯函数

@pytest.mark.parametrize("value,default,expected", (
    (None, True, True), (None, False, False), (True, False, True), (False, True, False),
    ("1", False, True), ("TRUE", False, True), (" yes ", False, True), ("On", False, True),
    ("0", True, False), ("false", True, False), ("", True, False), ("random", True, False),
    (1, False, True), (0, True, False),
))
def test_debug_bool(value, default, expected):
    assert svc.debug_bool(value, default) is expected


@pytest.mark.parametrize("args,expected", (
    (("7", 1), 7), (("x", 3), 3), ((None, 3), 3), ((7.9, 1), 7),
    (("9", 1, 0, 5), 5), (("-3", 1, 0, 5), 0), (("x", 9, 0, 5), 5), ((None, 3, 4), 4),
))
def test_debug_int(args, expected):
    assert svc.debug_int(*args) == expected


@pytest.mark.parametrize("value,expected", (
    ("a//b", "a_b"), ("  Mixed  Case!! ", "mixed_case"), ("", "debug"), (None, "debug"),
    ("店铺 A", "店铺_a"), ("x" * 100, "x" * 64), ("___", "debug"),
))
def test_debug_slug(value, expected):
    assert svc._debug_slug(value) == expected


def test_debug_normalize_text_collapses_whitespace_and_truncates():
    assert svc._debug_normalize_text("  a \n b\t c ") == "a b c"
    assert svc._debug_normalize_text("x" * 10, 4) == "xxxx..."
    assert svc._debug_normalize_text("x" * 10, 0) == "x" * 10
    assert svc._debug_normalize_text(None) == ""


def test_serialize_session_counts_events_and_optionally_includes_the_tail():
    session = {"session_id": "s", "label": "l", "created_at": "c", "updated_at": "u", "artifacts_dir": "d",
               "events": [{"n": i} for i in range(5)]}
    assert svc.serialize_session(None) is None
    plain = svc.serialize_session(session)
    assert plain == {"session_id": "s", "label": "l", "created_at": "c", "updated_at": "u",
                     "artifacts_dir": "d", "event_count": 5}
    assert svc.serialize_session(session, include_events=True, recent_event_count=2)["events"] == [{"n": 3}, {"n": 4}]


# ====================================================================== 会话 / 事件 / 状态

def test_create_session_makes_a_directory_and_becomes_current(world, service):
    session = service.create_session("主流程 调试")
    assert session["label"] == "主流程 调试" and session["events"] == []
    assert Path(session["artifacts_dir"]).is_dir()
    assert Path(session["artifacts_dir"]).parent == world.debug_root
    assert session["session_id"].startswith("主流程_调试_")
    assert service.get_session()["session_id"] == session["session_id"]


def test_get_session_creates_only_on_request(service):
    assert service.get_session() is None
    assert service.get_session(create=False) is None
    created = service.get_session(create=True, label="first")
    assert created["label"] == "first"
    assert service.get_session(create=True, label="ignored")["session_id"] == created["session_id"]


def test_only_the_newest_eight_sessions_are_kept(service):
    ids = [service.create_session("s%d" % index)["session_id"] for index in range(10)]
    kept = set(service._state["sessions"])
    assert kept == set(ids[2:]) and len(kept) == 8
    assert service._state["current_session_id"] == ids[-1]
    assert service.get_session()["session_id"] == ids[-1]


def test_pruning_the_current_session_clears_the_current_pointer(world, monkeypatch):
    # 时钟倒退时「最旧」恰好是刚建的这个会话：被淘汰的是当前会话，指针必须清空而不是指向已删除的会话
    TickingDatetime.reset(-1)
    monkeypatch.setattr(svc, "datetime", TickingDatetime)
    service = world.service()
    for index in range(9):
        service.create_session("s%d" % index)
    assert len(service._state["sessions"]) == 8
    assert service._state["current_session_id"] is None
    assert service.get_session() is None


def test_events_are_copies_and_go_to_the_current_session(service):
    assert service.append_event("query", "没有会话") is None
    session = service.create_session("e")
    event = service.append_event("query", "第一条", data={"a": 1})
    assert event["type"] == "query" and event["message"] == "第一条" and event["data"] == {"a": 1}
    event["data"]["a"] = 99
    assert session["events"][0]["data"] == {"a": 1}                # 返回的是副本
    assert session["updated_at"] == session["events"][0]["timestamp"]
    assert service.append_event("x", "无数据")["data"] == {}


def test_events_can_target_a_specific_session_and_unknown_ids_are_ignored(service):
    first = service.create_session("first")
    service.create_session("second")
    assert service.append_event("t", "m", session_id=first["session_id"]) is not None
    assert len(first["events"]) == 1
    assert service.append_event("t", "m", session_id="nope") is None


def test_a_session_keeps_only_the_newest_200_events(service):
    session = service.create_session("many")
    for index in range(205):
        service.append_event("t", "m%d" % index)
    messages = [event["message"] for event in session["events"]]
    assert len(messages) == 200 and messages[0] == "m5" and messages[-1] == "m204"


def test_last_error_and_browser_instance_are_stored_as_copies(service):
    assert service.get_last_error() is None and service.get_browser_instance() is None
    report = {"stage": "upload", "captured_at": "2026-10-19T08:00:00", "nested": {"k": [1]}}
    service.set_last_error(report)
    report["nested"]["k"].append(2)
    assert service.get_last_error()["nested"] == {"k": [1]}
    fetched = service.get_last_error()
    fetched["nested"]["k"].append(3)
    assert service.get_last_error()["nested"] == {"k": [1]}

    service.set_browser_instance({"debug_address": "127.0.0.1:9333", "pid": 1})
    assert service.get_browser_instance() == {"debug_address": "127.0.0.1:9333", "pid": 1}
    service.set_browser_instance(None)
    assert service.get_browser_instance() is None
    service.set_browser_instance({})
    assert service.get_browser_instance() is None                  # 空实例等于没有


@pytest.mark.parametrize("started_at,expected", (
    (None, True), ("2026-10-19T07:59:59", True), ("2026-10-19T08:00:00", True), ("2026-10-19T08:00:01", False),
))
def test_latest_error_after(service, started_at, expected):
    assert service.latest_error_after(started_at) is None            # 还没有错误报告
    service.set_last_error({"stage": "s", "captured_at": "2026-10-19T08:00:00"})
    assert (service.latest_error_after(started_at) is not None) is expected


def test_latest_error_after_ignores_reports_without_a_capture_time(service):
    service.set_last_error({"stage": "s"})
    assert service.latest_error_after() is not None
    assert service.latest_error_after("2000-01-01T00:00:00") is None


def test_two_services_never_share_state(world, ticking):
    first, second = world.service(), world.service()
    first.create_session("only-first")
    first.set_last_error({"stage": "x"})
    assert second.get_session() is None and second.get_last_error() is None
    assert first._lock is not second._lock


@pytest.mark.parametrize("frozen", (False, True))
def test_artifacts_root_depends_on_the_frozen_flag(world, monkeypatch, frozen):
    if frozen:
        monkeypatch.setattr(sys, "frozen", True, raising=False)
    service = world.service(get_app_root=lambda: str(world.root / "packaged"))
    base = world.root / ("packaged" if frozen else "")
    assert Path(service._debug_root_dir()) == base / "output" / "browser-debug"
    assert (base / "output" / "browser-debug").is_dir()


# ====================================================================== 找浏览器 / 选页面

def test_find_browser_process_matches_normalized_addresses(world, service):
    world.browsers = [{"debug_address": "http://127.0.0.1:9334/", "pid": 22}, {"debug_address": "", "pid": 0}]
    assert service.find_browser_process("127.0.0.1:9334")["pid"] == 22
    assert service.find_browser_process("127.0.0.1:9999") is None
    assert service.find_browser_process("") is None
    assert service.find_browser_process(None) is None
    assert ["discover", False] in world.calls


@pytest.mark.parametrize("attributes,expected", (
    (None, ""), ("normal", "127.0.0.1:9333"), ("broken", ""),
))
def test_gui_page_debug_address(world, service, attributes, expected):
    if attributes:
        world.set_page("127.0.0.1:9333")
    if attributes == "broken":
        world.flags["broken_browser"] = True
    assert service.gui_page_debug_address() == (expected if attributes != "broken" else "")


def test_gui_page_debug_address_falls_back_to_the_page_address(world, service):
    # 页面对象有 browser 但 browser 上没有 address：回落到页面自己的 address
    world.gui.page = types.SimpleNamespace(browser=object(), address="127.0.0.1:9333")
    assert service.gui_page_debug_address() == "127.0.0.1:9333"
    world.gui.page = types.SimpleNamespace(browser=None)
    assert service.gui_page_debug_address() == ""


def test_managed_tab_without_a_browser_is_none_unless_asked_to_create_one(world, service):
    tab, meta = service.get_current_tab()
    assert tab is None
    assert meta == {"mode": "managed", "created_browser": False, "reused_browser": False,
                    "attached_browser": False, "navigated": False, "debug_address": ""}
    assert world.calls == []


def test_managed_tab_creation_uses_the_default_url_and_the_active_profile(world, service):
    service.set_browser_instance({"debug_address": "stale"})
    tab, meta = service.get_current_tab(create_if_missing=True)
    assert tab is not None
    assert world.calls[0] == ["get_page", "https://fxg.jinritemai.com/ffa/g/create", "shop-aaaaaaaa"]
    assert meta["created_browser"] is True and meta["navigated"] is True and meta["reused_browser"] is False
    assert meta["debug_address"] == "127.0.0.1:9333"
    assert service.get_browser_instance() is None                  # 新开浏览器，旧实例信息作废
    assert world.gui.page is not None


def test_managed_tab_is_reused_and_can_navigate(world, service):
    world.set_page("127.0.0.1:9333")
    tab, meta = service.get_current_tab(url="https://x.test/a", navigate=True)
    assert meta["reused_browser"] is True and meta["created_browser"] is False and meta["navigated"] is True
    assert ["tab.get", "https://x.test/a"] in world.calls
    tab, meta = service.get_current_tab(url="https://x.test/ignored")      # 没要求导航就不动页面
    assert meta["navigated"] is False and ["tab.get", "https://x.test/ignored"] not in world.calls


def test_a_closed_tab_is_reopened_only_when_creation_is_allowed(world, service):
    world.set_page("127.0.0.1:9333")
    world.flags["tab_fail"] = True
    with pytest.raises(RuntimeError, match="标签页已关闭"):
        service.get_current_tab()
    world.flags.pop("tab_fail")
    world.flags["tab_fail_once"] = True
    service.set_browser_instance({"debug_address": "stale"})
    tab, meta = service.get_current_tab(create_if_missing=True)
    assert tab is not None and meta["created_browser"] is True and meta["reused_browser"] is False
    assert service.get_browser_instance() is None


def test_open_failures_propagate(world, service):
    world.open_error = RuntimeError("打不开浏览器")
    with pytest.raises(RuntimeError, match="打不开浏览器"):
        service.get_current_tab(create_if_missing=True)


def test_unsupported_modes_and_missing_attach_address_are_rejected(world, service):
    with pytest.raises(Exception, match="Unsupported browser mode: bogus"):
        service.get_current_tab(mode="bogus")
    with pytest.raises(Exception, match="Attach mode requires debug_address"):
        service.get_current_tab(mode="attach")
    with pytest.raises(Exception, match="Attach mode requires debug_address"):
        service.get_current_tab(mode="attach", debug_address="  ")


def test_attach_connects_once_per_address_and_records_the_instance(world, service):
    world.browsers = [{"debug_address": "127.0.0.1:9334", "pid": 22, "browser_name": "Chrome",
                       "exe": "C:/chrome.exe", "user_data_dir": "C:/ud", "profile_directory": "Default"}]
    tab, meta = service.get_current_tab(mode="attach", debug_address="http://127.0.0.1:9334/")
    assert meta["attached_browser"] is True and meta["debug_address"] == "127.0.0.1:9334"
    assert ["attach", "127.0.0.1:9334", True] in world.calls
    instance = service.get_browser_instance()
    assert instance["pid"] == 22 and instance["browser_path"] == "C:/chrome.exe"
    assert instance["source"] == "attach" and instance["user_data_dir"] == "C:/ud"

    world.calls.clear()
    tab, meta = service.get_current_tab(mode="attach", debug_address="127.0.0.1:9334")
    assert meta["attached_browser"] is False and not [c for c in world.calls if c[0] == "attach"]
    tab, meta = service.get_current_tab(mode="attach", debug_address="127.0.0.1:9335")
    assert meta["attached_browser"] is True
    assert service.get_browser_instance()["debug_address"] == "127.0.0.1:9335"
    assert service.get_browser_instance().get("pid") is None        # 换了地址就不沿用旧实例的 pid


def test_attach_always_requires_an_already_running_browser(world, service):
    service.get_current_tab(mode="attach", debug_address="127.0.0.1:9334", existing_only=False)
    assert ["attach", "127.0.0.1:9334", True] in world.calls


def test_attach_failures_propagate_even_when_creation_is_allowed(world, service):
    world.attach_error = RuntimeError("连接调试浏览器失败")
    with pytest.raises(RuntimeError, match="连接调试浏览器失败"):
        service.get_current_tab(mode="attach", debug_address="127.0.0.1:9334", create_if_missing=True)
    world.attach_error = None
    world.set_page("127.0.0.1:9334")
    world.flags["tab_fail"] = True
    with pytest.raises(RuntimeError, match="标签页已关闭"):
        service.get_current_tab(mode="attach", debug_address="127.0.0.1:9334", create_if_missing=True)


# ====================================================================== 启动可连接的调试浏览器

@pytest.fixture()
def launcher(world, service, clock, monkeypatch):
    monkeypatch.setattr(subprocess, "Popen", world.popen)
    world.chrome = sys.executable                                  # 一个真实存在的文件当作 Chrome
    return service


def test_launch_reuses_a_running_browser_on_an_explicit_port(world, launcher):
    world.open_ports = {9334}
    world.browsers = [{"debug_address": "127.0.0.1:9334", "pid": 22, "browser_name": "Chrome", "exe": "chrome.exe",
                       "user_data_dir": "C:/ud", "profile_directory": "Default"}]
    result = launcher.launch_attachable_browser(port="9334")
    assert result["reused_existing"] is True and result["launched"] is False
    assert result["pid"] == 22 and result["user_data_dir"] == "C:/ud" and result["port"] == 9334
    assert result["url"] == "about:blank" and result["profile_name"] == "default"
    assert not [c for c in world.calls if c[0] == "popen"]


def test_launch_refuses_to_reuse_when_told_not_to(world, launcher):
    world.open_ports = {9334}
    with pytest.raises(Exception, match="already running at 127.0.0.1:9334"):
        launcher.launch_attachable_browser(port=9334, reuse_existing=False)


@pytest.mark.parametrize("port,message", (("abc", "Invalid debug port: abc"), (70000, "Invalid debug port: 70000"),
                                          (0, "Invalid debug port: 0"), (-1, "Invalid debug port: -1")))
def test_launch_rejects_invalid_ports(launcher, port, message):
    with pytest.raises(Exception, match=message):
        launcher.launch_attachable_browser(port=port)


def test_launch_rejects_a_port_held_by_another_process(world, launcher):
    with pytest.raises(Exception, match="Port 9334 is already in use by another process"):
        launcher.launch_attachable_browser(port=9334)


def test_launch_picks_the_first_free_port_when_none_is_given(world, launcher):
    world.free_ports = {9337}
    world.ready_after_popen = True
    result = launcher.launch_attachable_browser(url=" https://x.test/a ", profile_name="店铺 A!")
    assert result["port"] == 9337 and result["launched"] is True and result["reused_existing"] is False
    assert result["url"] == "https://x.test/a" and result["profile_name"] == "店铺 A!"
    popen = next(c for c in world.calls if c[0] == "popen")
    assert popen[1][1] == "--remote-debugging-port=9337"
    expected_dir = str(world.debug_root / "profiles" / "店铺_a")
    assert popen[1][2] == "--user-data-dir=" + os.path.abspath(expected_dir)
    assert popen[1][3:] == ["--no-first-run", "--no-default-browser-check", "https://x.test/a"]
    assert Path(expected_dir).is_dir()
    assert result["pid"] == 4321 and result["browser_name"] == "Chrome" and result["browser_path"] == sys.executable


def test_launch_prefers_an_already_running_port_while_scanning(world, launcher):
    world.open_ports = {9335}
    result = launcher.launch_attachable_browser()
    assert result["port"] == 9335 and result["reused_existing"] is True


def test_launch_without_any_free_port_fails_clearly(launcher):
    with pytest.raises(Exception, match="No available debug port was found in the configured range"):
        launcher.launch_attachable_browser()


def test_launch_needs_a_browser_executable(world, launcher):
    world.free_ports = {9333}
    world.chrome = None
    with pytest.raises(Exception, match="Chrome executable was not found"):
        launcher.launch_attachable_browser()
    with pytest.raises(Exception, match="Browser executable was not found"):
        launcher.launch_attachable_browser(browser_path=str(world.root / "missing.exe"))
    world.chrome = str(world.root / "detected-but-missing.exe")
    with pytest.raises(Exception, match="Chrome executable was not found"):
        launcher.launch_attachable_browser()


def test_launch_reports_an_early_exit_and_a_timeout(world, launcher, clock):
    world.free_ports = {9333}
    world.flags["proc_exit"] = 3
    with pytest.raises(Exception, match="exited early with code 3"):
        launcher.launch_attachable_browser()
    world.flags["proc_exit"] = None
    world.popen_started = False
    world.verify_error = "连接被拒绝"
    with pytest.raises(Exception, match="did not become ready at 127.0.0.1:9333: 连接被拒绝"):
        launcher.launch_attachable_browser(timeout=1)
    assert ["proc.kill"] in world.calls
    assert clock.now >= 1000 + 1                                   # 虚拟时钟走满了超时


def test_launch_timeout_survives_a_process_that_cannot_be_killed(world, launcher):
    world.free_ports = {9333}
    world.flags["kill_fail"] = True
    with pytest.raises(Exception, match="did not become ready at 127.0.0.1:9333: timeout"):
        launcher.launch_attachable_browser(timeout=1)


def test_launch_uses_a_custom_user_data_dir(world, launcher):
    world.free_ports = {9333}
    world.ready_after_popen = True
    custom = world.root / "custom-ud"
    result = launcher.launch_attachable_browser(user_data_dir=str(custom), browser_path=sys.executable)
    assert result["user_data_dir"] == os.path.abspath(str(custom)) and custom.is_dir()


# ====================================================================== 页面快照 / 截图 / 错误报告

def test_snapshot_context_combines_page_bits_session_and_query(world, service):
    tab = world.set_page().get_tab("tab-1")
    session = service.create_session("snap")
    service.append_event("t", "m")
    context = service.snapshot_context(tab, locator="css:#a", locator_type="css", limit=1, include_html=True)
    assert context["url"] == "https://fxg.jinritemai.com/ffa/g/create" and context["title"] == "抖店-发布商品"
    assert context["ready_state"] == "complete" and context["scroll"] == {"x": 0, "y": 12}
    assert context["visible_fields"][0]["field_id"] == "商品标题"
    assert context["visible_controls"][0]["text"] == "保存" and context["visible_overlays"] == []
    assert context["upload_signals"] == {"upload_busy": False}
    assert context["session"]["session_id"] == session["session_id"] and context["session"]["event_count"] == 1
    assert context["query"]["match_count"] == 2 and len(context["query"]["matches"]) == 1
    assert context["html_excerpt"].startswith("<html>")


def test_snapshot_context_degrades_when_the_page_cannot_be_read(world, service):
    tab = world.set_page().get_tab("tab-1")
    world.flags.update(snapshot_fail=True, html_fail=True)
    context = service.snapshot_context(tab, include_html=True)
    assert context["session"] is None and context["scroll"] == {"x": 0, "y": 0}
    assert context["url"] == "https://fxg.jinritemai.com/ffa/g/create"    # 回落到 tab.url
    assert context["visible_fields"] == [] and context["html_excerpt"] == ""
    assert "query" not in context


def test_capture_artifacts_writes_screenshot_context_and_html(world, service):
    tab = world.set_page().get_tab("tab-1")
    artifacts = service.capture_artifacts(tab, label="My Shot!", include_html=True, session_label="cap")
    assert Path(artifacts["screenshot_path"]).read_bytes().startswith(b"\x89PNG")
    assert artifacts["screenshot_path"].endswith("_my_shot.png")
    assert json.loads(Path(artifacts["context_path"]).read_text(encoding="utf-8"))["title"] == "抖店-发布商品"
    assert "fake page" in Path(artifacts["html_path"]).read_text(encoding="utf-8")
    session = service.get_session()
    assert session["label"] == "cap" and artifacts["session_id"] == session["session_id"]
    assert session["events"][-1]["type"] == "artifact"


def test_capture_artifacts_without_html_or_tab(world, service):
    tab = world.set_page().get_tab("tab-1")
    artifacts = service.capture_artifacts(tab, label="no html", include_html=False)
    assert artifacts["html_path"] is None and artifacts["screenshot_path"] and artifacts["context_path"]
    bare = service.capture_artifacts(None, label="no tab")
    assert bare["screenshot_path"] is None and bare["context_path"] is None and bare["html_path"] is None
    assert [e["type"] for e in service.get_session()["events"]] == ["artifact", "artifact"]


def test_capture_artifacts_records_each_failure_without_stopping(world, service):
    tab = world.set_page().get_tab("tab-1")
    world.flags.update(screenshot_fail=True, html_fail=True, snapshot_fail=True, url_fail=True)
    artifacts = service.capture_artifacts(tab, label="all broken")
    assert artifacts["screenshot_path"] is None and artifacts["screenshot_error"] == "截图失败"
    assert artifacts["context_path"] is None and artifacts["context_error"] == "地址不可读"
    assert artifacts["html_path"] is None and artifacts["html_error"] == "读取 html 失败"


def test_record_automation_error_builds_a_full_report(world, service):
    tab = world.set_page().get_tab("tab-1")
    report = service.record_automation_error("上传/主图", RuntimeError("上传失败"), "Traceback (fake)", tab=tab,
                                             extra={"record_id": 7})
    assert report["stage"] == "上传/主图" and report["error"] == "上传失败" and report["traceback"] == "Traceback (fake)"
    assert report["extra"] == {"record_id": 7} and report["page"]["title"] == "抖店-发布商品"
    assert report["session"]["label"] == "upload-error"
    assert Path(report["report_path"]).name.endswith("_上传_主图_report.json")
    on_disk = json.loads(Path(report["report_path"]).read_text(encoding="utf-8"))
    assert on_disk["stage"] == "上传/主图" and "report_path" not in on_disk       # 落盘的是写入前的快照
    assert service.get_last_error()["stage"] == "上传/主图"
    assert service.latest_error_after("2000-01-01T00:00:00") is not None
    events = [e["type"] for e in service.get_session()["events"]]
    assert events[-1] == "automation_error" and "artifact" in events


def test_record_automation_error_without_a_tab_has_no_page_snapshot(world, service):
    report = service.record_automation_error("stage", "plain text error", "tb")
    assert report["page"] is None and report["error"] == "plain text error" and report["extra"] == {}
    assert report["artifacts"]["screenshot_path"] is None


def test_record_automation_error_survives_a_vanished_artifacts_directory(world, service):
    tab = world.set_page().get_tab("tab-1")
    session = service.create_session("upload-error")
    import shutil
    shutil.rmtree(session["artifacts_dir"])
    report = service.record_automation_error("stage", RuntimeError("x"), "tb", tab=tab)
    assert "report_path" not in report and "report_path_error" in report
    assert report["artifacts"]["screenshot_error"] and report["artifacts"]["context_error"]
    assert service.get_last_error()["stage"] == "stage"            # 内存里的报告仍然在


# ====================================================================== 元素查询 / 等待

def test_normalize_locator():
    assert svc._normalize_debug_locator("#a", "css") == "css:#a"
    assert svc._normalize_debug_locator("css:#a", "CSS") == "css:#a"
    assert svc._normalize_debug_locator("//div", "xpath") == "xpath://div"
    assert svc._normalize_debug_locator("xpath://div", "xpath") == "xpath://div"
    assert svc._normalize_debug_locator("  tag:div ", "raw") == "tag:div"
    assert svc._normalize_debug_locator("tag:div", None) == "tag:div"
    with pytest.raises(Exception, match="Locator is required"):
        svc._normalize_debug_locator("   ")


def test_query_elements_filters_visibility_and_limits_the_summaries(world):
    tab = world.set_page().get_tab("tab-1")
    # 函数本身默认不过滤可见性（接口层才默认只看可见的），所以这里两种都要显式验证
    everything = svc.query_elements(tab, "#a", "css")
    assert everything["match_count"] == 2 and len(everything["matches"]) == 2
    visible = svc.query_elements(tab, "#a", "css", only_visible=True)
    assert visible["locator"] == "css:#a" and visible["match_count"] == 1 and len(visible["matches"]) == 1
    assert visible["matches"][0]["text"] == "第一个" and visible["matches"][0]["displayed"] is True
    limited = svc.query_elements(tab, "#a", "css", only_visible=False, limit=1)
    assert limited["match_count"] == 2 and len(limited["matches"]) == 1
    detailed = svc.query_elements(tab, "#a", "css", only_visible=False, include_html=True)
    assert detailed["matches"][1]["tag"] == "span" and detailed["matches"][1]["outer_html"].startswith("<span")
    assert svc.query_elements(tab, "css:.none")["match_count"] == 0
    assert svc.query_elements(tab, "css:.hidden", only_visible=True)["match_count"] == 0
    assert svc.query_elements(tab, "css:.hidden")["match_count"] == 1
    assert ["eles", "css:#a", 1.0] in world.calls


def test_query_elements_truncates_long_text_and_degrades_on_broken_elements(world):
    tab = world.set_page().get_tab("tab-1")
    long_text = svc.query_elements(tab, "css:long", only_visible=False)["matches"][0]["text"]
    assert long_text == "长" * 240 + "..."
    skipped = svc.query_elements(tab, "css:quirky", only_visible=True)      # 可见性读不出的元素按不可见处理
    assert skipped["match_count"] == 0
    broken = svc.query_elements(tab, "css:quirky", only_visible=False, include_html=True)["matches"][0]
    assert broken["text"] == "" and broken["tag"] == "" and broken["displayed"] is False
    assert broken["outer_html"] == "" and broken["id"] == ""
    with pytest.raises(RuntimeError, match="定位器炸了"):
        svc.query_elements(tab, "css:boom")


def test_get_target_element(world):
    tab = world.set_page().get_tab("tab-1")
    element, locator, count = svc.get_target_element(tab, "#a", "css")
    assert (element.index, locator, count) == (0, "css:#a", 1)             # 只看可见的：只剩第一个
    element, locator, count = svc.get_target_element(tab, "#a", "css", index=1, only_visible=False)
    assert (element.index, count) == (1, 2)
    with pytest.raises(Exception, match="Element index 5 is out of range for locator: css:#a"):
        svc.get_target_element(tab, "#a", "css", index=5)
    with pytest.raises(Exception, match="Element index -1 is out of range"):
        svc.get_target_element(tab, "#a", "css", index=-1)
    with pytest.raises(Exception, match="No element matched locator: css:.none"):
        svc.get_target_element(tab, ".none", "css")
    with pytest.raises(Exception, match="No element matched locator: css:quirky"):
        svc.get_target_element(tab, "quirky", "css")


@pytest.mark.parametrize("condition,kwargs,matched", (
    # present / absent 数的是全部匹配（含不可见的）；visible / hidden 才按可见性过滤
    ("present", {"locator": "css:#a"}, True), ("present", {"locator": "css:#a", "count": 2}, True),
    ("present", {"locator": "css:#a", "count": 3}, False),
    ("present", {"locator": "css:.none"}, False), ("present", {"locator": "css:.hidden"}, True),
    ("visible", {"locator": "css:#a"}, True), ("visible", {"locator": "css:#a", "count": 2}, False),
    ("visible", {"locator": "css:.hidden"}, False),
    ("absent", {"locator": "css:.none"}, True), ("absent", {"locator": "css:#a"}, False),
    ("hidden", {"locator": "css:.hidden"}, True), ("hidden", {"locator": "css:#a"}, False),
    ("hidden", {"locator": "css:.hidden", "only_visible": False}, False),
    ("url_contains", {"expected_text": "jinritemai"}, True), ("url_contains", {"expected_text": "nope"}, False),
    ("url_contains", {}, True), ("title_contains", {"expected_text": "抖店"}, True),
    ("title_contains", {"expected_text": "淘宝"}, False), ("title_contains", {}, True),
    ("ready_state", {}, True), ("ready_state", {"expected_text": "complete"}, True),
    ("ready_state", {"expected_text": "loading"}, False),
))
def test_wait_conditions(world, clock, condition, kwargs, matched):
    tab = world.set_page().get_tab("tab-1")
    result, state = svc.wait_for_condition(tab, condition, timeout=0.2, interval=0.05, **kwargs)
    assert result is matched and state["matched"] is matched and state["condition"] == condition
    assert state["url"] == "https://fxg.jinritemai.com/ffa/g/create" and state["ready_state"] == "complete"
    if matched:
        assert clock.sleeps == []                                 # 立刻命中，不睡
    else:
        assert clock.sleeps and clock.now >= 1000.2               # 等满超时才放弃


def test_wait_reports_the_query_that_decided_it(world, clock):
    tab = world.set_page().get_tab("tab-1")
    _, state = svc.wait_for_condition(tab, "present", locator="css:#a", count=3, timeout=0.1)
    assert state["observed_count"] == 2 and state["query"]["match_count"] == 2
    assert state["count"] == 3 and state["only_visible"] is True and state["matched"] is False


def test_wait_rejects_unknown_conditions_and_missing_locators(world, clock):
    tab = world.set_page().get_tab("tab-1")
    with pytest.raises(Exception, match="Unsupported wait condition: bogus"):
        svc.wait_for_condition(tab, " BOGUS ", timeout=0.1)
    for condition in ("present", "visible", "absent", "hidden"):
        with pytest.raises(Exception, match=f"locator is required for condition: {condition}"):
            svc.wait_for_condition(tab, condition, timeout=0.1)
    with pytest.raises(RuntimeError, match="定位器炸了"):
        svc.wait_for_condition(tab, "present", locator="css:.boom", timeout=0.1)


def test_wait_degrades_when_the_page_cannot_report_its_state(world, clock):
    tab = world.set_page().get_tab("tab-1")
    world.flags.update(url_fail=True, title_fail=True, snapshot_fail=True)
    _, state = svc.wait_for_condition(tab, "url_contains", timeout=0.1)
    assert state["url"] == "" and state["title"] == "" and state["ready_state"] == "" and state["matched"] is False
    _, state = svc.wait_for_condition(tab, "ready_state", timeout=0.1)
    assert state["matched"] is False


def test_wait_never_busy_loops(world, clock):
    tab = world.set_page().get_tab("tab-1")
    svc.wait_for_condition(tab, "present", locator="css:.none", timeout=0, interval=0)
    assert all(0.02 <= pause <= 1.0 for pause in clock.sleeps)    # interval 被限制在 [0.02, 1.0]
    clock.sleeps.clear()
    svc.wait_for_condition(tab, "present", locator="css:.none", timeout=0.5, interval=99)
    assert clock.sleeps and max(clock.sleeps) == 1.0


# ====================================================================== 依赖边界

def test_importing_the_service_does_not_load_the_browser_stack(tmp_path):
    code = (
        "import sys; sys.path.insert(0, %r); import src.sidecar.debug_browser_service; "
        "bad = [m for m in ('DrissionPage', 'src.utils', 'PySide6', 'app') if m in sys.modules]; "
        "print('LOADED=' + ','.join(bad))" % str(REPO)
    )
    env = dict(os.environ, DOUYIN_DATA_DIR=str(tmp_path / "data"), PYTHONUTF8="1")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         encoding="utf-8", env=env, check=True)
    assert out.stdout.strip().splitlines()[-1] == "LOADED="


def test_the_port_is_a_frozen_dataclass(world):
    port = world.port()
    with pytest.raises(Exception):
        port.host = "0.0.0.0"
    assert copy.copy(port) == port

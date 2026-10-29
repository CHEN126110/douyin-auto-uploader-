# -*- coding: utf-8 -*-
"""店铺会话接口（src/sidecar/shop_routes.py + shop_service.py）回归：直接注册 Blueprint。

账户注册表用**真实**的 ``src.shop_session``，落在 pytest 临时目录（``DOUYIN_DATA_DIR``），所以添加 / 切换 / 移除账户、
实测身份写回注册表这些逻辑是真跑的；浏览器、CDP 读身份、发布任务字典是假的。重点守住：

1. 浏览器实测到的店铺只能记到「这个浏览器目录所属的账户」头上，属于别的账户时报冲突、不写注册表；
2. 切换 / 添加账户必须丢弃旧浏览器句柄，且有发布任务在跑时一律拒绝（409）；
3. 移除账户的两档语义：默认只摘记录，``purge`` 才连登录资料目录一起删；默认空占位与「有身份的默认账户」区别对待；
4. 参数校验严格：非法请求不得改动注册表、不得打开浏览器；
5. 导入这些模块不会连带加载浏览器自动化库或 app.py。
"""

from __future__ import annotations

import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace

import pytest
from flask import Flask

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from src import shop_session  # noqa: E402
from src.sidecar.shop_accounts import ShopAccountGuard  # noqa: E402
from src.sidecar.shop_routes import create_shop_blueprint  # noqa: E402
from src.sidecar.shop_service import ShopBrowserPort, ShopSessionService  # noqa: E402

DEFAULT = shop_session.DEFAULT_PROFILE_NAME
DOUYIN, TAOBAO, XHS = "shop-aaaaaaaa", "taobao-bbbbbbbb", "xhs-cccccccc"
DOUYIN_HOME = "https://fxg.jinritemai.com/ffa/mshop/homepage/index"
TAOBAO_HOME = "https://item.upload.taobao.com/sell/ai/category.htm"
XHS_HOME = "https://ark.xiaohongshu.com/app-system/home"
LOGGED_IN = {"status": "logged_in", "shop_id": "1001", "shop_name": "甲店", "page_url": "https://fxg/home",
             "error": None, "detail": None}


class FakeUuid:
    """让新建账户的目录名可预测：<前缀>-00000001、<前缀>-00000002……"""

    def __init__(self):
        self.counter = 0

    def uuid4(self):
        self.counter += 1
        return SimpleNamespace(hex="%08x" % self.counter + "0" * 24)


def entry(slug, platform, label=None, **extra):
    base = {"profile_name": slug, "platform": platform, "label": label, "created_at": "2026-10-01T09:00:00",
            "shop_id": None, "shop_name": None, "last_seen_at": None, "seen_count": 0}
    base.update(extra)
    return base


class Env:
    """一次测试里的假外部世界：浏览器端口、发布任务、CDP 读身份。"""

    def __init__(self, tmp_path):
        self.root = tmp_path
        self.gui = SimpleNamespace(page=None)
        self.opened = []                 # (url, profile_name)
        self.open_error = None
        self.resets = []                 # 每次丢弃调试浏览器实例记一笔
        self.processes = {}              # 调试地址 -> 进程信息
        self.reusable = {"selected_browser": None, "eligible_browsers": [], "targets_by_address": {}}
        self.reusable_calls = []
        self.reusable_error = None
        self.running = False
        self.identity = {"status": "no_browser"}
        self.identity_calls = []
        self.freight = {"status": "ok", "templates": []}
        self.page_address = "127.0.0.1:9601"

    # ---- 端口实现
    def open_page(self, url, profile_name=None):
        self.opened.append((url, profile_name))
        if self.open_error is not None:
            raise self.open_error
        return SimpleNamespace(address=self.page_address)

    def gui_address(self):
        return self.gui.page.address if self.gui.page else ""

    def find_reusable(self, verify=False, preferred_profile=None):
        self.reusable_calls.append(verify)
        if self.reusable_error is not None:
            raise self.reusable_error
        return self.reusable

    def profile_dir(self, slug):
        return str(self.root / slug)


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DOUYIN_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(shop_session, "uuid", FakeUuid())
    shop_session.save_registry({
        "active_profile": DOUYIN,
        "profiles": {
            DOUYIN: entry(DOUYIN, "douyin", "甲店备注", shop_id="1001", shop_name="甲店",
                          last_seen_at="2026-10-02T10:00:00", seen_count=2),
            TAOBAO: entry(TAOBAO, "taobao", "乙淘宝"),
            XHS: entry(XHS, "xiaohongshu", "丙小红书", last_seen_at="2026-10-03T10:00:00"),
        },
    })
    state = Env(tmp_path)

    def read_identity(debug_address, platform="douyin", timeout=10.0):
        state.identity_calls.append((debug_address, platform, timeout))
        if isinstance(state.identity, Exception):
            raise state.identity
        return dict(state.identity)

    monkeypatch.setattr(shop_session, "read_account_identity", read_identity)
    monkeypatch.setattr(shop_session, "read_freight_templates",
                        lambda address, timeout=10.0: dict(state.freight))
    monkeypatch.setattr(shop_session, "read_taobao_freight_templates",
                        lambda address, timeout=10.0: dict(state.freight))
    return state


def build(env, shop=shop_session, route_shop=None):
    guard = ShopAccountGuard(shop_session=shop, has_running_publish_tasks=lambda: env.running)
    service = ShopSessionService(
        accounts=guard,
        browser=ShopBrowserPort(
            page_state=lambda: env.gui,
            open_page=env.open_page,
            normalize_address=lambda value: str(value or "").strip(),
            gui_page_debug_address=env.gui_address,
            find_browser_process=lambda address: env.processes.get(address),
            find_reusable_browser=env.find_reusable,
            set_debug_browser_instance=env.resets.append,
            host="127.0.0.1", shop_port_start=9500, shop_port_end=9503,
        ),
        shop_session=shop,
    )
    app = Flask("shop-routes-test")
    app.register_blueprint(create_shop_blueprint(accounts=guard, service=service,
                                                 shop_session=route_shop or shop))
    return SimpleNamespace(app=app, client=app.test_client(), guard=guard, service=service)


@pytest.fixture()
def api(env):
    return build(env)


def registry():
    return shop_session.load_registry()


def selected(address, user_data_dir):
    browser = {"debug_address": address, "user_data_dir": user_data_dir, "profile_directory": "Default"}
    return {"selected_browser": browser, "eligible_browsers": [browser],
            "targets_by_address": {address: [{"type": "page", "url": DOUYIN_HOME}]}}


def get_json(response, status=200):
    assert response.status_code == status, response.get_data(as_text=True)
    return response.get_json()


# ====================================================================== 账户列表

def test_route_table_is_exactly_the_seven_shop_routes(api):
    rules = {(rule.rule, tuple(sorted(m for m in rule.methods if m not in ("HEAD", "OPTIONS"))))
             for rule in api.app.url_map.iter_rules() if rule.rule.startswith("/api/")}
    assert rules == {
        ("/api/shop/current", ("GET",)), ("/api/shop/freight-templates", ("GET",)),
        ("/api/shop/profiles", ("GET",)), ("/api/shop/add", ("POST",)),
        ("/api/shop/switch", ("POST",)), ("/api/shop/forget", ("POST",)),
        ("/api/shop/restore", ("POST",)),
    }


def test_profiles_lists_every_account_with_its_platform_and_directory(env, api):
    body = get_json(api.client.get("/api/shop/profiles"))
    assert body["success"] is True and body["msg"] == "店铺列表已加载"
    data = body["data"]
    assert data["active_profile"] == DOUYIN and data["platform"] == "douyin"
    assert data["registry_path"] == shop_session.registry_path()
    by_name = {item["profile_name"]: item for item in data["profiles"]}
    assert set(by_name) == {DOUYIN, TAOBAO, XHS}
    assert by_name[TAOBAO]["platform"] == "taobao" and by_name[XHS]["platform"] == "xiaohongshu"
    assert by_name[DOUYIN]["profile_dir"] == env.profile_dir(DOUYIN)
    assert by_name[DOUYIN]["is_active"] is True and by_name[TAOBAO]["is_active"] is False
    assert env.opened == [] and env.identity_calls == []        # 只读列表，不碰浏览器


def test_profiles_failure_is_reported_not_swallowed(env, api, monkeypatch):
    monkeypatch.setattr(shop_session, "list_profiles", lambda: (_ for _ in ()).throw(RuntimeError("注册表读取失败")))
    body = get_json(api.client.get("/api/shop/profiles"))
    assert body["success"] is False and body["msg"] == "读取店铺列表失败: 注册表读取失败"


# ====================================================================== 当前登录的店铺

def test_current_without_any_browser_says_not_logged_in(env, api):
    body = get_json(api.client.get("/api/shop/current"))
    assert body["success"] is True
    data = body["data"]
    assert data["status"] == "no_browser" and data["browser_source"] == "none"
    assert data["error"] == "尚未登录，点左上角账户菜单选择该账户即可打开登录页"
    assert data["active_profile"] == DOUYIN and data["active_profile_label"] == "甲店"
    assert data["last_seen_shop_id"] == "1001" and data["last_seen_shop_name"] == "甲店"
    assert data["profile_dir"] == env.profile_dir(DOUYIN)
    assert env.identity_calls == []                                  # 没有浏览器就不读身份


def test_current_records_the_measured_shop_under_the_browsers_own_account(env, api):
    env.reusable = selected("127.0.0.1:9501", env.profile_dir(DOUYIN))
    env.identity = dict(LOGGED_IN)
    data = get_json(api.client.get("/api/shop/current"))["data"]
    assert data["status"] == "logged_in" and data["shop_id"] == "1001" and data["shop_name"] == "甲店"
    assert data["browser_source"] == "reusable_browser" and data["debug_address"] == "127.0.0.1:9501"
    assert data["owner_profile"] == DOUYIN and data["observation"] == "confirmed"
    assert data["profile_match"] is True
    assert env.identity_calls == [("127.0.0.1:9501", "douyin", 6.0)]
    assert env.reusable_calls == [True]
    assert registry()["profiles"][DOUYIN]["seen_count"] == 3        # 实测写回了注册表


def test_xiaohongshu_shop_name_is_saved_and_listed_as_verified(env, api):
    """千帆实时读到店铺名后，账户列表不能再退回默认名和「未验证登录」。"""
    registry_now = registry()
    registry_now["active_profile"] = XHS
    shop_session.save_registry(registry_now)
    env.gui.page = SimpleNamespace(address="127.0.0.1:9501")
    env.processes["127.0.0.1:9501"] = {
        "debug_address": "127.0.0.1:9501", "user_data_dir": env.profile_dir(XHS)
    }
    env.identity = {
        "status": "logged_in", "shop_id": None, "shop_name": "涩计似空的店",
        "page_url": XHS_HOME, "error": None, "detail": None,
    }

    data = get_json(api.client.get("/api/shop/current"))["data"]
    assert data["status"] == "logged_in" and data["observation"] != "unknown"
    assert data["active_profile_label"] == "涩计似空的店"
    assert data["shop_id"] is None and data["shop_name"] == "涩计似空的店"

    profiles = get_json(api.client.get("/api/shop/profiles"))["data"]["profiles"]
    listed = next(item for item in profiles if item["profile_name"] == XHS)
    assert listed["label"] == "涩计似空的店"
    assert listed["identity_source"] == "registry_last_seen"
    assert listed["shop_id"] is None


def test_current_flags_a_changed_shop_and_keeps_the_history(env, api):
    env.reusable = selected("127.0.0.1:9501", env.profile_dir(DOUYIN))
    env.identity = dict(LOGGED_IN, shop_id="2002", shop_name="乙店")
    data = get_json(api.client.get("/api/shop/current"))["data"]
    assert data["observation"] == "changed"
    saved = registry()["profiles"][DOUYIN]
    assert saved["shop_id"] == "2002" and saved["history"][0]["shop_id"] == "1001"


@pytest.mark.parametrize("identity", (
    {"status": "logged_out", "shop_id": None, "shop_name": None, "error": "尚未登录", "detail": "x"},
    {"status": "logged_in", "shop_id": None, "shop_name": None},
))
def test_current_does_not_write_the_registry_without_a_shop_id(env, api, identity):
    env.reusable = selected("127.0.0.1:9501", env.profile_dir(DOUYIN))
    env.identity = identity
    before = registry()
    data = get_json(api.client.get("/api/shop/current"))["data"]
    assert data["status"] == identity["status"] and "observation" not in data
    assert registry() == before


def test_current_reports_a_conflict_when_the_browser_belongs_to_another_account(env, api):
    env.reusable = selected("127.0.0.1:9502", env.profile_dir(TAOBAO))
    env.identity = dict(LOGGED_IN)
    before = registry()
    data = get_json(api.client.get("/api/shop/current"))["data"]
    assert data["status"] == "conflict"
    assert data["shop_id"] is None and data["shop_name"] is None
    assert data["error"] == "浏览器登录账户与当前所选账户不一致，请重新选择账户"
    assert data["owner_profile"] == TAOBAO
    assert registry() == before                                     # 绝不记到当前账户头上


def test_current_reports_a_conflict_when_the_registry_changes_while_the_identity_is_read(env, api, monkeypatch):
    """读身份期间，注册表里这个账户的平台被别处改了：不能拿旧平台的读法去证明新平台的身份。"""
    env.reusable = selected("127.0.0.1:9501", env.profile_dir(DOUYIN))

    def read_identity_and_change_the_platform(debug_address, platform="douyin", timeout=10.0):
        registry_now = registry()
        registry_now["profiles"][DOUYIN]["platform"] = "taobao"
        shop_session.save_registry(registry_now)
        return dict(LOGGED_IN)

    monkeypatch.setattr(shop_session, "read_account_identity", read_identity_and_change_the_platform)
    data = get_json(api.client.get("/api/shop/current"))["data"]
    assert data["status"] == "conflict" and data["shop_id"] is None and data["shop_name"] is None
    assert data["error"] == "浏览器所属账户的平台与当前发布平台不一致，请重新选择账户"
    assert registry()["profiles"][DOUYIN]["seen_count"] == 2        # 没有把这次实测记进注册表


def test_current_with_a_browser_outside_every_account_does_not_write(env, api):
    env.reusable = selected("127.0.0.1:9503", str(env.root / "elsewhere" / "x"))
    env.identity = dict(LOGGED_IN)
    before = registry()
    data = get_json(api.client.get("/api/shop/current"))["data"]
    assert data["status"] == "logged_in" and data["owner_profile"] is None
    assert data["profile_match"] is False and "observation" not in data
    assert registry() == before


def test_current_profile_match_is_unknown_without_browser_details(env, api):
    env.gui.page = SimpleNamespace(address="127.0.0.1:9504")       # GUI 页面在手，但进程枚举没有它
    env.identity = dict(LOGGED_IN)
    data = get_json(api.client.get("/api/shop/current"))["data"]
    assert data["browser_source"] == "gui_page" and data["profile_match"] is None
    assert env.reusable_calls == []                                 # 有 GUI 页面就不再枚举其它浏览器


@pytest.mark.parametrize("error", (OSError("磁盘已满"), ValueError("平台不匹配")))
def test_current_warns_but_still_answers_when_the_registry_write_fails(env, api, monkeypatch, error):
    env.reusable = selected("127.0.0.1:9501", env.profile_dir(DOUYIN))
    env.identity = dict(LOGGED_IN)

    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(shop_session, "observe_identity", fail)
    data = get_json(api.client.get("/api/shop/current"))["data"]
    assert data["status"] == "logged_in" and data["shop_id"] == "1001"
    assert data["warning"] == f"登录已实测，但账户资料保存失败：{error}"
    assert data["observation"] == "unknown"


def test_current_probe_failure_is_an_api_error(env, api):
    env.reusable = selected("127.0.0.1:9501", env.profile_dir(DOUYIN))
    env.identity = RuntimeError("CDP 断开")
    body = get_json(api.client.get("/api/shop/current"))
    assert body["success"] is False and body["msg"] == "读取店铺状态失败: CDP 断开"


def test_current_with_a_missing_active_account_is_an_api_error(env, api):
    registry_now = registry()
    registry_now["active_profile"] = "ghost-00000000"
    shop_session.save_registry(registry_now)
    body = get_json(api.client.get("/api/shop/current"))
    assert body["success"] is False and body["msg"] == "读取店铺状态失败: 当前账户不存在，请重新选择账户"


@pytest.mark.parametrize("slug,platform", ((DOUYIN, "douyin"), (TAOBAO, "taobao"), (XHS, "xiaohongshu")))
def test_current_reads_identity_with_the_accounts_own_platform(env, api, slug, platform):
    registry_now = registry()
    registry_now["active_profile"] = slug
    shop_session.save_registry(registry_now)
    env.gui.page = SimpleNamespace(address="127.0.0.1:9504")
    env.identity = {"status": "logged_out"}
    data = get_json(api.client.get("/api/shop/current"))["data"]
    assert data["platform"] == platform
    assert env.identity_calls == [("127.0.0.1:9504", platform, 6.0)]


# ====================================================================== 解析「发布流程这一刻用的浏览器」

def test_gui_page_wins_over_every_other_source(env, api):
    env.gui.page = SimpleNamespace(address="127.0.0.1:9504")
    env.processes["127.0.0.1:9504"] = {"debug_address": "127.0.0.1:9504", "pid": 7}
    for platform in ("douyin", "taobao", "xiaohongshu"):
        assert api.service.resolve_active_browser(platform=platform) == (
            "127.0.0.1:9504", {"debug_address": "127.0.0.1:9504", "pid": 7}, "gui_page")
    assert env.reusable_calls == []


def test_douyin_prefers_a_logged_in_reusable_browser(env, api):
    env.reusable = selected("127.0.0.1:9501", env.profile_dir(DOUYIN))
    address, info, source = api.service.resolve_active_browser(platform="douyin")
    assert (address, source) == ("127.0.0.1:9501", "reusable_browser")
    assert info["user_data_dir"] == env.profile_dir(DOUYIN)
    assert env.reusable_calls == [True]


def test_douyin_falls_back_to_a_browser_parked_on_the_login_page(env, api):
    skipped = {"debug_address": ""}
    parked = {"debug_address": "127.0.0.1:9520", "user_data_dir": ""}
    env.reusable = {
        "selected_browser": None, "eligible_browsers": [skipped, parked],
        "targets_by_address": {"127.0.0.1:9520": [
            {"type": "page", "url": "devtools://x"},
            {"type": "background_page", "url": "https://fxg.jinritemai.com/"},
            {"type": "page", "url": "https://fxg.jinritemai.com/login"},
        ]},
    }
    assert api.service.resolve_active_browser(platform="douyin") == ("127.0.0.1:9520", parked, "open_browser")


@pytest.mark.parametrize("reusable,error", (
    ({"eligible_browsers": [{"debug_address": "127.0.0.1:9521"}],
      "targets_by_address": {"127.0.0.1:9521": [{"type": "page", "url": "https://example.com/"}]}}, None),
    ({}, RuntimeError("枚举浏览器失败")),
))
def test_douyin_without_any_jinritemai_page_has_no_browser(env, api, reusable, error):
    env.reusable, env.reusable_error = reusable, error
    assert api.service.resolve_active_browser(platform="douyin") == ("", {}, "none")


def test_taobao_prefers_a_seller_page_and_never_requires_a_logged_in_check(env, api):
    browser = {"debug_address": "127.0.0.1:9510"}
    env.reusable = {"eligible_browsers": [{"debug_address": ""}, browser], "targets_by_address": {
        "127.0.0.1:9510": [{"type": "service_worker", "url": "https://www.taobao.com/"},
                           {"type": "page", "url": "devtools://x"},
                           {"type": "page", "url": "https://www.taobao.com/"},
                           {"type": "page", "url": "https://item.upload.taobao.com/sell/x"}]}}
    assert api.service.resolve_active_browser(platform="taobao") == (
        "127.0.0.1:9510", browser, "taobao_seller_page")
    assert env.reusable_calls == [False]


def test_taobao_falls_back_to_a_plain_taobao_page_then_to_nothing(env, api):
    browser = {"debug_address": "127.0.0.1:9511"}
    env.reusable = {"eligible_browsers": [browser], "targets_by_address": {
        "127.0.0.1:9511": [{"type": "page", "url": "https://www.taobao.com/"}]}}
    assert api.service.resolve_active_browser(platform="taobao") == ("127.0.0.1:9511", browser, "taobao_page")
    env.reusable = {"eligible_browsers": [browser], "targets_by_address": {
        "127.0.0.1:9511": [{"type": "page", "url": "https://example.com/"}]}}
    assert api.service.resolve_active_browser(platform="taobao") == ("", {}, "none")
    env.reusable_error = RuntimeError("枚举失败")
    assert api.service.resolve_active_browser(platform="taobao") == ("", {}, "none")


def fake_xhs_ports(monkeypatch, targets_by_port):
    class Response:
        def __init__(self, body):
            self.body = body

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return self.body

    def urlopen(url, timeout=None):
        port = int(url.split("//")[1].split("/")[0].rsplit(":", 1)[-1])
        if port not in targets_by_port:
            raise urllib.error.URLError("refused")
        import json
        return Response(json.dumps(targets_by_port[port]).encode("utf-8"))

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)


def test_xiaohongshu_scans_only_the_shop_port_range(env, api, monkeypatch):
    fake_xhs_ports(monkeypatch, {
        9499: [{"type": "page", "url": "https://ark.xiaohongshu.com/out-of-range"}],
        9501: [{"type": "page", "url": "devtools://x"},
               {"type": "page", "url": "https://customer.xiaohongshu.com/x"},
               {"type": "page", "url": "https://example.com/"}],
        9502: [{"type": "service_worker", "url": "https://ark.xiaohongshu.com/sw"},
               {"type": "page", "url": "https://ark.xiaohongshu.com/app"}],
    })
    env.processes["127.0.0.1:9502"] = {"debug_address": "127.0.0.1:9502", "pid": 3}
    assert api.service.resolve_active_browser(platform="xiaohongshu") == (
        "127.0.0.1:9502", {"debug_address": "127.0.0.1:9502", "pid": 3}, "xhs_ark_page")
    assert env.reusable_calls == []                  # 千帆浏览器不走「已登录抖店」那条链


def test_xiaohongshu_falls_back_to_any_qianfan_page_and_unknown_process_info(env, api, monkeypatch):
    fake_xhs_ports(monkeypatch, {9500: [{"type": "page", "url": "https://school.xiaohongshu.com/"}]})
    assert api.service.resolve_active_browser(platform="xiaohongshu") == (
        "127.0.0.1:9500", {"debug_address": "127.0.0.1:9500"}, "xhs_page")
    fake_xhs_ports(monkeypatch, {9500: [{"type": "page", "url": "https://example.com/"}], 9503: []})
    assert api.service.resolve_active_browser(platform="xiaohongshu") == ("", {}, "none")


# ====================================================================== 运费模板

def test_freight_templates_without_a_browser_are_empty_but_not_conflated_with_none(env, api):
    data = get_json(api.client.get("/api/shop/freight-templates"))["data"]
    assert data["status"] == "no_browser" and data["templates"] == [] and data["platform"] == "douyin"
    assert data["error"] == "尚未登录，先在左上角登录店铺"


def test_freight_templates_are_read_live_and_tagged_with_the_shop_name(env, api):
    env.reusable = selected("127.0.0.1:9501", env.profile_dir(DOUYIN))
    env.identity = dict(LOGGED_IN)
    env.freight = {"status": "ok", "templates": [{"id": "t1", "name": "包邮"}], "shop_id": "1001", "current": None}
    data = get_json(api.client.get("/api/shop/freight-templates"))["data"]
    assert data["status"] == "ok" and data["templates"] == [{"id": "t1", "name": "包邮"}]
    assert data["shop_id"] == "1001" and data["shop_name"] == "甲店"


def test_freight_templates_from_another_shop_are_discarded(env, api):
    env.reusable = selected("127.0.0.1:9501", env.profile_dir(DOUYIN))
    env.identity = dict(LOGGED_IN)
    env.freight = {"status": "ok", "templates": [{"id": "t1"}], "shop_id": "9999"}
    data = get_json(api.client.get("/api/shop/freight-templates"))["data"]
    assert data["status"] == "conflict" and data["templates"] == []
    assert data["error"] == "运费模板与当前登录店铺对不上，请重新登录后再试"
    assert data["detail"] == "模板 shop_id=9999 实测登录 shop_id=1001"


def test_freight_templates_survive_a_failed_identity_read(env, api):
    env.reusable = selected("127.0.0.1:9501", env.profile_dir(DOUYIN))
    env.identity = RuntimeError("身份读取失败")
    env.freight = {"status": "ok", "templates": [{"id": "t1"}], "shop_id": "1001"}
    data = get_json(api.client.get("/api/shop/freight-templates"))["data"]
    assert data["status"] == "ok" and data["templates"] == [{"id": "t1"}] and data["shop_name"] is None


def test_taobao_freight_templates_use_the_taobao_reader_and_keep_current(env, api):
    registry_now = registry()
    registry_now["active_profile"] = TAOBAO
    shop_session.save_registry(registry_now)
    env.reusable = {"eligible_browsers": [{"debug_address": "127.0.0.1:9510"}], "targets_by_address": {
        "127.0.0.1:9510": [{"type": "page", "url": "https://item.upload.taobao.com/x"}]}}
    env.identity = {"status": "logged_in", "shop_id": "tb-1", "shop_name": "淘宝店"}
    env.freight = {"status": "not_captured", "templates": [], "current": "包邮模板", "detail": "d"}
    data = get_json(api.client.get("/api/shop/freight-templates"))["data"]
    assert data["platform"] == "taobao" and data["status"] == "not_captured"
    assert data["current"] == "包邮模板" and data["shop_name"] == "淘宝店"
    assert env.identity_calls[-1][1] == "taobao"


# ====================================================================== 添加账户

@pytest.mark.parametrize("raw", ("bad", "[]", "42"))
def test_add_requires_a_json_object(env, api, raw):
    before = registry()
    response = api.client.post("/api/shop/add", data=raw, content_type="application/json")
    assert response.status_code == 400 and response.get_json()["success"] is False
    assert registry() == before and env.opened == []


@pytest.mark.parametrize("body,fragment", (
    ({"unknown": 1}, "有效的 JSON 对象"),
    ({"label": 5}, "60字以内"),
    ({"label": "名" * 61}, "60字以内"),
    ({"open_browser": "yes"}, "必须是布尔值"),
    ({"open_browser": 1}, "必须是布尔值"),
))
def test_add_rejects_bad_fields_without_touching_anything(env, api, body, fragment):
    before = registry()
    response = api.client.post("/api/shop/add", json=body)
    assert response.status_code == 400
    assert fragment in response.get_json()["msg"]
    assert registry() == before and env.opened == []


@pytest.mark.parametrize("platform", ("tmall", 7, "", None, True))
def test_add_rejects_unknown_platforms(env, api, platform):
    before = registry()
    response = api.client.post("/api/shop/add", json={"platform": platform})
    assert response.status_code == 400 and "添加账户失败" in response.get_json()["msg"]
    assert registry() == before and env.opened == []


@pytest.mark.parametrize("platform,url,label", (
    ("douyin", DOUYIN_HOME, "抖音 / 抖店"), ("taobao", TAOBAO_HOME, "淘宝"),
    ("xiaohongshu", XHS_HOME, "小红书千帆"),
))
def test_add_opens_each_platforms_own_login_page(env, api, platform, url, label):
    env.gui.page = SimpleNamespace(address="old-browser")
    env.resets.clear()
    body = get_json(api.client.post("/api/shop/add", json={"platform": platform, "label": " 新账户 "}))
    assert body["success"] is True
    assert body["msg"] == f"{label}账户已添加，登录后会自动显示店铺名"
    data = body["data"]
    slug = data["active_profile"]
    assert data["platform"] == platform and data["browser_opened"] is True and data["browser_error"] is None
    assert env.opened == [(url, slug)]
    assert data["debug_address"] == "127.0.0.1:9601" and data["previous_debug_address"] == "old-browser"
    assert env.resets == [None]                                  # 旧句柄被丢弃
    assert registry()["active_profile"] == slug and registry()["profiles"][slug]["label"] == "新账户"
    assert registry()["profiles"][slug]["platform"] == platform


def test_add_without_body_keeps_the_legacy_douyin_behavior(env, api):
    body = get_json(api.client.post("/api/shop/add"))
    assert body["success"] is True and body["data"]["platform"] == "douyin"
    assert body["data"]["active_profile"] == "shop-00000001"
    assert env.opened == [(DOUYIN_HOME, "shop-00000001")]


def test_add_without_opening_the_browser(env, api):
    body = get_json(api.client.post("/api/shop/add", json={"platform": "taobao", "open_browser": False}))
    assert body["msg"] == "淘宝账户已添加" and body["data"]["browser_opened"] is False
    assert env.opened == [] and "debug_address" not in body["data"]


def test_add_reuses_an_unused_empty_account_of_the_same_platform(env, api):
    body = get_json(api.client.post("/api/shop/add", json={"platform": "taobao", "open_browser": False}))
    assert body["data"]["active_profile"] == TAOBAO              # 空容器复用，不在磁盘上多一个目录
    assert set(registry()["profiles"]) == {DOUYIN, TAOBAO, XHS}


def test_add_keeps_the_account_when_the_browser_cannot_be_opened(env, api):
    env.open_error = RuntimeError("打不开浏览器")
    body = get_json(api.client.post("/api/shop/add", json={"platform": "douyin"}))
    assert body["success"] is True
    assert body["msg"] == "店铺已添加，但登录页面没能自动打开，请手动打开抖音 / 抖店后台登录"
    assert body["data"]["browser_opened"] is False and body["data"]["browser_error"] == "打不开浏览器"
    assert registry()["active_profile"] == body["data"]["active_profile"]


@pytest.mark.parametrize("failing,error,status", (
    ("create_profile", RuntimeError("磁盘只读"), 200),
    ("create_profile", ValueError("名称重复"), 400),
    ("set_active_profile", ValueError("不能激活"), 400),
    ("set_active_profile", OSError("注册表写入失败"), 200),
))
def test_add_reports_registry_failures(env, api, monkeypatch, failing, error, status):
    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(shop_session, failing, fail)
    response = api.client.post("/api/shop/add", json={"platform": "douyin"})
    assert response.status_code == status
    body = response.get_json()
    assert body["success"] is False
    assert (("添加账户失败" if status == 400 else "添加店铺失败") in body["msg"]) and str(error) in body["msg"]
    assert env.opened == []


@pytest.mark.parametrize("route,body", (
    ("/api/shop/add", {"platform": "taobao"}),
    ("/api/shop/switch", {"profile_name": TAOBAO}),
    ("/api/shop/forget", {"profile_name": XHS}),
))
def test_running_publish_tasks_block_every_account_change(env, api, route, body):
    env.running = True
    before = registry()
    response = api.client.post(route, json=body)
    assert response.status_code == 409
    assert response.get_json() == {"success": False, "msg": "发布任务运行中，请完成或取消后再切换账户"}
    assert registry() == before and env.opened == [] and env.resets == []


# ====================================================================== 切换账户

@pytest.mark.parametrize("body,status", (
    (None, 400), ([], 400), ({"profile_name": DOUYIN, "extra": 1}, 400), ({}, 400),
    ({"profile_name": 5}, 400), ({"profile_name": "   "}, 400),
    ({"profile_name": DOUYIN, "open_browser": "no"}, 400),
))
def test_switch_rejects_bad_requests_without_touching_anything(env, api, body, status):
    before = registry()
    response = api.client.post("/api/shop/switch", json=body)
    assert response.status_code == status and response.get_json()["success"] is False
    assert registry() == before and env.opened == [] and env.resets == []


@pytest.mark.parametrize("name", ("不存在的账户", "ghost-00000000", "upload-browser-profile"))
def test_switch_to_an_unregistered_account_is_a_404_and_creates_nothing(env, api, name):
    before = registry()
    response = api.client.post("/api/shop/switch", json={"profile_name": name})
    assert response.status_code == 404 and response.get_json()["msg"] == "账户不存在，请刷新账户列表"
    assert registry() == before and env.opened == []


@pytest.mark.parametrize("slug,url,platform", ((TAOBAO, TAOBAO_HOME, "taobao"), (XHS, XHS_HOME, "xiaohongshu"),
                                               (DOUYIN, DOUYIN_HOME, "douyin")))
def test_switch_drops_the_old_browser_handle_and_opens_the_new_login_page(env, api, slug, url, platform):
    env.gui.page = SimpleNamespace(address="127.0.0.1:9701")
    body = get_json(api.client.post("/api/shop/switch", json={"profile_name": f" {slug} "}))
    assert body["success"] is True and body["msg"] == "已切换，请在打开的页面完成登录"
    data = body["data"]
    assert data["active_profile"] == slug and data["platform"] == platform
    assert data["previous_debug_address"] == "127.0.0.1:9701"
    assert env.opened == [(url, slug)] and env.resets == [None]
    assert env.gui.page.address == "127.0.0.1:9601"             # 页面句柄换成了新开的那个
    assert registry()["active_profile"] == slug
    assert data["profile_dir"] == env.profile_dir(slug)


def test_switch_without_opening_the_browser_still_drops_the_old_handle(env, api):
    env.gui.page = SimpleNamespace(address="127.0.0.1:9701")
    body = get_json(api.client.post("/api/shop/switch", json={"profile_name": TAOBAO, "open_browser": False}))
    assert body["msg"] == "已切换到淘宝账户" and body["data"]["browser_opened"] is False
    assert env.gui.page is None and env.opened == [] and env.resets == [None]


def test_switch_keeps_the_new_account_when_the_browser_cannot_be_opened(env, api):
    env.open_error = RuntimeError("打不开浏览器")
    body = get_json(api.client.post("/api/shop/switch", json={"profile_name": TAOBAO}))
    assert body["success"] is True
    assert body["msg"] == "已切换，但登录页面没能自动打开，请手动打开淘宝后台登录"
    assert body["data"]["browser_error"] == "打不开浏览器"
    assert registry()["active_profile"] == TAOBAO and env.gui.page is None


@pytest.mark.parametrize("error,status,fragment", (
    (ValueError("不能切换"), 400, "切换账户失败：不能切换"),
    (RuntimeError("意外"), 200, "切换店铺失败: 意外"),
))
def test_switch_reports_registry_failures(env, api, monkeypatch, error, status, fragment):
    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(shop_session, "set_active_profile", fail)
    response = api.client.post("/api/shop/switch", json={"profile_name": TAOBAO})
    assert response.status_code == status and fragment in response.get_json()["msg"]
    assert env.opened == []


def test_switch_refuses_when_the_registry_target_differs_from_the_requested_one(env, api, monkeypatch):
    monkeypatch.setattr(shop_session, "set_active_profile", lambda name, **kwargs: "shop-eeeeeeee")
    response = api.client.post("/api/shop/switch", json={"profile_name": TAOBAO})
    assert response.status_code == 400
    assert response.get_json()["msg"] == "切换账户失败：当前账户与切换目标不一致"
    assert env.opened == [] and env.resets == []


def test_switch_message_falls_back_to_the_raw_platform_name_when_it_cannot_be_normalized(env):
    class Wrapped:
        """路由里的 shop_session 认不得 xiaohongshu：platform_label 必须退回原始平台名而不是抛错。"""

        def __getattr__(self, name):
            return getattr(shop_session, name)

        @staticmethod
        def normalize_platform(value):
            if value == "xiaohongshu":
                raise ValueError("不认识")
            return shop_session.normalize_platform(value)

    api = build(env, route_shop=Wrapped())
    body = get_json(api.client.post("/api/shop/switch", json={"profile_name": XHS, "open_browser": False}))
    assert body["msg"] == "已切换到xiaohongshu账户"


# ====================================================================== 移除账户

@pytest.mark.parametrize("body,status", (
    (None, 400), ([], 400), ({}, 400), ({"profile_name": 5}, 400), ({"profile_name": "  "}, 400),
    ({"profile_name": XHS, "purge": "true"}, 400),
))
def test_forget_rejects_bad_requests(env, api, body, status):
    before = registry()
    response = api.client.post("/api/shop/forget", json=body)
    assert response.status_code == status and response.get_json()["success"] is False
    assert registry() == before


def test_forget_without_purge_only_removes_the_record(env, api):
    directory = env.root / XHS
    directory.mkdir()
    (directory / "Cookies").write_text("login", encoding="utf-8")
    body = get_json(api.client.post("/api/shop/forget", json={"profile_name": XHS}))
    assert body["msg"] == "已从列表移除，本地浏览器登录资料仍保留"
    assert body["data"]["purged"] is False and body["data"]["removed_profile"] == XHS
    assert XHS not in registry()["profiles"] and (directory / "Cookies").exists()
    assert {item["profile_name"] for item in body["data"]["profiles"]} == {DOUYIN, TAOBAO}


def test_forget_with_purge_deletes_the_login_data_too(env, api):
    directory = env.root / TAOBAO
    directory.mkdir()
    (directory / "Cookies").write_text("login", encoding="utf-8")
    body = get_json(api.client.post("/api/shop/forget", json={"profile_name": TAOBAO, "purge": True}))
    assert body["msg"] == "已彻底删除该账户，包括本地浏览器登录资料"
    assert body["data"]["purged"] is True and not directory.exists()
    assert TAOBAO not in registry()["profiles"]


def test_forget_with_purge_but_no_directory_does_not_claim_a_purge(env, api):
    body = get_json(api.client.post("/api/shop/forget", json={"profile_name": TAOBAO, "purge": True}))
    assert body["data"]["purged"] is False and body["msg"] == "已从列表移除，本地浏览器登录资料仍保留"


def test_forget_reports_leftover_login_data_honestly(env, api, monkeypatch):
    directory = env.root / TAOBAO
    directory.mkdir()
    monkeypatch.setattr(shop_session, "remove_profile", lambda name, purge_directory=False: True)
    body = get_json(api.client.post("/api/shop/forget", json={"profile_name": TAOBAO, "purge": True}))
    assert body["data"]["purged"] is False
    assert body["msg"] == "已从列表移除，但浏览器登录资料未能完全删除，请手动检查"


def test_forgetting_the_active_account_hands_the_selection_to_another_one(env, api):
    body = get_json(api.client.post("/api/shop/forget", json={"profile_name": DOUYIN}))
    assert body["data"]["active_profile"] in (TAOBAO, XHS)       # 交接给仍然存在的账户
    assert registry()["active_profile"] == body["data"]["active_profile"]


def test_forget_unknown_account_is_a_404(env, api):
    before = registry()
    response = api.client.post("/api/shop/forget", json={"profile_name": "ghost-00000000"})
    assert response.status_code == 404 and response.get_json()["msg"] == "账户不存在，请刷新账户列表"
    assert registry() == before


def test_the_default_placeholder_is_removable_only_while_it_is_empty(env, api):
    registry_now = registry()
    registry_now["profiles"][DEFAULT] = entry(DEFAULT, "douyin", "有备注的默认账户")
    shop_session.save_registry(registry_now)
    response = api.client.post("/api/shop/forget", json={"profile_name": DEFAULT})
    assert response.status_code == 409 and "不能作为默认空账户移除" in response.get_json()["msg"]
    assert DEFAULT in registry()["profiles"]

    registry_now = registry()
    registry_now["profiles"][DEFAULT] = entry(DEFAULT, "douyin")
    shop_session.save_registry(registry_now)
    body = get_json(api.client.post("/api/shop/forget", json={"profile_name": DEFAULT}))
    assert body["data"]["removed_profile"] == DEFAULT and DEFAULT not in registry()["profiles"]


@pytest.mark.parametrize("error,status", ((OSError("注册表写入失败"), 503), (ValueError("不能移除"), 503)))
def test_forget_registry_failures_are_503_and_visible(env, api, monkeypatch, error, status):
    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(shop_session, "remove_profile", fail)
    response = api.client.post("/api/shop/forget", json={"profile_name": XHS})
    assert response.status_code == status
    assert response.get_json()["msg"] == f"移除账户失败：{error}"


# ====================================================================== 启动时恢复浏览器


def test_restore_without_browser_opens_once_then_stops_reopening_when_logged_in(env, api):
    body = get_json(api.client.post('/api/shop/restore'))['data']
    assert body['recovery_attempted'] is True and body['browser_opened'] is True
    assert body['debug_address'] == '127.0.0.1:9601'
    assert body['shop']['status'] == 'no_browser', '打开浏览器不能冒充登录恢复'
    assert env.opened == [(DOUYIN_HOME, DOUYIN)]

    env.identity = dict(LOGGED_IN)
    second = get_json(api.client.post('/api/shop/restore'))['data']
    assert second['recovery_attempted'] is False and second['browser_opened'] is False
    assert second['shop']['status'] == 'logged_in'
    assert env.opened == [(DOUYIN_HOME, DOUYIN)]


def test_restore_existing_login_never_opens_another_page(env, api):
    env.reusable = selected('127.0.0.1:9501', env.profile_dir(DOUYIN))
    env.identity = dict(LOGGED_IN)
    body = get_json(api.client.post('/api/shop/restore'))['data']
    assert body['recovery_attempted'] is False and body['browser_opened'] is False
    assert body['shop']['status'] == 'logged_in' and env.opened == []


def test_restore_real_logged_out_does_not_open_or_hide_the_fact(env, api):
    env.reusable = selected('127.0.0.1:9501', env.profile_dir(DOUYIN))
    env.identity = {'status': 'logged_out', 'shop_id': None, 'shop_name': None}
    body = get_json(api.client.post('/api/shop/restore'))['data']
    assert body['recovery_attempted'] is False and body['browser_opened'] is False
    assert body['shop']['status'] == 'logged_out' and env.opened == []


def test_restore_is_blocked_by_running_publish_tasks(env, api):
    env.running = True
    response = api.client.post('/api/shop/restore')
    assert response.status_code == 409
    assert response.get_json()['success'] is False and env.opened == []


# ====================================================================== 依赖边界

def test_importing_the_shop_modules_does_not_load_the_browser_stack(tmp_path):
    code = (
        "import sys; sys.path.insert(0, %r); "
        "import src.sidecar.shop_accounts, src.sidecar.shop_service, src.sidecar.shop_routes; "
        "bad = [m for m in ('DrissionPage', 'src.utils', 'PySide6', 'app') if m in sys.modules]; "
        "print('LOADED=' + ','.join(bad))" % str(REPO)
    )
    env = dict(os.environ, DOUYIN_DATA_DIR=str(tmp_path / "data"), PYTHONUTF8="1")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         encoding="utf-8", env=env, check=True)
    assert out.stdout.strip().splitlines()[-1] == "LOADED="

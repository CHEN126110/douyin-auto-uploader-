# -*- coding: utf-8 -*-
"""账户绑定平台的真实 Flask 路由与发布门禁，隔离注册表、DB 和浏览器。"""

from __future__ import annotations

import ast
import copy
import importlib
import json
import os
import sys
import threading
import traceback
from datetime import datetime
from functools import wraps
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from flask import Flask, jsonify, request


PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_PATH = PROJECT_ROOT / "tauri-app" / "python-sidecar" / "app.py"
FUNCTIONS = {
    "_active_shop_profile", "_active_shop_account", "_require_publish_platform",
    "_with_shop_account_lock", "_account_change_blocked",
    "_shop_profile_matches", "_build_shop_current_payload", "_activate_shop_profile",
    # platform_label 被 shop_add / shop_switch 用来拼面向用户的消息；
    # 它是被这两个路由调用的，必须一起抽出来，否则隔离命名空间里会 NameError。
    "platform_label",
    "shop_current", "shop_profiles", "shop_add", "shop_switch", "shop_forget", "shop_freight_templates",
    "_load_taobao_desktop", "_taobao_product_request", "taobao_prepare", "taobao_export",
    "upload_start", "upload_start_all", "upload_ensure_session",
}
# 这些路由引用到的模块级常量。它们不是函数，但缺一个就会在某个分支 NameError。
MODULE_CONSTANTS = {
    "_SHOP_LOGIN_URL", "_TAOBAO_SHOP_LOGIN_URL", "_PUBLISH_CREATE_URL",
}


class FakeShopSession:
    DEFAULT_PROFILE_NAME = "upload-browser-profile"

    def __init__(self):
        self.registry = {
            "active_profile": self.DEFAULT_PROFILE_NAME,
            "profiles": {
                self.DEFAULT_PROFILE_NAME: {
                    "profile_name": self.DEFAULT_PROFILE_NAME,
                    "label": "历史抖店",
                    "shop_id": "douyin-1",
                    "shop_name": "历史实测抖店",
                },
                "douyin-second": {
                    "profile_name": "douyin-second", "platform": "douyin",
                    "label": "抖店二", "shop_id": "douyin-2", "shop_name": "抖店二",
                },
                "taobao-local": {
                    "profile_name": "taobao-local", "platform": "taobao",
                    "label": "淘宝人工备注", "shop_id": None, "shop_name": None,
                },
            },
        }
        self.created = []
        self.activations = []
        self.removed = []
        self.purge_requests = []
        self.read_shop_identity = Mock(return_value={"status": "no_browser"})
        self.read_taobao_identity = Mock(return_value={"status": "no_browser"})
        # app.py 现在按平台分派身份读取：统一走 read_account_identity。
        # 刻意**不设 side_effect**——设了它就会盖掉用例随后设的 return_value，
        # 实测这次踩过：淘宝用例设了 logged_in，拿到的却是桩里的默认 no_browser。
        # 需要验证「按平台分派」的用例，直接断言这个 mock 收到的 platform 参数。
        self.read_account_identity = Mock(return_value={"status": "no_browser"})
        self.read_freight_templates = Mock(return_value={"status": "no_browser", "templates": []})

    @staticmethod
    def normalize_platform(value):
        if not isinstance(value, str) or value.strip().lower() not in {"douyin", "taobao"}:
            raise ValueError("账户平台必须是 douyin 或 taobao")
        return value.strip().lower()

    def load_registry(self):
        return copy.deepcopy(self.registry)

    def get_active_profile(self):
        return self.registry["active_profile"]

    def list_profiles(self):
        return [
            dict(entry, profile_name=name, platform=self.normalize_platform(entry.get("platform", "douyin")),
                 is_active=name == self.get_active_profile())
            for name, entry in self.registry["profiles"].items()
        ]

    def profile_dir(self, name):
        return str(PROJECT_ROOT / ".tmp" / "isolated-shop-platform" / name)

    def registry_path(self):
        return str(PROJECT_ROOT / ".tmp" / "isolated-shop-platform" / "shop_profiles.json")

    @staticmethod
    def slugify_profile_name(name):
        return name or FakeShopSession.DEFAULT_PROFILE_NAME

    def create_profile(self, platform="douyin", label=None):
        platform = self.normalize_platform(platform)
        name = f"{platform}-created-{len(self.created) + 1}"
        self.created.append({"platform": platform, "label": label, "profile_name": name})
        self.registry["profiles"][name] = {
            "profile_name": name, "platform": platform, "label": label,
            "shop_id": None, "shop_name": None,
        }
        return name

    def set_active_profile(self, name, **_kwargs):
        self.activations.append(name)
        # 有意保留旧 ensure 行为，让真实 switch 路由必须先拦未知目标。
        self.registry["profiles"].setdefault(name, {"profile_name": name, "platform": "douyin"})
        self.registry["active_profile"] = name
        return name

    @staticmethod
    def is_empty_default_profile(name, entry):
        # 使用真实纯判断 helper；不调用实际注册表或目录定位。
        real_shop_session = importlib.import_module("src.shop_session")
        return real_shop_session.is_empty_default_profile(name, entry)

    def remove_profile(self, name, purge_directory=False):
        """purge_directory 是 app.py 的「连本地目录一起删」开关。

        真实实现只有在它显式为 True 且目录确实存在时才会动磁盘；
        这里如实记录参数，让断言能验证「默认不删目录」这条安全行为。
        交接规则也对齐真实实现：被删的正好是当前账户时，交回默认账户
        （而不是留下一个指向已删账户的 active）。
        """
        self.removed.append(name)
        self.purge_requests.append({"profile_name": name, "purge_directory": purge_directory})
        if name not in self.registry["profiles"]:
            return False
        del self.registry["profiles"][name]
        if self.registry["active_profile"] == name:
            self.registry["active_profile"] = self.DEFAULT_PROFILE_NAME
        return True

    def owning_profile_of(self, path):
        return next((name for name in self.registry["profiles"] if self.profile_dir(name) == path), None)

    def observe_identity(self, *_args, **_kwargs):
        return {"status": "confirmed"}


class FakeSettings:
    def __init__(self):
        self.automation = {"upload_browser_profile": "upload-browser-profile"}
        self.updates = []

    def get_automation_config(self):
        return dict(self.automation)

    def update_automation_config(self, values):
        self.updates.append(dict(values))
        self.automation.update(values)
        return True


@pytest.fixture
def platform_api():
    shop = FakeShopSession()
    settings = FakeSettings()
    browser_resolver = Mock(return_value=("", {}, "none"))
    browser_open = Mock(return_value=SimpleNamespace())
    browser_reset = Mock()
    forbidden = Mock(side_effect=AssertionError("不得访问真实 DB、浏览器或发布流水线"))
    db_calls = []

    class FakeQuery:
        def where(self, *_args):
            return self

        def order_by(self, *_args):
            return self

        def __iter__(self):
            return iter([SimpleNamespace(id=7, name="测试商品")])

    class FakeRecord:
        id = 7
        status = 0
        DoesNotExist = LookupError

        @classmethod
        def get_by_id(cls, record_id):
            db_calls.append(("get_by_id", record_id))
            raise AssertionError("被平台门禁拒绝的请求不得读取 Record")

        @classmethod
        def select(cls):
            db_calls.append(("select",))
            return FakeQuery()

    workers = []

    class FakeThread:
        def __init__(self, target, args, daemon):
            self.target, self.args, self.daemon = target, args, daemon

        def start(self):
            # 记录调度但不执行后台任务，不接触浏览器或平台。
            workers.append(self)

    app = Flask("isolated-shop-platform-api")
    app.config.update(TESTING=True)
    tasks = {}
    namespace = {
        "__name__": "shop_platform_api_isolated", "app": app,
        "os": os, "sys": sys, "json": json, "datetime": datetime,
        "traceback": traceback, "repo_root": str(PROJECT_ROOT),
        "wraps": wraps, "_shop_account_lock": threading.RLock(),
        "request": request, "jsonify": jsonify,
        "shop_session": shop, "settings_manager": settings,
        "api_ok": lambda msg, data=None: {"success": True, "msg": msg, "data": data},
        "api_error": lambda msg, data=None: {"success": False, "msg": msg, "data": data},
        "gui": SimpleNamespace(page=SimpleNamespace()),
        "get_page": browser_open, "_set_browser_debug_instance": browser_reset,
        "_normalize_debug_address": lambda value: value or "",
        "_get_gui_page_debug_address": lambda: "127.0.0.1:9400",
        "_resolve_active_shop_browser": browser_resolver,
        "_debug_bool": lambda value, default=False: default if value is None else bool(value),
        "Record": FakeRecord, "resolve_data_file": forbidden,
        "_run_upload_task": forbidden, "_ensure_publish_session": forbidden,
        "_resolve_upload_stop_before_submit": lambda _data: (True, False),
        "_upload_tasks": tasks, "_upload_tasks_lock": threading.RLock(),
        "_taobao_tasks": {}, "_taobao_tasks_lock": threading.RLock(),
        "threading": SimpleNamespace(Thread=FakeThread),
    }
    tree = ast.parse(APP_PATH.read_text(encoding="utf-8"))
    definitions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in FUNCTIONS]
    assert {node.name for node in definitions} == FUNCTIONS
    # 路由用到的模块级常量也要抽出来。少一个不会报 ImportError，
    # 而是等到某个分支才 NameError——淘宝那条 open_browser=True 的路径就这样漏过了一整轮。
    constants = [
        node for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id in MODULE_CONSTANTS for t in node.targets)
    ]
    assert {t.id for node in constants for t in node.targets if isinstance(t, ast.Name)} == MODULE_CONSTANTS
    exec(compile(ast.Module(body=constants + definitions, type_ignores=[]), str(APP_PATH), "exec"), namespace)
    yield SimpleNamespace(
        app=app, client=app.test_client(), namespace=namespace, shop=shop, settings=settings,
        browser_resolver=browser_resolver, browser_open=browser_open,
        browser_reset=browser_reset, forbidden=forbidden, db_calls=db_calls,
        tasks=tasks, workers=workers,
    )
    forbidden.assert_not_called()


def test_legacy_account_without_platform_stays_douyin(platform_api):
    account = platform_api.namespace["_active_shop_account"]()
    assert account["platform"] == "douyin"
    assert platform_api.namespace["_require_publish_platform"]("douyin") is None


def test_taobao_current_probes_identity_instead_of_assuming_manual(platform_api):
    """淘宝不再早退成「本地未验证」：它和抖店走同一条实测链路。

    早先这里的断言是 ``status == "manual"`` 且**不碰浏览器**，因为当时淘宝
    只做本地资料准备。现在淘宝也走真实登录，本地账户名不代表登录态，
    所以必须去实测；读不到就如实报「尚未登录」，而不是宣称已就绪。
    """
    platform_api.shop.registry["active_profile"] = "taobao-local"
    platform_api.browser_resolver.return_value = ("127.0.0.1:9400", {}, "open_browser")
    platform_api.shop.read_account_identity.return_value = {
        "status": "logged_out", "shop_id": None, "shop_name": None, "error": "尚未登录",
    }
    response = platform_api.client.get("/api/shop/current")
    assert response.status_code == 200
    body = response.get_json()
    assert body["success"] is True
    assert body["data"]["platform"] == "taobao"
    assert body["data"]["active_profile"] == "taobao-local"
    assert body["data"]["active_profile_label"] == "淘宝人工备注"
    # 本地账户名不能冒充已验证身份：这次实测没读到，就只能是「未登录」。
    assert body["data"]["status"] == "logged_out"
    assert not body["data"].get("shop_id")
    assert not body["data"].get("shop_name")
    # 关键：确实去实测了，而且按淘宝那条链路分派。
    assert platform_api.shop.read_account_identity.call_args.kwargs.get("platform") == "taobao"
    assert platform_api.browser_resolver.call_args.kwargs.get("platform") == "taobao"
    assert platform_api.settings.updates == []


def test_profiles_exposes_account_platforms_without_browser_access(platform_api):
    response = platform_api.client.get("/api/shop/profiles")
    assert response.status_code == 200
    body = response.get_json()
    assert body["success"] is True
    assert body["data"]["platform"] == "douyin"
    entries = {item["profile_name"]: item for item in body["data"]["profiles"]}
    assert entries["upload-browser-profile"]["platform"] == "douyin"
    assert entries["taobao-local"]["platform"] == "taobao"
    assert entries["taobao-local"]["shop_id"] is None
    assert entries["taobao-local"]["shop_name"] is None
    platform_api.browser_resolver.assert_not_called()
    platform_api.shop.read_shop_identity.assert_not_called()


@pytest.mark.parametrize("route", ("/api/upload/start", "/api/upload/start-all", "/api/upload/ensure-session"))
@pytest.mark.parametrize("body", ({}, {"platform": "douyin"}))
def test_active_taobao_blocks_douyin_even_without_platform_body(platform_api, route, body):
    platform_api.shop.registry["active_profile"] = "taobao-local"
    response = platform_api.client.post(route, json=body)
    assert response.status_code == 409
    assert response.get_json()["success"] is False
    assert platform_api.db_calls == []
    assert platform_api.tasks == {}
    assert platform_api.workers == []


@pytest.mark.parametrize("route", ("prepare", "export"))
@pytest.mark.parametrize("body", ({"record_id": 7}, {"record_id": 7, "platform": "taobao"}))
def test_active_douyin_blocks_taobao_before_reading_record(platform_api, route, body):
    response = platform_api.client.post(f"/api/taobao/publish/{route}", json=body)
    assert response.status_code == 409
    assert response.get_json()["success"] is False
    assert platform_api.db_calls == []
    assert platform_api.tasks == {}


def test_taobao_identity_probe_dispatches_by_platform(platform_api):
    """实测链路必须按平台分派：拿抖店的读法去证明淘宝登录态会得出错误身份。"""
    platform_api.shop.registry["active_profile"] = "taobao-local"
    platform_api.browser_resolver.return_value = ("127.0.0.1:9400", {}, "open_browser")
    platform_api.shop.read_account_identity.return_value = {
        "status": "logged_in", "shop_id": "taobao-local", "shop_name": "猫咪宝贝",
    }
    response = platform_api.client.get("/api/shop/current")
    assert response.status_code == 200
    body = response.get_json()
    assert body["success"] is True
    assert body["data"]["status"] == "logged_in"
    assert body["data"]["shop_id"] == "taobao-local"
    assert body["data"]["shop_name"] == "猫咪宝贝"
    assert platform_api.shop.read_account_identity.call_args.kwargs.get("platform") == "taobao"


@pytest.mark.parametrize("platform", (None, True, 1, [], {}, "tmall", "invalid", ""))
def test_add_rejects_invalid_platform_without_mutation(platform_api, platform):
    original = copy.deepcopy(platform_api.shop.registry)
    response = platform_api.client.post("/api/shop/add", json={"platform": platform})
    assert response.status_code == 400
    assert response.get_json()["success"] is False
    assert platform_api.shop.registry == original
    assert platform_api.settings.updates == []
    platform_api.browser_open.assert_not_called()


@pytest.mark.parametrize("open_browser", (True, False))
def test_add_taobao_binds_platform_and_opens_its_own_login_page(platform_api, open_browser):
    """淘宝账户和抖店走同一套添加流程：需要登录就打开它的登录页。

    早先这里断言 ``browser_opened is False`` 且**不打开浏览器**，因为当时
    淘宝只做本地资料准备。现在淘宝也要真实登录才能查账户身份，所以
    ``open_browser=True`` 时必须真的打开**淘宝**的登录页，不能拿抖店的地址顶替。
    """
    response = platform_api.client.post(
        "/api/shop/add", json={"platform": "taobao", "label": "新淘宝备注", "open_browser": open_browser}
    )
    assert response.status_code == 200
    body = response.get_json()
    assert body["success"] is True
    assert body["data"]["platform"] == "taobao"
    assert body["data"]["browser_opened"] is open_browser
    active = platform_api.shop.registry["active_profile"]
    assert platform_api.shop.registry["profiles"][active]["platform"] == "taobao"
    assert platform_api.shop.registry["profiles"][active]["label"] == "新淘宝备注"
    assert platform_api.settings.automation["upload_browser_profile"] == "upload-browser-profile"
    assert platform_api.settings.updates == []
    if open_browser:
        platform_api.browser_open.assert_called_once()
        assert "taobao.com" in platform_api.browser_open.call_args.args[0]
    else:
        platform_api.browser_open.assert_not_called()


def test_add_without_platform_preserves_legacy_douyin_login(platform_api):
    response = platform_api.client.post("/api/shop/add", json={})
    assert response.status_code == 200
    body = response.get_json()
    assert body["success"] is True
    assert body["data"]["platform"] == "douyin"
    assert body["data"]["browser_opened"] is True
    assert platform_api.shop.created[0]["platform"] == "douyin"
    platform_api.browser_open.assert_called_once()
    assert platform_api.browser_open.call_args.args[0] == "https://fxg.jinritemai.com/ffa/mshop/homepage/index"


@pytest.mark.parametrize("open_browser", (True, False))
def test_switch_to_taobao_keeps_douyin_profile_setting(platform_api, open_browser):
    response = platform_api.client.post(
        "/api/shop/switch", json={"profile_name": "taobao-local", "open_browser": open_browser}
    )
    assert response.status_code == 200
    body = response.get_json()
    assert body["success"] is True
    assert body["data"]["platform"] == "taobao"
    assert body["data"]["browser_opened"] is open_browser
    assert platform_api.shop.registry["active_profile"] == "taobao-local"
    assert platform_api.settings.automation["upload_browser_profile"] == "upload-browser-profile"
    assert platform_api.settings.updates == []
    if open_browser:
        platform_api.browser_open.assert_called_once()
        assert "taobao.com" in platform_api.browser_open.call_args.args[0]
    else:
        platform_api.browser_open.assert_not_called()


def test_switch_uses_target_binding_and_douyin_login(platform_api):
    platform_api.shop.registry["active_profile"] = "taobao-local"
    response = platform_api.client.post(
        "/api/shop/switch", json={"profile_name": "douyin-second", "open_browser": True}
    )
    assert response.status_code == 200
    body = response.get_json()
    assert body["success"] is True
    assert body["data"]["platform"] == "douyin"
    assert body["data"]["browser_opened"] is True
    assert platform_api.shop.registry["active_profile"] == "douyin-second"
    platform_api.browser_open.assert_called_once()


def test_switch_unknown_profile_cannot_create_a_douyin_account(platform_api):
    before = copy.deepcopy(platform_api.shop.registry)
    response = platform_api.client.post("/api/shop/switch", json={"profile_name": "not-registered"})
    assert response.status_code in (400, 404)
    assert response.get_json()["success"] is False
    assert platform_api.shop.registry == before
    assert platform_api.shop.activations == []
    platform_api.browser_open.assert_not_called()


def test_forget_active_account_through_raw_name_alias_removes_canonical_profile(platform_api, monkeypatch):
    """用原始中文名移除当前账户：必须落到 slug 化后的那一条记录上。

    早先这里要求 409「先切换」，于是「登录错了账户」时用户被卡住——错的就是当前账户。
    现在允许移除，但**别名必须解析成规范的 profile 标识**，不能因为名字对不上
    就删错记录、更不能假装成功。
    """
    monkeypatch.syspath_prepend(str(PROJECT_ROOT))
    real_shop_session = importlib.import_module("src.shop_session")
    raw_name = "我的淘宝主账户"
    canonical = real_shop_session.slugify_profile_name(raw_name)
    assert canonical != raw_name
    platform_api.shop.registry["active_profile"] = canonical
    platform_api.shop.registry["profiles"][canonical] = {
        "profile_name": canonical, "platform": "taobao", "label": raw_name,
    }
    # 空默认占位必须存在：移除当前账户后 active 要交回它，否则后续读取会失败。
    platform_api.shop.registry["profiles"][FakeShopSession.DEFAULT_PROFILE_NAME] = empty_default_entry()
    monkeypatch.setattr(platform_api.shop, "slugify_profile_name", real_shop_session.slugify_profile_name)

    response = platform_api.client.post("/api/shop/forget", json={"profile_name": raw_name})
    assert response.status_code == 200
    body = response.get_json()
    assert body["success"] is True
    # 落到规范标识上，而不是原始名字。
    assert platform_api.shop.removed == [canonical]
    assert canonical not in platform_api.shop.registry["profiles"]
    assert platform_api.shop.registry["active_profile"] == FakeShopSession.DEFAULT_PROFILE_NAME
    platform_api.browser_open.assert_not_called()


def empty_default_entry():
    return {
        "profile_name": FakeShopSession.DEFAULT_PROFILE_NAME,
        "platform": "douyin", "label": None, "shop_id": None, "shop_name": None,
        "created_at": "2026-10-03T10:00:00", "last_seen_at": None,
        "seen_count": 0, "history": [],
    }


def test_empty_nonactive_default_can_be_forgotten(platform_api):
    name = platform_api.shop.DEFAULT_PROFILE_NAME
    platform_api.shop.registry["profiles"][name] = empty_default_entry()
    platform_api.shop.registry["active_profile"] = "taobao-local"
    other_entries = copy.deepcopy({
        key: entry for key, entry in platform_api.shop.registry["profiles"].items() if key != name
    })
    response = platform_api.client.post("/api/shop/forget", json={"profile_name": name})
    assert response.status_code == 200
    assert response.get_json()["success"] is True
    assert platform_api.shop.removed == [name]
    assert platform_api.shop.registry["profiles"] == other_entries
    assert platform_api.shop.registry["active_profile"] == "taobao-local"
    platform_api.browser_open.assert_not_called()
    platform_api.shop.read_shop_identity.assert_not_called()


@pytest.mark.parametrize("failure_site", ("read", "save"))
@pytest.mark.parametrize("error_type", (OSError, ValueError))
def test_forget_registry_read_or_save_failure_is_visible(platform_api, monkeypatch, failure_site, error_type):
    name = platform_api.shop.DEFAULT_PROFILE_NAME
    platform_api.shop.registry["profiles"][name] = empty_default_entry()
    platform_api.shop.registry["active_profile"] = "taobao-local"
    before = copy.deepcopy(platform_api.shop.registry)
    message = "读取注册表失败" if failure_site == "read" else "保存注册表失败"
    operation = "load_registry" if failure_site == "read" else "remove_profile"
    failing = Mock(side_effect=error_type(message))
    monkeypatch.setattr(platform_api.shop, operation, failing)
    response = platform_api.client.post("/api/shop/forget", json={"profile_name": name})
    assert response.status_code == 503
    assert response.get_json()["success"] is False
    assert message in response.get_json()["msg"]
    failing.assert_called_once()
    assert platform_api.shop.registry == before
    assert platform_api.shop.registry["active_profile"] == "taobao-local"
    platform_api.browser_open.assert_not_called()


def test_forget_missing_account_returns_not_found_without_change(platform_api):
    before = copy.deepcopy(platform_api.shop.registry)
    response = platform_api.client.post("/api/shop/forget", json={"profile_name": "not-registered"})
    assert response.status_code == 404
    assert response.get_json()["success"] is False
    assert platform_api.shop.registry == before
    platform_api.browser_open.assert_not_called()


@pytest.mark.parametrize("profile_name", ([], "", " ", None))
def test_forget_invalid_name_cannot_turn_into_empty_default(platform_api, profile_name):
    name = platform_api.shop.DEFAULT_PROFILE_NAME
    platform_api.shop.registry["profiles"][name] = empty_default_entry()
    platform_api.shop.registry["active_profile"] = "taobao-local"
    before = copy.deepcopy(platform_api.shop.registry)
    response = platform_api.client.post("/api/shop/forget", json={"profile_name": profile_name})
    assert response.status_code == 400
    assert response.get_json()["success"] is False
    assert platform_api.shop.removed == []
    assert platform_api.shop.registry == before
    platform_api.browser_open.assert_not_called()


@pytest.mark.parametrize("body", ([], None, ""))
def test_forget_invalid_json_shape_does_not_claim_success(platform_api, body):
    before = copy.deepcopy(platform_api.shop.registry)
    response = platform_api.client.post(
        "/api/shop/forget", data=json.dumps(body), content_type="application/json"
    )
    assert response.status_code == 400
    assert response.get_json()["success"] is False
    assert platform_api.shop.removed == []
    assert platform_api.shop.registry == before


@pytest.mark.parametrize("field,value", (
    ("shop_id", "confirmed-shop"),
    ("shop_name", "实测历史店铺"),
    ("label", "用户自定义备注"),
    ("seen_count", 1),
    ("last_seen_at", "2026-10-03T10:00:00"),
    ("history", [{"shop_id": "old-shop", "shop_name": "旧店铺"}]),
))
def test_default_with_identity_label_or_history_remains_protected(platform_api, field, value):
    name = platform_api.shop.DEFAULT_PROFILE_NAME
    entry = empty_default_entry()
    entry[field] = value
    platform_api.shop.registry["profiles"][name] = entry
    platform_api.shop.registry["active_profile"] = "taobao-local"
    before = copy.deepcopy(platform_api.shop.registry)
    response = platform_api.client.post("/api/shop/forget", json={"profile_name": name})
    assert response.status_code == 409
    assert response.get_json()["success"] is False
    assert platform_api.shop.removed == []
    assert platform_api.shop.registry == before


def test_even_empty_default_can_be_removed_while_active(platform_api):
    """默认空占位在「它是当前账户」时也允许移除。

    早先这里要求 409「先切换到其他账户」，可「登录错了账户」场景下那个错账户
    就是当前账户，等于把人卡住。现在删完把 active 交回默认空占位，
    这里断言 registry 状态与移除请求，而不是只看状态码。
    """
    name = platform_api.shop.DEFAULT_PROFILE_NAME
    platform_api.shop.registry["profiles"][name] = empty_default_entry()
    response = platform_api.client.post("/api/shop/forget", json={"profile_name": name})
    assert response.status_code == 200
    body = response.get_json()
    assert body["success"] is True
    assert platform_api.shop.removed == [name]
    assert name not in platform_api.shop.registry["profiles"]
    assert platform_api.shop.registry["active_profile"] == name
    assert body["data"]["active_profile"] == name
    # 默认必须「只摘记录、不动磁盘」：删错账户不能顺手把登录资料删掉。
    assert platform_api.shop.purge_requests == [
        {"profile_name": name, "purge_directory": False}
    ]


def test_missing_default_switch_is_not_a_bootstrap_or_creation_request(platform_api):
    name = platform_api.shop.DEFAULT_PROFILE_NAME
    del platform_api.shop.registry["profiles"][name]
    platform_api.shop.registry["active_profile"] = "taobao-local"
    before = copy.deepcopy(platform_api.shop.registry)
    response = platform_api.client.post("/api/shop/switch", json={"profile_name": name})
    assert response.status_code == 404
    assert response.get_json()["success"] is False
    assert platform_api.shop.registry == before
    assert platform_api.shop.activations == []
    assert platform_api.shop.created == []
    platform_api.browser_open.assert_not_called()


@pytest.mark.parametrize("route,body", (
    ("/api/upload/start", {}),
    ("/api/upload/start-all", {}),
    ("/api/taobao/publish/prepare", {"record_id": 7}),
    ("/api/taobao/publish/export", {"record_id": 7}),
))
def test_nonempty_registry_with_missing_default_active_fails_before_work(platform_api, route, body):
    del platform_api.shop.registry["profiles"][platform_api.shop.DEFAULT_PROFILE_NAME]
    before = copy.deepcopy(platform_api.shop.registry)
    response = platform_api.client.post(route, json=body)
    assert response.status_code == 503
    assert response.get_json()["success"] is False
    assert platform_api.shop.registry == before
    assert platform_api.db_calls == []
    assert platform_api.tasks == {}
    assert platform_api.workers == []


def test_truly_empty_legacy_registry_keeps_douyin_bootstrap_compatibility(platform_api):
    platform_api.shop.registry["profiles"] = {}
    response = platform_api.client.post("/api/upload/start", json={})
    assert response.status_code == 200
    assert response.get_json()["success"] is True
    task = platform_api.tasks[response.get_json()["data"]["task_id"]]
    assert task["platform"] == "douyin"
    assert task["account_profile"] == platform_api.shop.DEFAULT_PROFILE_NAME
    assert platform_api.shop.registry["profiles"] == {}
    assert platform_api.shop.created == []
    assert len(platform_api.workers) == 1


@pytest.mark.parametrize("route", ("/api/upload/start", "/api/upload/start-all"))
def test_legacy_douyin_upload_without_platform_still_creates_task(platform_api, route):
    response = platform_api.client.post(route, json={})
    assert response.status_code == 200
    body = response.get_json()
    assert body["success"] is True
    task_id = body["data"]["task_id"]
    assert platform_api.tasks[task_id]["platform"] == "douyin"
    assert len(platform_api.workers) == 1


def test_douyin_current_still_uses_identity_probe(platform_api):
    platform_api.browser_resolver.return_value = ("127.0.0.1:9400", {}, "open_browser")
    platform_api.shop.read_account_identity.return_value = {
        "status": "logged_in", "shop_id": "douyin-1", "shop_name": "本次实测店铺",
    }
    response = platform_api.client.get("/api/shop/current")
    assert response.status_code == 200
    body = response.get_json()
    assert body["success"] is True
    assert body["data"]["platform"] == "douyin"
    assert body["data"]["status"] == "logged_in"
    assert body["data"]["shop_name"] == "本次实测店铺"
    # 实测入口统一走 read_account_identity，且必须按抖店平台分派。
    platform_api.shop.read_account_identity.assert_called_once_with(
        "127.0.0.1:9400", platform="douyin", timeout=6.0
    )


@pytest.mark.parametrize("body", ([], "bad", None))
def test_add_requires_json_object(platform_api, body):
    before = copy.deepcopy(platform_api.shop.registry)
    response = platform_api.client.post(
        "/api/shop/add", data=json.dumps(body), content_type="application/json"
    )
    assert response.status_code == 400
    assert response.get_json()["success"] is False
    assert platform_api.shop.registry == before
    platform_api.browser_open.assert_not_called()


def test_add_empty_legacy_body_still_creates_douyin_account(platform_api):
    response = platform_api.client.post("/api/shop/add")
    assert response.status_code == 200
    assert response.get_json()["success"] is True
    assert response.get_json()["data"]["platform"] == "douyin"
    assert platform_api.shop.created[0]["platform"] == "douyin"
    platform_api.browser_open.assert_called_once()


@pytest.mark.parametrize("label", (42, True, [], "名" * 61))
def test_add_rejects_invalid_label_without_creating_account(platform_api, label):
    response = platform_api.client.post("/api/shop/add", json={"platform": "taobao", "label": label})
    assert response.status_code == 400
    assert response.get_json()["success"] is False
    assert platform_api.shop.created == []
    assert platform_api.shop.activations == []


@pytest.mark.parametrize("route,body", (
    ("/api/shop/add", {"platform": "taobao"}),
    ("/api/shop/switch", {"profile_name": "taobao-local"}),
))
@pytest.mark.parametrize("value", ("false", 0, 1, None))
def test_open_browser_is_strict_boolean(platform_api, route, body, value):
    before = copy.deepcopy(platform_api.shop.registry)
    response = platform_api.client.post(route, json=dict(body, open_browser=value))
    assert response.status_code == 400
    assert response.get_json()["success"] is False
    assert platform_api.shop.registry == before
    platform_api.browser_open.assert_not_called()


@pytest.mark.parametrize("route,body", (
    ("/api/shop/add", {"platform": "taobao"}),
    ("/api/shop/switch", {"profile_name": "taobao-local", "open_browser": False}),
    ("/api/shop/forget", {"profile_name": "taobao-local"}),
))
@pytest.mark.parametrize("status", ("pending", "running"))
def test_pending_or_running_publish_blocks_account_changes(platform_api, route, body, status):
    platform_api.tasks["existing-task"] = {"status": status, "platform": "douyin"}
    before = copy.deepcopy(platform_api.shop.registry)
    response = platform_api.client.post(route, json=body)
    assert response.status_code == 409
    assert response.get_json()["success"] is False
    assert platform_api.shop.registry == before
    assert platform_api.shop.created == []
    assert platform_api.shop.activations == []
    platform_api.browser_open.assert_not_called()


@pytest.mark.parametrize('status', ('pending', 'running'))
def test_taobao_fill_blocks_account_switch_and_preserves_its_browser(platform_api, status):
    platform_api.namespace['_taobao_tasks']['taobao-active'] = {'status': status, 'platform': 'taobao'}
    before = copy.deepcopy(platform_api.shop.registry)
    response = platform_api.client.post('/api/shop/switch', json={'profile_name': 'taobao-local'})
    assert response.status_code == 409 and response.json['success'] is False
    assert platform_api.shop.registry == before
    platform_api.browser_open.assert_not_called()
    platform_api.browser_reset.assert_not_called()


@pytest.mark.parametrize("route,body", (
    ("/api/upload/start", {}),
    ("/api/upload/start-all", {}),
    ("/api/upload/ensure-session", {}),
    ("/api/taobao/publish/prepare", {"record_id": 7}),
    ("/api/taobao/publish/export", {"record_id": 7}),
))
def test_registry_read_error_cannot_fall_back_to_douyin(platform_api, monkeypatch, route, body):
    monkeypatch.setattr(platform_api.shop, "load_registry", Mock(side_effect=ValueError("注册表损坏")))
    response = platform_api.client.post(route, json=body)
    assert response.status_code == 503
    assert response.get_json()["success"] is False
    assert "注册表损坏" in response.get_json()["msg"]
    assert platform_api.db_calls == []
    assert platform_api.tasks == {}
    assert platform_api.workers == []


@pytest.mark.parametrize("bad_platform", (None, "other", 5))
def test_explicit_invalid_active_platform_cannot_be_legacy_default(platform_api, bad_platform):
    platform_api.shop.registry["profiles"]["upload-browser-profile"]["platform"] = bad_platform
    response = platform_api.client.post("/api/upload/start", json={})
    assert response.status_code == 503
    assert response.get_json()["success"] is False
    assert platform_api.tasks == {}
    assert platform_api.workers == []


def test_missing_nondefault_active_account_fails_closed(platform_api):
    platform_api.shop.registry["active_profile"] = "missing-account"
    response = platform_api.client.post("/api/upload/start", json={})
    assert response.status_code == 503
    assert response.get_json()["success"] is False
    assert platform_api.tasks == {}
    assert platform_api.shop.created == []


def test_observing_other_browser_cannot_switch_selected_account(platform_api):
    """浏览器实测到的店铺属于**另一个** profile 时，必须报冲突而不是改写当前账户。

    这里最容易出错的地方是「谁归属谁」：浏览器目录属于 douyin-second，
    而当前选中的是 upload-browser-profile，所以实测结果不能记到当前账户头上。
    """
    platform_api.browser_resolver.return_value = (
        "127.0.0.1:9401",
        {"user_data_dir": platform_api.shop.profile_dir("douyin-second")},
        "open_browser",
    )
    platform_api.shop.read_account_identity.return_value = {
        "status": "logged_in", "shop_id": "douyin-2", "shop_name": "浏览器另一家店",
    }
    response = platform_api.client.get("/api/shop/current")
    assert response.status_code == 200
    payload = response.get_json()["data"]
    assert payload["status"] == "conflict"
    assert payload["shop_id"] is None
    assert payload["shop_name"] is None
    assert platform_api.shop.registry["active_profile"] == "upload-browser-profile"
    assert platform_api.shop.activations == []


@pytest.mark.parametrize("route,active,stale", (
    ("/api/upload/start", "douyin-second", "upload-browser-profile"),
    ("/api/upload/start-all", "douyin-second", "upload-browser-profile"),
    ("/api/taobao/publish/prepare", "taobao-local", "another-taobao"),
    ("/api/taobao/publish/export", "taobao-local", "another-taobao"),
))
def test_stale_same_platform_account_is_rejected_before_work(platform_api, route, active, stale):
    platform_api.shop.registry["active_profile"] = active
    platform_api.shop.registry["profiles"]["another-taobao"] = {
        "profile_name": "another-taobao", "platform": "taobao", "label": "另一淘宝账户",
    }
    response = platform_api.client.post(route, json={"record_id": 7, "account_profile": stale})
    assert response.status_code == 409
    assert response.get_json()["code"] == "ACCOUNT_CHANGED"
    assert platform_api.db_calls == []
    assert platform_api.tasks == {}
    assert platform_api.workers == []
    platform_api.browser_open.assert_not_called()


@pytest.mark.parametrize("route,active", (
    ("/api/upload/start", "douyin-second"),
    ("/api/upload/start-all", "douyin-second"),
    ("/api/taobao/publish/prepare", "taobao-local"),
    ("/api/taobao/publish/export", "taobao-local"),
))
@pytest.mark.parametrize("account_profile", (True, 1, [], {}, "", " "))
def test_invalid_account_snapshot_is_rejected_before_work(platform_api, route, active, account_profile):
    platform_api.shop.registry["active_profile"] = active
    response = platform_api.client.post(route, json={"record_id": 7, "account_profile": account_profile})
    assert response.status_code == 400
    assert response.get_json()["success"] is False
    assert platform_api.db_calls == []
    assert platform_api.tasks == {}
    assert platform_api.workers == []


def test_account_switch_waits_for_task_creation_then_rejects(platform_api, monkeypatch):
    """门禁检查与创建 pending 任务之间，账户切换不能插入。"""
    checked_platform = threading.Event()
    continue_creation = threading.Event()
    switch_waiting = threading.Event()
    switch_finished = threading.Event()
    results = {}
    exceptions = []

    class ObservedRLock:
        def __init__(self):
            self.lock = threading.RLock()
            self.counter_lock = threading.Lock()
            self.attempts = 0

        def __enter__(self):
            with self.counter_lock:
                self.attempts += 1
                if self.attempts == 2:
                    switch_waiting.set()
            self.lock.acquire()
            return self

        def __exit__(self, *_exc):
            self.lock.release()

    def pause_after_platform_check(_data):
        checked_platform.set()
        if not continue_creation.wait(5):
            raise AssertionError("测试未允许任务创建继续")
        return True, False

    monkeypatch.setitem(platform_api.namespace, "_shop_account_lock", ObservedRLock())
    monkeypatch.setitem(platform_api.namespace, "_resolve_upload_stop_before_submit", pause_after_platform_check)

    def invoke(name, route, body):
        try:
            results[name] = platform_api.app.test_client().post(route, json=body)
        except Exception as exc:
            exceptions.append(exc)
        finally:
            if name == "switch":
                switch_finished.set()

    upload = threading.Thread(target=invoke, args=("upload", "/api/upload/start", {}))
    switch = threading.Thread(target=invoke, args=(
        "switch", "/api/shop/switch", {"profile_name": "taobao-local", "open_browser": False}
    ))
    upload.start()
    try:
        assert checked_platform.wait(3)
        switch.start()
        assert switch_waiting.wait(3)
        assert not switch_finished.is_set()
    finally:
        continue_creation.set()
        upload.join(5)
        if switch.ident is not None:
            switch.join(5)
    assert not upload.is_alive()
    assert not switch.is_alive()
    assert exceptions == []
    assert results["upload"].status_code == 200
    assert results["upload"].get_json()["success"] is True
    assert results["switch"].status_code == 409
    assert platform_api.shop.registry["active_profile"] == "upload-browser-profile"
    assert len(platform_api.tasks) == 1
    assert next(iter(platform_api.tasks.values()))["status"] == "pending"

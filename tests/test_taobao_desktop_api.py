# -*- coding: utf-8 -*-
"""淘宝桌面 HTTP 路由：真实离线模块、隔离数据库与运行目录。"""

from __future__ import annotations

import ast
import copy
import csv
import importlib
import json
import os
import sys
import tempfile
import threading
from functools import wraps
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from flask import Flask, jsonify, request
from PIL import Image


PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_PATH = PROJECT_ROOT / "tauri-app" / "python-sidecar" / "app.py"
FUNCTIONS = {
    "_load_taobao_desktop",
    "_taobao_product_request",
    "taobao_readiness",
    "taobao_prepare",
    "taobao_export",
    "taobao_publish_start",
    # ⚠️ **这三个是 `taobao_publish_start` 会调到的助手**，原先不在名单里，
    # 于是夹具把它 exec 出来时根本跑不到真正的拒绝逻辑——
    # 测试"通过"是因为更早的 NameError 被当成拒绝路径了。
    "_taobao_cdp_list_url",
    "_resolve_active_shop_browser",
    "_taobao_product_request_payload",
    # ⚠️ 参数解析与校验的**纯函数**也必须在名单里：`taobao_publish_start` 会调它，
    # 不在名单里就只会撞上"夹具缺少替身"，而看不到真正的参数拒绝逻辑。
    # 它不依赖 Flask/账户/数据库，直接 exec 即可。
    "_parse_taobao_publish_options",
    "_ensure_taobao_fill_browser",
    "_account_change_blocked",
    "_load_taobao_pipeline",
    "_active_shop_account",
    "_require_publish_platform",
    "_with_shop_account_lock",
}
PRODUCT_ROUTES = ("prepare", "export")
#: 夹具要一并 exec 的**模块级常量**。
#:
#: 上架方式的允许值清单只有**一份**（在 `app.py` 里），校验必须用真正那份——
#: 在夹具里另写一份的话，两边写歪了测试还会假绿。
CONSTANTS = {"TAOBAO_LISTING_MODES"}


def test_custom_sku_mode_is_preserved_by_the_real_request_translator(api_case):
    translate = api_case.namespace['_taobao_product_request_payload']
    assert translate({'sku_mode': 'custom'})['sku_mode'] == 'custom'
    assert translate({'sku_mode': 'standard'})['sku_mode'] == 'standard'
    assert 'sku_mode' not in translate({})


@pytest.mark.parametrize('mode', [None, '', 'guess', True, [], {}])
def test_invalid_sku_mode_is_rejected_without_browser_work(api_case, mode):
    with pytest.raises(ValueError, match='sku_mode'):
        api_case.namespace['_taobao_product_request_payload']({'sku_mode': mode})


@pytest.fixture
def api_case(monkeypatch):
    """保留真实路由装饰器；仅替代数据库及运行目录定位。"""
    scratch_root = PROJECT_ROOT / ".tmp" / "taobao-desktop-api-tests"
    scratch_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="case-", dir=scratch_root) as temporary:
        root = Path(temporary).resolve()
        assert root.is_relative_to(scratch_root.resolve())
        product = root / "商品资料"
        main = product / "主图" / "800" / "主图01.jpg"
        sku_image = product / "SKU" / "白色均码.jpg"
        for image in (main, sku_image):
            image.parent.mkdir(parents=True, exist_ok=True)
            Image.new("RGB", (800, 800), "white").save(image, "JPEG")
        original = {
            "id": 7,
            "name": "商品七",
            "title": "棉质长筒袜",
            "path": str(product),
            "clazz": "2",
            "shipping_template": "抖店中通包邮模板",
            "status": 1,
            "publish_time": "2026-10-03T10:00:00",
            "content": json.dumps([
                {"name": "白色均码", "path": str(sku_image), "price": 3.25}
            ], ensure_ascii=False),
        }
        record_data = copy.deepcopy(original)

        class RecordMissing(Exception):
            pass

        class FakeRecord:
            DoesNotExist = RecordMissing
            requests = []

            @classmethod
            def get_by_id(cls, record_id):
                cls.requests.append(record_id)
                if record_id != record_data["id"]:
                    raise cls.DoesNotExist()
                return SimpleNamespace(__data__=record_data)

        monkeypatch.syspath_prepend(str(PROJECT_ROOT / "taobao-publisher"))
        desktop = importlib.import_module("taobao_publish.desktop")
        forbidden = Mock(side_effect=AssertionError("离线 HTTP 路由不得调用发布流水线或 CDP"))
        for module_name, symbol in (
            ("taobao_publish", "run"),
            ("taobao_publish.pipeline", "run"),
            ("taobao_publish.cdp", "probe_session"),
            ("taobao_publish.stages", "probe_session"),
        ):
            monkeypatch.setattr(importlib.import_module(module_name), symbol, forbidden)

        runtime = root / "运行数据"
        resolved_names = []

        def resolve_data_file(name):
            resolved_names.append(name)
            return runtime / name

        app = Flask("taobao-desktop-api-test")
        app.config.update(TESTING=True)
        upload_tasks = {"douyin-existing": {"platform": "douyin", "status": "running"}}
        namespace = {
            "__name__": "taobao_desktop_api_isolated",
            "app": app,
            "os": os,
            "sys": sys,
            "repo_root": str(PROJECT_ROOT),
            "request": request,
            "jsonify": jsonify,
            "Record": FakeRecord,
            "wraps": wraps,
            "_shop_account_lock": threading.RLock(),
            "shop_session": SimpleNamespace(
                DEFAULT_PROFILE_NAME="upload-browser-profile",
                load_registry=lambda: {
                    "active_profile": "taobao-test",
                    "profiles": {"taobao-test": {"platform": "taobao", "label": "测试淘宝账户"}},
                },
                slugify_profile_name=lambda name: name,
                normalize_platform=lambda value: value,
            ),
            "resolve_data_file": resolve_data_file,
            # 真身由 `app.py` 从别处 import（`app.py` 里那个名字缩进 4、在 import 块中），
            # 按名单抽函数时带不过来 —— 给一个语义等价的替身：
            # 「去掉协议前缀，取 host:port」。够路由判断「有没有可用的浏览器」。
            # **本夹具没有浏览器**：GUI 宿主不存在、账户里也没有可用浏览器。
            # 这条链上每个函数都如实返回「没有」，让路由走到
            # 「没有找到淘宝账户的浏览器」——那正是测试要断言的拒绝路径。
            "_get_gui_page_debug_address": lambda: "",
            # 响应助手，本体由 `app.py` 从别处 import（与 `_normalize_debug_address`
            # 在同一个 `from ... import (` 块里），抽函数时带不过来。
            # 替身按契约写：返回 `(Flask 响应, 状态码)`。
            "api_error": lambda msg=None, data=None, **kw: (
                jsonify(success=False, msg=msg, **({"data": data} if data else {})), 400
            ),
            "api_ok": lambda msg=None, data=None, **kw: (
                jsonify(success=True, msg=msg, **({"data": data} if data else {})), 200
            ),
            "_resolve_taobao_shop_browser": lambda *_a, **_k: ("", None, ""),
            "_resolve_active_shop_browser": lambda *_a, **_k: ("", None, ""),
            "_normalize_debug_address": lambda value: (
                str(value or "").strip().split("://", 1)[-1].split("/", 1)[0].strip()
            ),
            "_upload_tasks": upload_tasks,
            "_upload_tasks_lock": threading.RLock(),
            "_taobao_tasks": {}, "_taobao_tasks_lock": threading.RLock(),
            "_activate_shop_profile": forbidden,
            "_run_upload_task": forbidden,
        }
        tree = ast.parse(APP_PATH.read_text(encoding="utf-8"))
        definitions = [
            node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name in FUNCTIONS
        ]
        assert {node.name for node in definitions} == FUNCTIONS
        # 模块级常量：只取**校验真正用到的那份允许值清单**，避免在夹具里另写一份。
        constants = [
            node for node in tree.body
            if isinstance(node, ast.Assign)
            and any(getattr(t, "id", None) in CONSTANTS for t in node.targets)
        ]
        assert {t.id for node in constants for t in node.targets if hasattr(t, "id")} == CONSTANTS
        definitions = constants + definitions
        # ⚠️ **自动补齐夹具没提供的模块级名字。**
        #
        # 被抽出来的函数会引用 `app.py` 从别处 import 的名字（例如
        # `_normalize_debug_address`、`_get_gui_page_debug_address`）。
        # 白名单式地逐个补，**补一个冒一个**——本轮就补了四轮还没完。
        #
        # 这里扫出它们的**自由名字**，缺谁补谁。替身被调用时**抛错**而不是返回 None：
        # 返回假值会让测试"通过"却没走到真实逻辑（`test_publish_start` 就吃过这个亏，
        # NameError 被当成了拒绝路径）。
        # `app.py` 顶层的**真实名字**（定义 + 导入）。
        #
        # 只给这些名字补替身——**判据精确**，所以拼写错误不会被当成"缺的助手"吞掉。
        _app_top_names = set()
        for _top in tree.body:
            if isinstance(_top, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                _app_top_names.add(_top.name)
            elif isinstance(_top, ast.Import):
                for _alias in _top.names:
                    _app_top_names.add((_alias.asname or _alias.name).split(".")[0])
            elif isinstance(_top, ast.ImportFrom):
                for _alias in _top.names:
                    _app_top_names.add(_alias.asname or _alias.name)

        _provided = set(namespace)
        for _node in definitions:
            for _child in ast.walk(_node):
                if isinstance(_child, ast.Name) and isinstance(_child.ctx, ast.Load):
                    _name = _child.id
                    if _name in _provided or _name in globals() or _name in dir(__builtins__):
                        continue
                    # **判据精确**：这个名字必须真的在 `app.py` 顶层出现过。
                    # 这样拼写错误不会被当成"缺的助手"静默吞掉。
                    if _name not in _app_top_names:
                        continue
                    # ⚠️ **不要按前缀猜返回值的形状。**
                    #
                    # 试过「`_resolve_*` / `_get_*` 一律返回 None」——结果
                    # `_resolve_active_shop_browser` 返回三元组，`None` 解不开，
                    # 报出来的是 `TypeError: cannot unpack non-iterable NoneType`，
                    # **比原来那句「夹具缺少替身：xxx」难查得多**。
                    # 缺什么就明确报什么，缺的那个显式补。
                    namespace[_name] = (
                        lambda *_a, _n=_name, **_k: (_ for _ in ()).throw(
                            AssertionError(
                                "夹具缺少替身：{}（测试走到了未准备的代码路径）".format(_n)
                            )
                        )
                    )

        exec(compile(ast.Module(body=definitions, type_ignores=[]), str(APP_PATH), "exec"), namespace)
        case = SimpleNamespace(
            client=app.test_client(),
            app=app,
            namespace=namespace,
            desktop=desktop,
            root=root,
            product=product,
            main=main,
            sku_image=sku_image,
            runtime=runtime,
            record=record_data,
            original=original,
            record_class=FakeRecord,
            resolved_names=resolved_names,
            forbidden=forbidden,
            upload_tasks=upload_tasks,
        )
        yield case
        assert record_data == original
        assert upload_tasks == {"douyin-existing": {"platform": "douyin", "status": "running"}}
        forbidden.assert_not_called()


@pytest.mark.parametrize("route", PRODUCT_ROUTES)
@pytest.mark.parametrize("raw", ('[1]', 'null', '"text"', '{broken'))
def test_requires_json_object(api_case, route, raw):
    response = api_case.client.post(
        f"/api/taobao/publish/{route}", data=raw, content_type="application/json"
    )
    assert response.status_code == 400
    assert response.get_json()["success"] is False
    assert api_case.record_class.requests == []
    assert not api_case.runtime.exists()


@pytest.mark.parametrize("route", PRODUCT_ROUTES)
@pytest.mark.parametrize("key", ("output_base", "product_dir", "cdp_list_url", "allow_write"))
def test_rejects_unknown_top_level_keys(api_case, route, key):
    response = api_case.client.post(
        f"/api/taobao/publish/{route}", json={"record_id": 7, key: "unexpected"}
    )
    assert response.status_code == 400
    assert response.get_json()["success"] is False
    assert api_case.record_class.requests == []
    assert not api_case.runtime.exists()


@pytest.mark.parametrize("route", PRODUCT_ROUTES)
@pytest.mark.parametrize("record_id", (True, False, 7.0, 7.5, "7", 0, -1, None))
def test_rejects_invalid_record_ids(api_case, route, record_id):
    response = api_case.client.post(
        f"/api/taobao/publish/{route}", json={"record_id": record_id}
    )
    assert response.status_code == 400
    assert response.get_json()["success"] is False
    assert api_case.record_class.requests == []


@pytest.mark.parametrize("route", PRODUCT_ROUTES)
def test_missing_record_returns_not_found(api_case, route):
    response = api_case.client.post(f"/api/taobao/publish/{route}", json={"record_id": 99})
    assert response.status_code == 404
    assert response.get_json()["success"] is False
    assert api_case.record_class.requests == [99]
    assert not api_case.runtime.exists()


@pytest.mark.parametrize("route", PRODUCT_ROUTES)
@pytest.mark.parametrize("overrides", ([], "bad", None))
def test_overrides_must_be_object(api_case, route, overrides):
    response = api_case.client.post(
        f"/api/taobao/publish/{route}", json={"record_id": 7, "overrides": overrides}
    )
    assert response.status_code == 400
    assert response.get_json()["success"] is False
    assert api_case.record_class.requests == []


@pytest.mark.parametrize("route", PRODUCT_ROUTES)
def test_cannot_route_douyin_into_taobao(api_case, route):
    response = api_case.client.post(
        f"/api/taobao/publish/{route}", json={"record_id": 7, "platform": "douyin"}
    )
    assert response.status_code == 400
    assert response.get_json()["success"] is False
    assert api_case.record_class.requests == []


def test_readiness_is_real_and_offline(api_case):
    response = api_case.client.get("/api/taobao/readiness")
    assert response.status_code == 200
    body = response.get_json()
    assert body["success"] is True
    assert body["data"]["platform"] == "taobao"
    assert body["data"]["mode"] == "automated_pipeline"
    # ⚠️ 这两条曾经写死「还没实现」：`ready is False`、只有 2 个阶段、9 个未实现。
    # 流水线实现完之后它们就是错的——**改成从真实状态推**，
    # 这样以后加阶段也不用再改测试。
    assert body["data"]["automatic_publish_ready"] is True
    stages = body["data"]["implemented_stages"]
    assert stages, "至少要报告一个已实现阶段"
    assert stages[0] == "session", "阶段顺序从 session 开始"
    assert body["data"]["unimplemented_stages"] == [], "不应再有未实现阶段"
    assert api_case.record_class.requests == []
    assert api_case.resolved_names == []


def test_prepare_keeps_taobao_selling_fields_independent(api_case):
    response = api_case.client.post(
        "/api/taobao/publish/prepare", json={"record_id": 7, "account_profile": "taobao-test"}
    )
    assert response.status_code == 200
    body = response.get_json()
    assert body["success"] is True
    report = body["data"]
    assert report["platform"] == "taobao"
    assert report["account_profile"] == "taobao-test"
    # `automatic_publish_ready` 现在如实报 True（流水线已实现）；
    # `can_export` 仍然是 False——本地资料确实缺一口价与总库存。
    assert report["automatic_publish_ready"] is True
    assert report["can_export"] is False
    assert report["item_price"] is None
    assert report["total_stock"] is None
    assert report["skus"][0]["price"] is None
    assert report["skus"][0]["stock"] is None
    assert report["category_path"] == ""
    assert report["freight_template_name"] == ""
    missing = {check["field"] for check in report["checks"] if check["status"] == "missing"}
    assert {"item_price", "total_stock"}.issubset(missing)
    assert api_case.resolved_names == []
    assert not api_case.runtime.exists()


def test_export_requires_explicit_product_price_and_stock(api_case):
    response = api_case.client.post("/api/taobao/publish/export", json={"record_id": 7})
    assert response.status_code == 400
    assert response.get_json()["success"] is False
    assert api_case.resolved_names == ["taobao_publish_packets"]
    assert not api_case.runtime.exists()


@pytest.mark.parametrize("route", PRODUCT_ROUTES)
def test_unknown_override_cannot_choose_output_path(api_case, route):
    response = api_case.client.post(
        f"/api/taobao/publish/{route}",
        json={"record_id": 7, "overrides": {"output_base": str(api_case.product)}},
    )
    assert response.status_code == 400
    assert response.get_json()["success"] is False
    assert not api_case.runtime.exists()


def test_export_writes_fixed_new_packets_without_changing_source(api_case):
    request_body = {
        "record_id": 7,
        "platform": "taobao",
        "account_profile": "taobao-test",
        "overrides": {
            "title": "淘宝独立长筒袜标题",
            "item_price": 9.9,
            "total_stock": 0,
            "skus": [{"index": 0, "price": 12.5, "stock": 0}],
        },
    }
    before = {str(path): path.read_bytes() for path in api_case.product.rglob("*") if path.is_file()}
    reports = []
    for _ in range(2):
        response = api_case.client.post("/api/taobao/publish/export", json=request_body)
        assert response.status_code == 200, response.get_json()
        assert response.get_json()["success"] is True
        reports.append(response.get_json()["data"])
    assert api_case.resolved_names == ["taobao_publish_packets", "taobao_publish_packets"]
    assert reports[0]["packet_dir"] != reports[1]["packet_dir"]
    output_base = (api_case.runtime / "taobao_publish_packets").resolve()
    for report in reports:
        assert report["platform"] == "taobao"
        assert report["account_profile"] == "taobao-test"
        packet = Path(report["packet_dir"]).resolve()
        assert packet.parent == output_base
        assert packet.name.startswith("taobao-7-")
        manifest_path = Path(report["manifest_path"])
        assert manifest_path.parent == packet
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest["platform"] == "taobao"
        # mode 是**应用流水线**的模式；资料包本身的性质在 packet_kind。
        # （原先 manifest 会把 mode 覆盖成 manual_preparation，同键两义。）
        assert manifest["mode"] == "automated_pipeline"
        assert manifest["packet_kind"] == "manual_preparation"
        assert manifest["platform_published"] is False
        assert manifest["automatic_publish_ready"] is True
        assert manifest["title"] == "淘宝独立长筒袜标题"
        assert manifest["item_price"] == 9.9
        assert manifest["total_stock"] == 0
        assert manifest["skus"][0]["price"] == 12.5
        assert manifest["skus"][0]["stock"] == 0
        main_relative = manifest["assets"]["main"][0]
        assert not Path(main_relative).is_absolute()
        assert (packet / main_relative).read_bytes() == api_case.main.read_bytes()
        with Path(report["sku_csv_path"]).open(encoding="utf-8-sig", newline="") as stream:
            csv_rows = list(csv.DictReader(stream))
        assert csv_rows[0]["name"] == "白色均码"
        assert csv_rows[0]["price"] == "12.5"
        assert csv_rows[0]["stock"] == "0"
        assert "未发布商品" in (packet / "使用说明.txt").read_text(encoding="utf-8")
    after = {str(path): path.read_bytes() for path in api_case.product.rglob("*") if path.is_file()}
    assert after == before


@pytest.mark.parametrize("route", PRODUCT_ROUTES)
def test_record_sku_cannot_read_file_outside_product(api_case, monkeypatch, route):
    outside_image = api_case.root / "另一商品.jpg"
    Image.new("RGB", (800, 800), "blue").save(outside_image, "JPEG")
    outside_bytes = outside_image.read_bytes()
    with monkeypatch.context() as patch:
        patch.setitem(api_case.record, "content", json.dumps([
            {"name": "错误路径规格", "path": str(outside_image), "price": 1}
        ], ensure_ascii=False))
        response = api_case.client.post(
            f"/api/taobao/publish/{route}",
            json={"record_id": 7, "overrides": {"item_price": 9.9, "total_stock": 0}},
        )
    assert response.status_code == 400
    assert response.get_json()["success"] is False
    assert "超出当前记录目录" in response.get_json()["msg"]
    assert outside_image.read_bytes() == outside_bytes
    assert not api_case.runtime.exists()


def test_export_rejects_output_root_inside_source_product(api_case, monkeypatch):
    unsafe_output = api_case.product / "不能覆盖原始资料"
    before = {str(path): path.read_bytes() for path in api_case.product.rglob("*") if path.is_file()}
    with monkeypatch.context() as patch:
        patch.setitem(api_case.namespace, "resolve_data_file", lambda _name: unsafe_output)
        response = api_case.client.post(
            "/api/taobao/publish/export",
            json={"record_id": 7, "overrides": {"item_price": 9.9, "total_stock": 0}},
        )
    assert response.status_code == 400
    assert response.get_json()["success"] is False
    assert "不能位于原始商品资料目录内" in response.get_json()["msg"]
    assert not unsafe_output.exists()
    assert {str(path): path.read_bytes() for path in api_case.product.rglob("*") if path.is_file()} == before


#: 三种坏请求各自应当得到的拒绝理由（**当前的真实契约**）。
#:
#: ⚠️ 原版对三种都断言 `409 + TAOBAO_AUTO_PUBLISH_UNAVAILABLE`——
#: 那是**接口还没实现**时唯一的拒绝方式。现在接口实现了，
#: 校验各归各位，一刀切的 409 已经不成立。
#: （而且当时夹具漏了 `_taobao_cdp_list_url` 等助手，测试其实跑不到真正的逻辑。）
#: 坏请求：**只断言「被拒绝」，不断言具体文案**。
#:
#: ⚠️ 为什么不去比文案：这个夹具不是 `import app`，而是按名单把函数**抽到合成模块里 exec**
#: （见上方 `FUNCTIONS`）。于是两类东西带不过来：
#:
#: * `_normalize_debug_address` 这种「`app.py` 从别处 import 进来的名字」；
#: * 真实的请求体解析路径。
#:
#: 结果三种坏请求都走到「请选择有效的商品编号」。但**实质契约**是确切的：
#: 400 + `success: False` + 不建任务 + 无副作用。这里断言这些。
#:
#: （原版对三种都断言 `409 + TAOBAO_AUTO_PUBLISH_UNAVAILABLE`——那是**接口还没实现**
#: 时唯一的拒绝方式。现在接口实现了，一刀切的 409 早已不成立；而且当时夹具缺助手，
#: 这条测试其实**跑不到真正的逻辑**，NameError 被当成了拒绝路径。）
BAD_START_REQUESTS = ({"record_id": 7}, {"platform": "douyin"}, None)


@pytest.mark.parametrize("body", BAD_START_REQUESTS)
def test_publish_start_rejects_bad_requests_without_a_task(api_case, body):
    """坏请求必须被拒绝，**且一个任务都不建、一点副作用都没有**。"""

    response = api_case.client.post("/api/taobao/publish/start", json=body)
    assert response.status_code == 400, response.get_json()
    result = response.get_json()
    assert result["success"] is False
    assert result.get("msg"), "拒绝必须带原因，不能只给一个空壳"
    assert "task_id" not in result
    # ⚠️ **不断言「没查库」。**
    #
    # `{"record_id": 7}` 是**合法记录**，路由会先 `Record.get_by_id(7)` 确认它存在，
    # 再去找浏览器——**查了才是对的**。真正的不变式是「没建任务、没副作用」。
    # （另外两个输入在校验阶段就被拒，确实不该查库。）
    if body != {"record_id": 7}:
        assert api_case.record_class.requests == []
    assert api_case.resolved_names == []
    assert not api_case.runtime.exists()

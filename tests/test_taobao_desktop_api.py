# -*- coding: utf-8 -*-
"""淘宝桌面 HTTP 路由：真实离线模块、隔离数据库与运行目录。

2026-10-20 起淘宝接口来自真实的 ``src/sidecar/taobao_routes.py`` 与 ``taobao_service.py``（以前是按名字从 app.py 里抽函数 exec）：
账户门禁、店铺会话服务、淘宝发布服务都是真对象，只有商品表、运行目录、浏览器和发布流水线是假的 / 会报错的替身。
"""

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
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from flask import Flask
from PIL import Image


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
APP_PATH = PROJECT_ROOT / "tauri-app" / "python-sidecar" / "app.py"

from src.sidecar.shop_accounts import ShopAccountGuard  # noqa: E402
from src.sidecar.shop_service import ShopBrowserPort, ShopSessionService  # noqa: E402
from src.sidecar.taobao_routes import create_taobao_blueprint  # noqa: E402
from src.sidecar.taobao_service import TaobaoPublishService  # noqa: E402

#: 仍从 app.py 抽出来的函数：账户门禁问「现在有没有发布任务在跑」时调用它（任务字典分属上传 / 淘宝两个域，留在入口）。
FUNCTIONS = {"_publish_tasks_running"}
PRODUCT_ROUTES = ("prepare", "export")


def test_custom_sku_mode_is_preserved_by_the_real_request_translator(api_case):
    translate = api_case.service.product_request_payload
    assert translate({'sku_mode': 'custom'})['sku_mode'] == 'custom'
    assert translate({'sku_mode': 'standard'})['sku_mode'] == 'standard'
    assert 'sku_mode' not in translate({})


@pytest.mark.parametrize('mode', [None, '', 'guess', True, [], {}])
def test_invalid_sku_mode_is_rejected_without_browser_work(api_case, mode):
    with pytest.raises(ValueError, match='sku_mode'):
        api_case.service.product_request_payload({'sku_mode': mode})


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
        # 导出接口读 ``resolve_data_file``：包一层可替换的转发，个别用例要把输出目录指到不安全的位置
        resolver = {"fn": resolve_data_file}

        def resolve(name):
            return resolver["fn"](name)

        shop_session = SimpleNamespace(
            DEFAULT_PROFILE_NAME="upload-browser-profile",
            load_registry=lambda: {
                "active_profile": "taobao-test",
                "profiles": {"taobao-test": {"platform": "taobao", "label": "测试淘宝账户"}},
            },
            slugify_profile_name=lambda name: name,
            normalize_platform=lambda value: value,
        )
        namespace = {
            "__name__": "taobao_desktop_api_isolated",
            # app.py 里的 _publish_tasks_running 读 upload_service.tasks / .lock（2026-10-21 起）
            "upload_service": SimpleNamespace(tasks=upload_tasks, lock=threading.RLock()),
        }

        def normalize_debug_address(value):
            # 去掉协议前缀，取 host:port；够路由判断「有没有可用的浏览器」
            return str(value or "").strip().split("://", 1)[-1].split("/", 1)[0].strip()

        # 真实的账户门禁与店铺会话服务。本夹具没有浏览器：枚举复用浏览器永远返回「没有」，
        # 于是路由走到「没有找到淘宝账户的浏览器」——那正是测试要断言的拒绝路径。
        # 任何真去开浏览器 / 复用调试实例的动作都落到 ``forbidden``，会让用例当场失败。
        guard = ShopAccountGuard(
            shop_session=shop_session,
            has_running_publish_tasks=lambda: namespace["_publish_tasks_running"](),
        )
        service = ShopSessionService(
            accounts=guard,
            browser=ShopBrowserPort(
                page_state=lambda: SimpleNamespace(page=None),
                open_page=forbidden,
                normalize_address=normalize_debug_address,
                gui_page_debug_address=lambda: "",
                find_browser_process=lambda _address: {},
                find_reusable_browser=lambda **_kwargs: {},
                set_debug_browser_instance=forbidden,
                host="127.0.0.1", shop_port_start=9500, shop_port_end=9599,
            ),
            shop_session=shop_session,
        )
        taobao = TaobaoPublishService(
            record_model=FakeRecord, repo_root=str(PROJECT_ROOT), accounts=guard, shop_service=service,
            normalize_debug_address=normalize_debug_address, resolve_data_file=resolve,
            bootstrap_log=lambda message: None,
        )
        namespace["taobao_service"] = taobao       # app.py 里的 _publish_tasks_running 读它
        app.register_blueprint(create_taobao_blueprint(
            service=taobao, accounts=guard, record_model=FakeRecord, resolve_data_file=resolve,
            require_product_revision=forbidden,
        ))
        tree = ast.parse(APP_PATH.read_text(encoding="utf-8"))
        definitions = [
            node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name in FUNCTIONS
        ]
        assert {node.name for node in definitions} == FUNCTIONS
        exec(compile(ast.Module(body=definitions, type_ignores=[]), str(APP_PATH), "exec"), namespace)
        case = SimpleNamespace(
            client=app.test_client(),
            app=app,
            namespace=namespace,
            service=taobao,
            guard=guard,
            resolver=resolver,
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
        patch.setitem(api_case.resolver, "fn", lambda _name: unsafe_output)
        response = api_case.client.post(
            "/api/taobao/publish/export",
            json={"record_id": 7, "overrides": {"item_price": 9.9, "total_stock": 0}},
        )
    assert response.status_code == 400
    assert response.get_json()["success"] is False
    assert "不能位于原始商品资料目录内" in response.get_json()["msg"]
    assert not unsafe_output.exists()
    assert {str(path): path.read_bytes() for path in api_case.product.rglob("*") if path.is_file()} == before


#: 三种坏请求各自应当得到的拒绝：**实质契约是确切的**——``success: False`` + 有原因 + 不建任务 + 无副作用。
#:
#: 状态码按真实接口：请求本身不合法（不是 JSON 对象 / 平台不对）是 400；
#: 请求合法但这个账户当前没有可用的淘宝浏览器，走统一的 ``api_error``（HTTP 200 + ``success: False``）。
#:
#: ⚠️ 2026-10-20 之前这个夹具用假的 ``api_error`` 替身，把「没有浏览器」也变成了 400，和真实接口不一致；
#: 现在用的是真接口，测试如实断言真实状态码（新旧两版 app.py 对打时这条路径的响应逐字相同：200 + 同一句提示）。
BAD_START_REQUESTS = (
    ({"record_id": 7}, 200),            # 记录存在，但这个账户没有可用的淘宝浏览器
    ({"platform": "douyin"}, 400),      # 平台不对：校验阶段就拒绝
    (None, 400),                        # 没有请求体：缺商品编号
)


@pytest.mark.parametrize("body,status", BAD_START_REQUESTS)
def test_publish_start_rejects_bad_requests_without_a_task(api_case, body, status):
    """坏请求必须被拒绝，**且一个任务都不建、一点副作用都没有**。"""

    response = api_case.client.post("/api/taobao/publish/start", json=body)
    assert response.status_code == status, response.get_json()
    result = response.get_json()
    assert result["success"] is False
    assert result.get("msg"), "拒绝必须带原因，不能只给一个空壳"
    assert "task_id" not in result
    assert api_case.service.tasks == {}, "被拒绝的请求不得登记任务"
    # ⚠️ **不断言「没查库」。**
    #
    # `{"record_id": 7}` 是**合法记录**，路由会先 `Record.get_by_id(7)` 确认它存在，
    # 再去找浏览器——**查了才是对的**。真正的不变式是「没建任务、没副作用」。
    # （另外两个输入在校验阶段就被拒，确实不该查库。）
    if body != {"record_id": 7}:
        assert api_case.record_class.requests == []
    assert api_case.resolved_names == []

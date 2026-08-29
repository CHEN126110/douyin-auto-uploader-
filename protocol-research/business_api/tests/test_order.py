# -*- coding: utf-8 -*-
import pytest

from business_api.core import BrowserContext, HumanPacer
from business_api.domains import base
from business_api.server import create_app
from business_api.tests.fakes import FakeDriver

# 订单样本：订单号行（td=2）+ 明细行（td=8）交替，取自真实页面结构（已脱敏）
ORDER_ROWS = [
    ["", "订单编号 6926719584908574185"],
    ["", "木耳边蝴蝶结袜子", "¥7.90 x1", "-", "已发货 承诺发货", "¥2.90", "叶* 1*** 吉林省", "重新发货补发订单详情"],
    ["", "订单编号 6953091970082215836"],
    ["", "多巴胺新款袜子", "¥7.50 x2", "-", "待发货", "¥15.00", "张* 1*** 北京市", "发货订单详情"],
]


@pytest.fixture
def client():
    app = create_app()
    app.testing = True
    with app.test_client() as c:
        yield c
    base.set_context_factory(None)


def _bind(driver):
    pacer = HumanPacer(min_interval=0, jitter=0, max_actions_per_min=100000)
    base.set_context_factory(lambda: BrowserContext(driver, pacer=pacer))


def test_order_list_success(client):
    _bind(FakeDriver(rows=ORDER_ROWS, logged_in=True))
    r = client.post("/api/order/list", json={"limit": 20})
    assert r.status_code == 200
    data = r.get_json()["data"]
    assert data["count"] == 2
    assert data["items"][0]["order_id"] == "6926719584908574185"
    assert data["items"][0]["status"] == "已发货"
    assert data["items"][1]["status"] == "待发货"
    # 不得泄露买家隐私字段
    assert "receiver" not in data["items"][0]
    assert "叶" not in str(data["items"][0])


def test_order_list_status_filter(client):
    _bind(FakeDriver(rows=ORDER_ROWS, logged_in=True))
    r = client.post("/api/order/list", json={"status": "待发货"})
    data = r.get_json()["data"]
    assert data["count"] == 1
    assert data["items"][0]["order_id"] == "6953091970082215836"


def test_order_ship_dry_run(client):
    _bind(FakeDriver(rows=ORDER_ROWS, logged_in=True, xpath_exists=True))
    r = client.post("/api/order/ship", json={"order_id": "6953091970082215836"})
    assert r.status_code == 200
    data = r.get_json()["data"]
    assert data["dry_run"] is True
    assert data["located"] is True


def test_order_ship_confirm_not_implemented(client):
    _bind(FakeDriver(rows=ORDER_ROWS, logged_in=True, xpath_exists=True))
    r = client.post("/api/order/ship", json={"order_id": "6953091970082215836", "dry_run": False, "confirm": True})
    assert r.status_code == 501
    assert r.get_json()["code"] == "NOT_IMPLEMENTED"


def test_order_ship_missing_param(client):
    _bind(FakeDriver(rows=ORDER_ROWS))
    r = client.post("/api/order/ship", json={})
    assert r.status_code == 400
    assert r.get_json()["code"] == "INVALID_PARAM"

# -*- coding: utf-8 -*-
import pytest

from business_api.core import BrowserContext, HumanPacer
from business_api.domains import base
from business_api.server import create_app
from business_api.tests.fakes import FakeDriver

# 售后样本：订单号行（td=2）+ 明细行（td=8），取自真实页面结构（已脱敏）
AFTERSALE_ROWS = [
    ["", "订单编号 6953091970082215836"],
    ["", "韩系波点中筒袜", "应付 ¥2.45", "售后退款 ¥2.45 申请1件", "同意退款，退款成功", "未介入", "1/1已签收", "查看详情"],
    ["", "订单编号 6926719584908574185"],
    ["", "木耳边袜子", "应付 ¥2.90", "售后退款 ¥2.90 申请1件", "待商家处理", "未介入", "待发货", "同意退款拒绝"],
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


def test_aftersale_list_success(client):
    _bind(FakeDriver(rows=AFTERSALE_ROWS, logged_in=True))
    r = client.post("/api/aftersale/list", json={"limit": 20})
    assert r.status_code == 200
    data = r.get_json()["data"]
    assert data["count"] == 2
    assert data["items"][0]["order_id"] == "6953091970082215836"
    assert data["items"][1]["aftersale_status"] == "待商家处理"
    # 不泄露买家隐私
    assert "receiver" not in data["items"][0]


def test_aftersale_list_status_filter(client):
    _bind(FakeDriver(rows=AFTERSALE_ROWS, logged_in=True))
    r = client.post("/api/aftersale/list", json={"status": "待商家处理"})
    data = r.get_json()["data"]
    assert data["count"] == 1
    assert data["items"][0]["order_id"] == "6926719584908574185"


def test_aftersale_agree_refund_dry_run(client):
    _bind(FakeDriver(rows=AFTERSALE_ROWS, logged_in=True, xpath_exists=True))
    r = client.post("/api/aftersale/agree-refund", json={"order_id": "6926719584908574185"})
    assert r.status_code == 200
    data = r.get_json()["data"]
    assert data["dry_run"] is True
    assert data["located"] is True
    assert data["action"] == "同意退款"


def test_aftersale_refund_confirm_not_implemented(client):
    _bind(FakeDriver(rows=AFTERSALE_ROWS, logged_in=True, xpath_exists=True))
    r = client.post("/api/aftersale/agree-refund",
                    json={"order_id": "6926719584908574185", "dry_run": False, "confirm": True})
    assert r.status_code == 501
    assert r.get_json()["code"] == "NOT_IMPLEMENTED"


def test_aftersale_missing_param(client):
    _bind(FakeDriver(rows=AFTERSALE_ROWS))
    r = client.post("/api/aftersale/agree-refund", json={})
    assert r.status_code == 400
    assert r.get_json()["code"] == "INVALID_PARAM"

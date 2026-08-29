# -*- coding: utf-8 -*-
import pytest

from business_api.core import BrowserContext, HumanPacer
from business_api.domains import base, product
from business_api.server import create_app
from business_api.tests.fakes import FakeDriver

SEL = product.SEL

# 取自真实页面 dump 的样本行（前两行为表头空行）
SAMPLE_ROWS = [
    [],
    [],
    ["", "韩系波点中筒袜 ID:3819238447663677663", "￥6.80", "593", "2 100%好评", "优秀90", "2026/05/27 08:52:36 售卖中", "编辑下架"],
    ["", "木耳边蝴蝶结袜子 ID:3820045708401181005", "￥7.90 ~ ￥28.60", "119", "0", "优秀91", "2026/05/26 15:35:12 售卖中", "编辑下架"],
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


def test_product_list_success(client):
    _bind(FakeDriver(rows=SAMPLE_ROWS, visible=True, logged_in=True))
    r = client.post("/api/product/list", json={"limit": 20})
    assert r.status_code == 200
    body = r.get_json()
    assert body["ok"] is True
    assert body["data"]["count"] == 2
    first = body["data"]["items"][0]
    assert first["product_id"] == "3819238447663677663"
    assert "韩系波点" in first["title"]
    assert first["price"] == "￥6.80"
    assert first["status"] == "售卖中"


def test_product_list_keyword_filter(client):
    _bind(FakeDriver(rows=SAMPLE_ROWS, visible=True, logged_in=True))
    r = client.post("/api/product/list", json={"keyword": "木耳边"})
    body = r.get_json()
    assert body["data"]["count"] == 1
    assert "木耳边" in body["data"]["items"][0]["title"]


def test_product_list_not_logged_in(client):
    _bind(FakeDriver(rows=SAMPLE_ROWS, logged_in=False))
    r = client.post("/api/product/list", json={})
    assert r.status_code == 401
    assert r.get_json()["code"] == "LOGIN_REQUIRED"


def test_product_list_empty(client):
    _bind(FakeDriver(rows=SAMPLE_ROWS, visible=False, logged_in=True))
    r = client.post("/api/product/list", json={})
    assert r.status_code == 502
    assert r.get_json()["code"] == "ELEMENT_NOT_FOUND"


def test_off_shelf_missing_param(client):
    _bind(FakeDriver(rows=SAMPLE_ROWS))
    r = client.post("/api/product/off-shelf", json={})
    assert r.status_code == 400
    assert r.get_json()["code"] == "INVALID_PARAM"


def test_off_shelf_dry_run_default(client):
    _bind(FakeDriver(rows=SAMPLE_ROWS, logged_in=True, xpath_exists=True))
    r = client.post("/api/product/off-shelf", json={"product_id": "3819238447663677663"})
    assert r.status_code == 200
    data = r.get_json()["data"]
    assert data["dry_run"] is True
    assert data["located"] is True
    assert data["action"] == "下架"


def test_off_shelf_product_not_found(client):
    _bind(FakeDriver(rows=SAMPLE_ROWS, logged_in=True, xpath_exists=False))
    r = client.post("/api/product/off-shelf", json={"product_id": "999"})
    assert r.status_code == 502
    assert r.get_json()["code"] == "ELEMENT_NOT_FOUND"


def test_captcha_blocks_request(client):
    _bind(FakeDriver(rows=SAMPLE_ROWS, captcha=True, logged_in=True))
    r = client.post("/api/product/list", json={})
    assert r.status_code == 423
    assert r.get_json()["code"] == "CAPTCHA_REQUIRED"

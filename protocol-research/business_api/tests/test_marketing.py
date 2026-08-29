# -*- coding: utf-8 -*-
import pytest

from business_api.core import BrowserContext, HumanPacer
from business_api.domains import base
from business_api.server import create_app
from business_api.tests.fakes import FakeDriver

# 优惠查询表格样本：每行 6 个 td（取自真实页面结构）
MARKETING_ROWS = [
    ["优惠券", "全店优惠券 20260601 10:12 ID:7646244282512359706 全店优惠券",
     "2026/06/01 00:00:00 - 2026/07/01 23:59:59",
     "活动生效7天内: 活动商品GMV ↑103.45% 查看数据 建议续期活动", "进行中", "编辑复制作废数据推广"],
    ["新人礼金", "新人礼金 20260526 15:34 ID:7644100742567100712",
     "2026/05/26 15:34:50 - 2026/08/24 15:34:50",
     "活动生效7天内: 活动商品GMV ↑显著提升 查看数据 复制续期", "已失效", "查看复制数据"],
    ["单品直降", "限时抢购 20260523 18:48 ID:7643037585493197119 限时抢购",
     "2026/05/23 18:48:22 - 2026/05/27 18:48:22",
     "活动生效7天内: 活动商品订单数 ↑33.33% 查看数据 复制续期", "已失效", "查看复制数据删除"],
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


def test_marketing_activities_success(client):
    _bind(FakeDriver(rows=MARKETING_ROWS, logged_in=True))
    r = client.post("/api/marketing/activities", json={"limit": 20})
    assert r.status_code == 200
    data = r.get_json()["data"]
    assert data["count"] == 3
    first = data["items"][0]
    assert first["activity_type"] == "优惠券"
    assert first["name"] == "全店优惠券"
    assert first["activity_id"] == "7646244282512359706"
    assert first["status"] == "进行中"
    assert first["period"] == "2026/06/01 00:00:00 - 2026/07/01 23:59:59"
    # 效果去掉操作词
    assert "查看数据" not in first["effect"]
    assert "GMV" in first["effect"]


def test_marketing_status_filter(client):
    _bind(FakeDriver(rows=MARKETING_ROWS, logged_in=True))
    r = client.post("/api/marketing/activities", json={"status": "进行中"})
    data = r.get_json()["data"]
    assert data["count"] == 1
    assert data["items"][0]["name"] == "全店优惠券"


def test_marketing_type_filter(client):
    _bind(FakeDriver(rows=MARKETING_ROWS, logged_in=True))
    r = client.post("/api/marketing/activities", json={"activity_type": "新人礼金"})
    data = r.get_json()["data"]
    assert data["count"] == 1
    assert data["items"][0]["activity_id"] == "7644100742567100712"


def test_marketing_keyword_by_id(client):
    _bind(FakeDriver(rows=MARKETING_ROWS, logged_in=True))
    r = client.post("/api/marketing/activities", json={"keyword": "7643037585493197119"})
    data = r.get_json()["data"]
    assert data["count"] == 1
    assert data["items"][0]["name"] == "限时抢购"


def test_marketing_login_required(client):
    _bind(FakeDriver(rows=MARKETING_ROWS, logged_in=False))
    r = client.post("/api/marketing/activities", json={})
    assert r.status_code == 401
    assert r.get_json()["code"] == "LOGIN_REQUIRED"


def test_marketing_coupon_create_skeleton(client):
    r = client.post("/api/marketing/coupon/create",
                    json={"name": "x", "discount": 5, "total": 100})
    assert r.status_code == 501
    body = r.get_json()
    assert body["code"] == "NOT_IMPLEMENTED"
    assert body["data"]["domain"] == "marketing"

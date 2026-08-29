# -*- coding: utf-8 -*-
import pytest

from business_api.core import BrowserContext, HumanPacer
from business_api.domains import base
from business_api.server import create_app
from business_api.tests.fakes import FakeDriver

CARD_SEL = "css:[class*=data-card-wrapper]"

# 取自真实页面结构：同一指标相邻渲染两次（去重保留首个），并混入两类应被过滤的非指标卡
COMPASS_CARDS = [
    "成交金额 ¥2.90 昨日 ¥0.00 同行基准 ¥86.78",
    "成交金额 ¥2.90 昨日 ¥0.00 同行基准 ¥86.78",
    "用户支付金额 ¥2.90 昨日 ¥0.00 同行基准 ¥83.6",
    "用户支付金额 ¥2.90 昨日 ¥0.00 同行基准 ¥83.6",
    "成交订单数 1 昨日 0 同行基准 3",
    "成交订单数 1 昨日 0 同行基准 3",
    "退款金额（退款时间） ¥0.00 昨日 ¥0.00 同行基准 ¥1.99",
    "退款率（支付时间） 0.00% 昨日 0.00% 同行基准 2.30%",
    # 同时含"同行顶尖"与"同行基准"：昨日值不被污染，对比优先取同行基准
    "商品点击-成交转化率（人数） 25% 昨日 0% 同行顶尖 100% 同行基准 9.04%",
    # 仅含"同行顶尖"：对比应退用顶尖值，并标注类型
    "曝光点击率 3% 昨日 2% 同行顶尖 8%",
    # 当日暂无数据（值为 "-"）：应保留为指标并标 "-"，而非丢弃
    "客单价 - 昨日 -",
    "客单价 - 昨日 -",
    "商品卡 - 昨日 -",  # 成交渠道分布卡：统一排除
    "商品卡",  # 渠道标签，无末尾数值，应被过滤
    "商品卡 ¥2.90 100%",  # 渠道占比异形卡，标签含货币，应被过滤
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


def test_compass_overview_success(client):
    _bind(FakeDriver(texts_map={CARD_SEL: COMPASS_CARDS}, logged_in=True))
    r = client.post("/api/compass/overview", json={})
    assert r.status_code == 200
    data = r.get_json()["data"]
    # 去重后 8 个唯一指标（含暂无数据的客单价）；渠道卡"商品卡"被过滤
    assert data["count"] == 8
    first = data["metrics"][0]
    assert first["label"] == "成交金额"
    assert first["value"] == "¥2.90"
    assert first["yesterday"] == "¥0.00"
    assert first["benchmark"] == "¥86.78"
    assert first["benchmark_type"] == "同行基准"
    # 百分号指标解析
    rate = next(m for m in data["metrics"] if m["label"] == "退款率（支付时间）")
    assert rate["value"] == "0.00%"
    assert rate["benchmark"] == "2.30%"
    # 同时含同行顶尖与同行基准：昨日值干净，对比优先取同行基准
    conv = next(m for m in data["metrics"] if m["label"] == "商品点击-成交转化率（人数）")
    assert conv["value"] == "25%"
    assert conv["yesterday"] == "0%"
    assert conv["benchmark"] == "9.04%"
    assert conv["benchmark_type"] == "同行基准"
    # 仅含同行顶尖：退用顶尖值并标注类型
    peak = next(m for m in data["metrics"] if m["label"] == "曝光点击率")
    assert peak["benchmark"] == "8%"
    assert peak["benchmark_type"] == "同行顶尖"
    # 当日暂无数据的指标仍保留，值为 "-"
    assert data["by_label"]["客单价"] == "-"
    # by_label 便捷映射
    assert data["by_label"]["成交订单数"] == "1"
    # 渠道分布卡 / 含货币标签的异形卡被过滤
    assert "商品卡" not in data["by_label"]
    assert not any("¥" in label for label in data["by_label"])


def test_compass_overview_keyword_filter(client):
    _bind(FakeDriver(texts_map={CARD_SEL: COMPASS_CARDS}, logged_in=True))
    r = client.post("/api/compass/overview", json={"keyword": "退款"})
    assert r.status_code == 200
    data = r.get_json()["data"]
    assert data["count"] == 2
    labels = {m["label"] for m in data["metrics"]}
    assert labels == {"退款金额（退款时间）", "退款率（支付时间）"}


def test_compass_overview_login_required(client):
    _bind(FakeDriver(texts_map={CARD_SEL: COMPASS_CARDS}, logged_in=False))
    r = client.post("/api/compass/overview", json={})
    assert r.status_code == 401
    assert r.get_json()["code"] == "LOGIN_REQUIRED"


def test_compass_overview_no_cards(client):
    # 卡片选择器命中但无可解析卡片：count=0，不报错
    _bind(FakeDriver(texts_map={CARD_SEL: ["商品卡", "直播"]}, logged_in=True))
    r = client.post("/api/compass/overview", json={})
    assert r.status_code == 200
    assert r.get_json()["data"]["count"] == 0


def test_compass_subpage_skeleton(client):
    r = client.post("/api/compass/product-analysis", json={})
    assert r.status_code == 501
    body = r.get_json()
    assert body["code"] == "NOT_IMPLEMENTED"
    assert body["data"]["domain"] == "compass"

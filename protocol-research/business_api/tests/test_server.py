# -*- coding: utf-8 -*-
import pytest

from business_api.domains.skeletons import SKELETON_DOMAINS
from business_api.server import create_app

# 动态取第一个骨架域，避免把具体域名写死（域升级为真实后测试不再破裂）
_SK_DOMAIN, _SK_CFG = next(iter(SKELETON_DOMAINS.items()))
_SK_EP = _SK_CFG["endpoints"][0]
_SK_PATH = _SK_CFG["prefix"] + _SK_EP.path


@pytest.fixture
def client():
    app = create_app()
    app.testing = True
    with app.test_client() as c:
        yield c


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.get_json()
    assert body["ok"] is True
    assert "product" in body["domains"]
    assert "order" in body["domains"]


def test_catalog(client):
    r = client.get("/catalog")
    assert r.status_code == 200
    body = r.get_json()
    assert "product" in body["implemented_domains"]
    assert "order" in body["implemented_domains"]
    domains = [d["domain"] for d in body["skeleton"]]
    for d in SKELETON_DOMAINS:
        assert d in domains
    # 已升级的真实域不应再出现在骨架清单
    assert "product" not in domains
    assert "order" not in domains


def test_skeleton_not_implemented(client):
    if _SK_EP.method == "GET":
        r = client.get(_SK_PATH)
    else:
        r = client.post(_SK_PATH, json={})
    assert r.status_code == 501
    body = r.get_json()
    assert body["code"] == "NOT_IMPLEMENTED"
    assert body["data"]["domain"] == _SK_DOMAIN


def test_skeleton_get_with_path_arg(client):
    r = client.get("/api/order/detail/12345")
    assert r.status_code == 501
    assert r.get_json()["data"]["path_args"]["order_id"] == "12345"


def test_unknown_route_404(client):
    r = client.post("/api/nonexistent", json={})
    assert r.status_code == 404
    assert r.get_json()["code"] == "INVALID_PARAM"

# -*- coding: utf-8 -*-
import pytest

from business_api.core import BrowserContext, HumanPacer
from business_api.domains import base
from business_api.server import create_app
from business_api.domains.skeletons import SKELETON_DOMAINS
from business_api.tests.fakes import FakeDriver
from business_api.tests.test_product import SAMPLE_ROWS

# 动态取第一个骨架域的工具，避免写死域名
_SK_DOMAIN, _SK_CFG = next(iter(SKELETON_DOMAINS.items()))
_SK_TOOL = f"{_SK_DOMAIN}.{_SK_CFG['endpoints'][0].name}"


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


def test_mcp_tools_list(client):
    r = client.get("/mcp/tools")
    assert r.status_code == 200
    tools = r.get_json()["tools"]
    names = [t["name"] for t in tools]
    assert "product.list" in names
    assert "order.ship" in names
    # 写操作要标注 destructive、非只读
    off = next(t for t in tools if t["name"] == "product.off_shelf")
    assert off["annotations"]["destructiveHint"] is True
    assert off["annotations"]["readOnlyHint"] is False
    assert off["_meta"]["requiresConfirm"] is True
    # 只读操作标注
    lst = next(t for t in tools if t["name"] == "product.list")
    assert lst["annotations"]["readOnlyHint"] is True


def test_mcp_call_real_tool(client):
    _bind(FakeDriver(rows=SAMPLE_ROWS, logged_in=True))
    r = client.post("/mcp/call", json={"name": "product.list", "arguments": {"limit": 5}})
    assert r.status_code == 200
    body = r.get_json()
    assert body["isError"] is False
    assert body["structuredContent"]["data"]["count"] == 2


def test_mcp_call_skeleton_tool(client):
    r = client.post("/mcp/call", json={"name": _SK_TOOL, "arguments": {}})
    body = r.get_json()
    assert body["isError"] is True
    assert body["structuredContent"]["code"] == "NOT_IMPLEMENTED"


def test_mcp_call_unknown_tool(client):
    r = client.post("/mcp/call", json={"name": "nope.nope", "arguments": {}})
    assert r.status_code == 400
    assert r.get_json()["code"] == "INVALID_PARAM"

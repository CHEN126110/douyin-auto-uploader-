# -*- coding: utf-8 -*-
"""小红书千帆 sidecar 接口回归（离线：注入假执行器，不连浏览器）。

重点守两件事：
1. **没有提交能力**——`/api/xhs/*` 里不存在任何提交/保存草稿/上架路由；
2. **上传默认不授权**——`allow_upload` 缺省为 False，透传给 `FillPlan` 时不得被打开。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from flask import Flask

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from src.sidecar.xhs_routes import create_xhs_blueprint  # noqa: E402


@pytest.fixture()
def captured() -> list:
    return []


@pytest.fixture()
def client(captured):
    def fake_runner(payload: dict) -> dict:
        captured.append(payload)
        return {"ok": True, "echo": payload}

    def fake_probe() -> dict:
        return {"port": 9336, "url": "https://ark.xiaohongshu.com/app-item/good/create",
                "visibility": "visible", "title_counter": "0/60"}

    app = Flask(__name__)
    app.register_blueprint(create_xhs_blueprint(runner=fake_runner, status_probe=fake_probe))
    return app.test_client()


def test_status_is_read_only_and_wrapped_in_api_ok(client):
    response = client.get("/api/xhs/status")
    assert response.status_code == 200
    body = response.get_json()
    assert body["success"] is True
    assert body["data"]["visibility"] == "visible"


def test_status_passes_through_gaps():
    """体检要能把"还差什么"带出来（前端面板据此显示必填缺口）。"""
    def probe_with_gaps() -> dict:
        return {"port": 9336, "url": "https://ark.xiaohongshu.com/app-item/good/create",
                "visibility": "visible", "title_counter": "56/60",
                "category_lines": [], "errors": [], "drawer": {"drawers": 0},
                "gaps": {"required_count": 13, "unfilled": ["物流模板", "运费模板"],
                         "filled": ["商品标题"], "judges": {"required": ["1 项必填"]}}}

    app = Flask(__name__)
    app.register_blueprint(create_xhs_blueprint(runner=lambda payload: {},
                                                status_probe=probe_with_gaps))
    body = app.test_client().get("/api/xhs/status").get_json()
    assert body["success"] is True
    assert body["data"]["gaps"]["unfilled"] == ["物流模板", "运费模板"]
    assert body["data"]["gaps"]["required_count"] == 13


def test_status_passes_through_gap_read_error_without_failing():
    """判据读不到时体检整体仍应成功，只在 gaps 里带 error（一项读不到不该让整体失败）。"""
    def probe_with_gap_error() -> dict:
        return {"port": 9336, "url": "https://ark.xiaohongshu.com/app-item/good/create",
                "visibility": "hidden", "gaps": {"error": "页面内执行报错"}}

    app = Flask(__name__)
    app.register_blueprint(create_xhs_blueprint(runner=lambda payload: {},
                                                status_probe=probe_with_gap_error))
    response = app.test_client().get("/api/xhs/status")
    assert response.status_code == 200
    body = response.get_json()
    assert body["success"] is True
    assert body["data"]["gaps"]["error"] == "页面内执行报错"


def test_fill_only_requires_title(client):
    response = client.post("/api/xhs/fill-only", json={"images": ["a.jpg"]})
    assert response.status_code == 400
    assert response.get_json()["success"] is False


def test_fill_only_defaults_allow_upload_to_false(client, captured):
    response = client.post("/api/xhs/fill-only", json={"title": "桑蚕丝羊毛小腿袜女秋冬款日系撞色罗口美腿袜"})
    assert response.status_code == 200
    assert captured[-1]["allow_upload"] is False


def test_fill_only_passes_explicit_authorization_through(client, captured):
    response = client.post("/api/xhs/fill-only",
                           json={"title": "桑蚕丝羊毛小腿袜女秋冬款日系撞色罗口美腿袜",
                                 "images": ["a.jpg"], "allow_upload": True})
    assert response.status_code == 200
    assert captured[-1]["allow_upload"] is True
    assert captured[-1]["images"] == ["a.jpg"]


def test_allow_submit_is_rejected(client):
    """本接口没有提交能力：收到 allow_submit 要明确报错，而不是默默忽略。"""
    response = client.post("/api/xhs/fill-only",
                           json={"title": "桑蚕丝羊毛小腿袜女秋冬款日系撞色罗口美腿袜",
                                 "allow_submit": True})
    assert response.status_code == 400
    assert "不支持提交" in response.get_json()["msg"]


def test_no_submit_or_draft_routes_exist():
    """红线守门：/api/xhs/* 下不允许出现提交/保存类路由。"""
    app = Flask(__name__)
    app.register_blueprint(create_xhs_blueprint(runner=lambda payload: {},
                                                status_probe=lambda: {}))
    rules = sorted(str(rule) for rule in app.url_map.iter_rules())
    xhs_rules = [rule for rule in rules if "/api/xhs/" in rule]
    assert xhs_rules == ["/api/xhs/fill-only", "/api/xhs/status"]
    for rule in xhs_rules:
        for forbidden in ("submit", "save", "publish", "draft", "on-sale", "onsale"):
            assert forbidden not in rule


def test_probe_failure_returns_503():
    def boom() -> dict:
        raise RuntimeError("CDP 9336 不可达")

    app = Flask(__name__)
    app.register_blueprint(create_xhs_blueprint(runner=lambda payload: {}, status_probe=boom))
    response = app.test_client().get("/api/xhs/status")
    assert response.status_code == 503
    assert "不可达" in response.get_json()["msg"]

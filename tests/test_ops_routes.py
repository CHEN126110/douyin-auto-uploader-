# -*- coding: utf-8 -*-
"""运营闭环接口（src/sidecar/ops）回归：直接注册 Blueprint，注入假浏览器与隔离数据库。

重点守三件事：
1. 37 个 /api/ops/* 路由的 URL 与方法不变（前端和 MCP 按它们调用）；
2. 上传前安全闸未通过、或找不到浏览器时，绝不触发任何上传；
3. 导入本包不会连带加载浏览器自动化库或 app.py。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import types
from pathlib import Path

import pytest
from flask import Flask

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from sidecar_test_support import make_record_model  # noqa: E402
from src.sidecar.ops import OpsBrowserPort, create_ops_blueprint  # noqa: E402

PRODUCT_ID = "3811995393416364123"
TITLE = "小雏菊碎花袜子女春夏新款镂空网眼中筒袜无骨甜美木耳边堆堆袜女"
READY_URL = f"https://fxg.jinritemai.com/ffa/g/create?product_id={PRODUCT_ID}&entrance=edit"
READY_SNAPSHOT = {
    "url": READY_URL,
    "title": "抖店",
    "brand_text": "*品牌 无品牌",
    "title_use_brand_name_checked": False,
    "title_values": [TITLE],
}

EXPECTED_ROUTES = {
    ("GET", "/api/ops/ai-policy"),
    ("GET", "/api/ops/health"),
    ("POST", "/api/ops/publish-preflight-safety"),
    ("POST", "/api/ops/upload-main-video-preflight"),
    ("POST", "/api/ops/save-edit-human-gate"),
    ("POST", "/api/ops/evaluate-product"),
    ("POST", "/api/ops/stock-plan"),
    ("POST", "/api/ops/product-candidates"),
    ("POST", "/api/ops/apply-candidate-pricing"),
    ("POST", "/api/ops/daily-plan"),
    ("POST", "/api/ops/search-conversion-work-package"),
    ("POST", "/api/ops/daily-review"),
    ("POST", "/api/ops/detail-conversion-audit"),
    ("POST", "/api/ops/conversion-asset-pack"),
    ("POST", "/api/ops/conversion-experiment-plan"),
    ("POST", "/api/ops/profit-ramp-plan"),
    ("POST", "/api/ops/profit-ladder-to-500"),
    ("POST", "/api/ops/sync-shop-metrics"),
    ("POST", "/api/ops/sync-strategy-signals"),
    ("GET", "/api/ops/daily-snapshots"),
    ("GET", "/api/ops/strategy-snapshots"),
    ("GET", "/api/ops/product-issue-actions"),
    ("GET", "/api/ops/no-brand-title-audit"),
    ("POST", "/api/ops/no-brand-remediation-plan"),
    ("POST", "/api/ops/reconcile-strategy-actions"),
    ("POST", "/api/ops/product-issue-actions/<int:action_id>"),
    ("POST", "/api/ops/sync-product-record-mappings"),
    ("GET", "/api/ops/product-record-mappings"),
    ("POST", "/api/ops/material-gap-plan"),
    ("POST", "/api/ops/sourcing-profit-gate"),
    ("POST", "/api/ops/supplier-quote-plan"),
    ("POST", "/api/ops/supplier-quote-intake"),
    ("POST", "/api/ops/execution-queue"),
    ("POST", "/api/ops/portfolio-path-to-500"),
    ("POST", "/api/ops/first-order-decision-matrix"),
    ("POST", "/api/ops/net-profit-verification-matrix"),
    ("POST", "/api/ops/post-save-conversion-monitor"),
}


class FakeBrowser:
    """记录所有上传调用的假浏览器；mode 决定当前标签页是否可用。"""

    def __init__(self):
        self.mode = "ready"  # ready=有标签页 / raises=取标签页抛错 / none=没有可用标签页
        self.uploads = []
        self.uploaded = False
        self.page_state = types.SimpleNamespace(page=None)

    def get_current_tab(self, create_if_missing=False):
        if self.mode == "raises":
            raise RuntimeError("no browser session")
        return (self if self.mode == "ready" else None), {}

    def snapshot_context(self, tab, limit=0, include_html=False):
        return {"url": READY_URL, "title": "抖店"}

    def attach_reusable_tab(self, progress):
        return self if self.mode == "ready" else None

    def find_reusable_browser(self, verify=False, preferred_profile=None):
        return {"status": "ready", "verify": verify}

    def discover_browsers(self, verify=False):
        return [{"debug_address": "127.0.0.1:9333"}]

    def upload_file(self, tab, paths, label, target_field_id=None, wait_for_finish=True):
        self.uploads.append((list(paths), label, target_field_id, wait_for_finish))
        self.uploaded = True

    def is_upload_busy(self, tab):
        return False

    # 当作 DrissionPage 的 tab 使用：只需要 run_js / ele
    def run_js(self, script):
        if "media_count" in script:
            return {"exists": True, "media_count": 1 if self.uploaded else 0, "upload_busy": False}
        return dict(READY_SNAPSHOT, body_text="品牌 无品牌", brand_texts=["*品牌 无品牌"])

    def ele(self, locator, timeout=0):
        return types.SimpleNamespace(scroll=types.SimpleNamespace(to_see=lambda: None, to_center=lambda: None))

    def port(self):
        return OpsBrowserPort(
            get_current_tab=self.get_current_tab, snapshot_context=self.snapshot_context,
            attach_reusable_tab=self.attach_reusable_tab, find_reusable_browser=self.find_reusable_browser,
            discover_browsers=self.discover_browsers, upload_file=self.upload_file,
            is_upload_busy=self.is_upload_busy, page_state=self.page_state,
        )


@pytest.fixture()
def env(tmp_path, monkeypatch):
    # 运营账本路径随 DOUYIN_DATA_DIR 走；账本实例按路径缓存，所以不会串到用户数据。
    monkeypatch.setenv("DOUYIN_DATA_DIR", str(tmp_path / "data"))
    Record, database = make_record_model(tmp_path / "records.db")
    browser = FakeBrowser()
    app = Flask(__name__)
    app.register_blueprint(create_ops_blueprint(
        record_model=Record, browser=browser.port(),
        is_sidecar_mode=lambda: True, get_sidecar_port=lambda: 5001, repo_root=str(tmp_path),
    ))
    video = tmp_path / "candidate-main-video.mp4"
    video.write_bytes(b"fake-video")
    yield types.SimpleNamespace(app=app, client=app.test_client(), Record=Record, browser=browser,
                                video=str(video))
    database.close()


def _routes(app):
    return {
        (method, rule.rule)
        for rule in app.url_map.iter_rules()
        for method in rule.methods
        if method not in ("HEAD", "OPTIONS") and rule.rule.startswith("/api/ops/")
    }


def test_route_table_matches_the_contract(env):
    assert _routes(env.app) == EXPECTED_ROUTES


def test_importing_the_package_does_not_load_browser_stack(tmp_path):
    code = (
        "import sys; sys.path.insert(0, %r); import src.sidecar.ops; "
        "bad = [m for m in ('DrissionPage', 'src.utils', 'PySide6', 'app') if m in sys.modules]; "
        "print('LOADED=' + ','.join(bad))" % str(REPO)
    )
    # 数据目录指向临时目录：src.config 导入时会读设置，不能让测试碰到用户的真实数据。
    env = dict(os.environ, DOUYIN_DATA_DIR=str(tmp_path / "data"), PYTHONUTF8="1")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         encoding="utf-8", env=env, check=True)
    assert out.stdout.strip().splitlines()[-1] == "LOADED="


# ---------------- 发布前安全闸：未通过就绝不上传 ----------------

def _upload_payload(env, **overrides):
    payload = {
        "page_snapshot": READY_SNAPSHOT, "expected_product_id": PRODUCT_ID,
        "expected_title": TITLE, "candidate_video_path": env.video,
    }
    payload.update(overrides)
    return payload


def test_upload_is_not_attempted_when_preflight_blocks(env):
    blocked = dict(READY_SNAPSHOT, brand_text="", title_use_brand_name_checked=True)
    response = env.client.post("/api/ops/upload-main-video-preflight",
                               json=_upload_payload(env, page_snapshot=blocked))
    body = response.get_json()
    assert body["success"] is False
    assert "安全闸未通过" in body["msg"]
    assert env.browser.uploads == []


def test_upload_is_not_attempted_without_a_reusable_browser(env):
    env.browser.mode = "none"
    body = env.client.post("/api/ops/upload-main-video-preflight", json=_upload_payload(env)).get_json()
    assert body["success"] is False
    assert "未找到可复用的已登录抖店浏览器" in body["msg"]
    assert env.browser.uploads == []


def test_upload_triggers_exactly_once_and_stops_before_save(env):
    body = env.client.post("/api/ops/upload-main-video-preflight", json=_upload_payload(env)).get_json()
    assert body["success"] is True
    assert env.browser.uploads == [([env.video], "主图视频", "主图视频", False)]
    result = body["data"]["upload_result"]
    assert result["save_publish_performed"] is False
    assert result["no_save"] and result["no_publish"] and result["no_ad_or_payment"]


def test_preflight_safety_never_marks_save_or_publish_as_safe(env):
    body = env.client.post("/api/ops/publish-preflight-safety", json=_upload_payload(env)).get_json()
    assert body["success"] is True
    assert body["data"]["preflight"]["ready_for_upload_preflight"] is True
    assert body["data"]["preflight"]["safe_to_save_or_publish"] is False
    assert env.browser.uploads == []


def test_health_reads_browser_state_at_call_time(env):
    env.browser.mode = "raises"
    env.browser.page_state.page = object()
    body = env.client.get("/api/ops/health").get_json()
    assert body["success"] is True
    assert body["data"]["browser"]["has_browser"] is True
    assert body["data"]["backend"] == {"status": "ok", "mode": "sidecar", "port": 5001}


# ---------------- 本地数据类接口 ----------------

def _create_record(env, skus):
    return env.Record.create(name="测试袜子", title="小雏菊碎花袜子女", clazz="袜子",
                             content=json.dumps(skus, ensure_ascii=False)).id


def test_evaluate_product_saves_snapshot_for_existing_record(env):
    record_id = _create_record(env, [{"name": "白 / 均码", "price": 8.9}])
    body = env.client.post("/api/ops/evaluate-product",
                           json={"record_id": record_id, "goods_cost": 2.0}).get_json()
    assert body["success"] is True
    assert body["data"]["record"]["record_id"] == record_id
    assert body["data"]["saved_snapshot"]
    assert body["data"]["ai_policy"]["external_ai_disabled"] is True


def test_apply_candidate_pricing_dry_run_does_not_touch_the_record(env):
    skus = [{"name": "白 / 均码", "price": 2.0}, {"name": "粉 / 均码", "price": 2.5, "ops_goods_cost": 1.8}]
    record_id = _create_record(env, skus)
    body = env.client.post("/api/ops/apply-candidate-pricing", json={"record_id": record_id}).get_json()
    assert body["success"] is True and body["data"]["saved"] is False
    assert json.loads(env.Record.get_by_id(record_id).content) == skus


def test_apply_candidate_pricing_saves_prices_and_keeps_goods_cost(env):
    record_id = _create_record(env, [{"name": "白 / 均码", "price": 2.0},
                                     {"name": "粉 / 均码", "price": 2.5, "ops_goods_cost": 1.8}])
    body = env.client.post("/api/ops/apply-candidate-pricing",
                           json={"record_id": record_id, "dry_run": False, "sale_price": 8.9}).get_json()
    assert body["success"] is True and body["data"]["saved"] is True
    saved = json.loads(env.Record.get_by_id(record_id).content)
    assert [sku["price"] for sku in saved] == [8.9, 8.9]
    assert [sku["ops_goods_cost"] for sku in saved] == [2.0, 1.8]


@pytest.mark.parametrize("payload,message", [
    ({}, "record_id 不能为空"),
    ({"record_id": 999999}, "商品不存在"),
])
def test_apply_candidate_pricing_rejects_missing_records(env, payload, message):
    body = env.client.post("/api/ops/apply-candidate-pricing", json=payload).get_json()
    assert body["success"] is False and message in body["msg"]


def test_product_issue_action_status_requires_a_value(env):
    body = env.client.post("/api/ops/product-issue-actions/1", json={}).get_json()
    assert body["success"] is False and "action_status 不能为空" in body["msg"]

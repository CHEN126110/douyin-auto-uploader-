# -*- coding: utf-8 -*-
"""AI 配置 / 标题 / 设置 / 定价四组接口回归：直接注册 Blueprint，注入隔离的数据库与数据目录。

不碰用户的真实设置和定价文件：SettingsManager 指向临时文件，``get_runtime_data_path`` 指向临时目录。
重点守住会悄悄出错的几处：
1. 设置接口回传不得带出模型密钥明文，前端只回传占位时必须沿用旧密钥；
2. 水洗标 / 吊牌图只能删除应用数据目录之内的文件；
3. 材质含量必须合计 100%，空名 / 超长名被拒绝；
4. 定价成本项的增删改查，以及「读设置失败」时的兜底成本项文本（曾被写成 ``??``）。
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest
from flask import Flask

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from sidecar_test_support import make_record_model  # noqa: E402
from src.config import LLM_PROVIDER_PRESETS, MATERIAL_NAME_MAX_LENGTH, SettingsManager  # noqa: E402
from src.sidecar import ai_routes, pricing_routes, settings_routes, title_routes  # noqa: E402


def _client(*blueprints):
    app = Flask(__name__)
    for blueprint in blueprints:
        app.register_blueprint(blueprint)
    return app.test_client()


@pytest.fixture()
def records(tmp_path):
    Record, database = make_record_model(tmp_path / "records.db")
    yield Record
    database.close()


@pytest.fixture()
def settings(tmp_path, monkeypatch):
    manager = SettingsManager(str(tmp_path / "user_settings.json"))
    for module in (ai_routes, settings_routes, pricing_routes):
        monkeypatch.setattr(module, "settings_manager", manager)
    return manager


# ------------------------------------------------------------------ AI 配置

class RecordingLLM:
    created = []

    def __init__(self, provider, api_key, base_url, model):
        RecordingLLM.created.append((provider, api_key, base_url, model))

    def test_connection(self, timeout=0):
        return True, "pong"

    def list_models(self):
        return True, ["m1"]


@pytest.fixture()
def ai_client(monkeypatch, settings):
    RecordingLLM.created = []
    monkeypatch.setattr(ai_routes, "LLMClient", RecordingLLM)
    return _client(ai_routes.create_ai_blueprint())


def test_ai_config_is_read_only_and_reports_external_ai_disabled(ai_client):
    for call in (ai_client.get("/api/ai/config"), ai_client.post("/api/ai/config", json={"x": 1})):
        body = call.get_json()
        assert body["success"] is True
        assert body["data"]["ai_policy"]["external_ai_disabled"] is True


def test_ai_test_rejects_unsupported_provider_without_creating_a_client(ai_client):
    body = ai_client.post("/api/ai/test", json={"openai": {"api_key": "k"}}).get_json()
    assert body["success"] is True  # 外层「测试完成」，逐个厂商的结果在 data 里
    assert body["data"]["openai"]["success"] is False
    assert RecordingLLM.created == []


def test_ai_models_falls_back_to_the_saved_key_when_the_frontend_sends_none(ai_client, settings):
    settings.update_settings({"model_configs": [
        {"id": "m1", "provider": "deepseek", "api_key": "sk-saved", "model": "x"}]})
    body = ai_client.post("/api/ai/models", json={"provider": "deepseek"}).get_json()
    assert body["success"] is True and body["data"]["models"] == ["m1"]
    provider, api_key, base_url, _model = RecordingLLM.created[-1]
    assert (provider, api_key) == ("deepseek", "sk-saved")
    assert base_url == LLM_PROVIDER_PRESETS["deepseek"]["base_url"]  # 地址仍以厂商预设为准


# ------------------------------------------------------------------ 标题

def test_title_routes_reject_missing_and_unknown_records(records):
    client = _client(title_routes.create_title_blueprint(record_model=records))
    for path in ("/api/generate_smart_title", "/api/generate_smart_title_enhanced",
                 "/api/generate_professional_title"):
        assert "缺少产品ID" in client.post(path, json={}).get_json()["msg"]
        assert "产品不存在" in client.post(path, json={"record_id": 999}).get_json()["msg"]


def test_professional_title_passes_the_record_through_the_generator(records, monkeypatch):
    seen = {}

    class FakeGenerator:
        def generate_professional_titles(self, info):
            seen["info"] = info
            return [types.SimpleNamespace(title="无品牌中筒袜", confidence=0.9, character_count=5,
                                          tags=["a"], reasoning="r", blue_ocean_words=["w"])]

    monkeypatch.setattr(title_routes, "get_professional_generator", lambda: FakeGenerator())
    record = records.create(name="小雏菊袜子", clazz="2", remark="春夏款",
                            content=json.dumps([{"name": "白"}], ensure_ascii=False))
    client = _client(title_routes.create_title_blueprint(record_model=records))
    body = client.post("/api/generate_professional_title", json={"record_id": record.id}).get_json()
    assert body["success"] is True
    assert body["data"]["suggestions"][0]["title"] == "无品牌中筒袜"
    assert body["data"]["product_info"] == {"name": "小雏菊袜子", "category": "2", "sku_count": 1}
    assert seen["info"].remark == "春夏款"


# ------------------------------------------------------------------ 设置

@pytest.fixture()
def settings_client(tmp_path, settings):
    assets_root = tmp_path / "runtime"
    assets_root.mkdir()
    blueprint = settings_routes.create_settings_blueprint(
        get_runtime_data_path=lambda name, legacy_fallback=None: str(assets_root / name))
    return types.SimpleNamespace(client=_client(blueprint), assets=assets_root / "automation_assets",
                                 tmp=tmp_path)


def _save_automation(client, **config):
    return client.post("/settings", json={"automation_config": config}).get_json()


def test_settings_reject_invalid_material_compositions(settings_client):
    client = settings_client.client
    too_long = "x" * (MATERIAL_NAME_MAX_LENGTH + 1)
    assert "不能为空" in _save_automation(client, material_compositions=[{"material": "", "percentage": 100}])["msg"]
    assert "过长" in _save_automation(client, material_compositions=[{"material": too_long, "percentage": 100}])["msg"]
    assert "等于100" in _save_automation(client, material_compositions=[{"material": "棉", "percentage": 90}])["msg"]
    ok = _save_automation(client, material_compositions=[{"material": "棉", "percentage": 70},
                                                         {"material": "氨纶", "percentage": 30}])
    assert ok["success"] is True


def test_settings_accept_decimal_material_percentages_without_truncation(settings_client):
    client = settings_client.client
    result = _save_automation(client, material_compositions=[
        {"material": "桑蚕丝", "percentage": 6.4},
        {"material": "羊毛", "percentage": 93.6},
    ])
    assert result["success"] is True, result
    saved = client.get("/settings").get_json()["data"]["settings"]["automation_config"]["material_compositions"]
    assert saved == [{"material": "桑蚕丝", "percentage": 6.4}, {"material": "羊毛", "percentage": 93.6}]


def test_settings_never_return_model_api_keys_and_keep_saved_ones(settings_client, settings):
    client = settings_client.client
    client.post("/settings", json={"model_configs": [
        {"id": "m1", "provider": "deepseek", "api_key": "sk-secret", "model": "a"}]})
    shown = client.get("/settings").get_json()["data"]["settings"]["model_configs"]
    assert shown[0]["api_key_set"] is True and "api_key" not in shown[0]
    # 前端只回传占位（没有 api_key）时，沿用已保存的密钥
    client.post("/settings", json={"model_configs": [
        {"id": "m1", "provider": "deepseek", "api_key_set": True, "model": "b"}]})
    saved = settings.get_settings().model_configs
    assert saved[0]["api_key"] == "sk-secret" and saved[0]["model"] == "b"


def test_publish_mode_round_trip_and_validation(settings_client):
    client = settings_client.client
    assert client.get("/settings/publish-mode").get_json()["data"]["publish_mode"] == "dom"
    assert client.post("/settings/publish-mode", json={"publish_mode": "protocol"}).get_json()["success"]
    assert client.get("/settings/publish-mode").get_json()["data"]["publish_mode"] == "protocol"
    assert client.post("/settings/publish-mode", json={"publish_mode": "bogus"}).get_json()["success"] is False


def test_wash_label_image_is_managed_inside_the_assets_dir_only(settings_client):
    from PIL import Image
    client = settings_client.client
    source = settings_client.tmp / "wash.png"
    Image.new("RGB", (4, 4), "red").save(source)

    imported = client.post("/settings/automation/wash-label/import", json={"source_path": str(source)}).get_json()
    assert imported["success"] is True
    stored = Path(imported["data"]["stored_path"])
    assert stored.parent == settings_client.assets and stored.is_file()

    # 只能删应用数据目录里的文件：源图在目录之外，必须被拒绝且原文件保留
    refused = client.post("/settings/automation/wash-label/remove", json={"stored_path": str(source)}).get_json()
    assert refused["success"] is False and source.is_file()
    removed = client.post("/settings/automation/wash-label/remove", json={"stored_path": str(stored)}).get_json()
    assert removed["success"] is True and not stored.exists()


def test_wash_label_import_rejects_non_image_extensions(settings_client):
    text = settings_client.tmp / "note.txt"
    text.write_text("x", encoding="utf-8")
    body = settings_client.client.post("/settings/automation/wash-label/import",
                                       json={"source_path": str(text)}).get_json()
    assert body["success"] is False and "仅支持" in body["msg"]


# ------------------------------------------------------------------ 定价

@pytest.fixture()
def pricing_env(tmp_path, records, settings):
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    blueprint = pricing_routes.create_pricing_blueprint(
        record_model=records, get_runtime_data_path=lambda name, legacy_fallback=None: str(runtime / name))
    return types.SimpleNamespace(client=_client(blueprint), config_file=runtime / "pricing_config.json",
                                 Record=records)


def _cost_item(name, value=1.0, cost_type="fixed"):
    return {"name": name, "cost_type": cost_type, "value": value, "description": name}


def test_cost_item_crud_round_trip(pricing_env):
    client = pricing_env.client
    assert client.post("/api/pricing/cost-item", json=_cost_item("包装费", 0.5)).get_json()["success"]
    assert "已存在" in client.post("/api/pricing/cost-item", json=_cost_item("包装费")).get_json()["error"]
    assert client.put("/api/pricing/cost-item/包装费", json={"value": 0.8, "is_active": 0}).get_json()["success"]
    items = client.get("/api/pricing/cost-items").get_json()["data"]
    assert items["total_count"] == 1 and items["active_count"] == 0
    assert items["cost_items"][0]["value"] == 0.8
    assert client.delete("/api/pricing/cost-item/包装费").get_json()["remaining_items"] == 0
    assert "不存在" in client.delete("/api/pricing/cost-item/包装费").get_json()["error"]


@pytest.mark.parametrize("payload,fragment", [
    ({}, "请求数据为空"),
    ({"cost_items": []}, "缺少目标利润率"),
    ({"cost_items": "x", "target_profit_rate": 0.3}, "格式错误"),
    ({"cost_items": [{"name": "a"}], "target_profit_rate": 0.3}, "缺少cost_type"),
    ({"cost_items": [_cost_item("a", -1)], "target_profit_rate": 0.3}, "不能为负数"),
    ({"cost_items": [_cost_item("a")], "target_profit_rate": 2}, "0-100%"),
])
def test_cost_config_validation(pricing_env, payload, fragment):
    body = pricing_env.client.post("/api/pricing/cost-config", json=payload).get_json()
    assert body["success"] is False and fragment in body["error"]
    assert not pricing_env.config_file.exists()


def test_profit_margin_is_stored_as_a_decimal(pricing_env):
    body = pricing_env.client.post("/api/pricing/profit-margin-config", json={"profit_margin": 35}).get_json()
    assert body["success"] is True and body["data"]["profit_margin_decimal"] == 0.35
    stored = json.loads(pricing_env.config_file.read_text(encoding="utf-8"))
    assert stored["templates"][pricing_routes.DEFAULT_PRICING_TEMPLATE]["profit_margin"] == 0.35


def test_smart_prices_fall_back_to_default_cost_items_when_settings_fail(pricing_env, monkeypatch):
    captured = {}

    class FakeEngine:
        def __init__(self, config_file):
            captured["config_file"] = config_file

        def calculate_runtime_pricing(self, sku_list, unit_price, pricing_config, cost_items):
            captured.update(cost_items=cost_items, pricing_config=pricing_config)
            return {"pricing_results": [{"sku": 1}], "statistics": {}, "config_used": {}}

    class BrokenSettings:
        def get_settings(self):
            raise RuntimeError("settings unavailable")

    monkeypatch.setattr(pricing_routes, "settings_manager", BrokenSettings())
    monkeypatch.setattr("src.smart_pricing_engine.SmartPricingEngine", FakeEngine)
    record = pricing_env.Record.create(name="袜子", content=json.dumps([{"name": "白", "price": 1}]))
    body = pricing_env.client.post("/api/pricing/calculate_smart_prices",
                                   json={"record_id": record.id, "unit_price": 2.2}).get_json()
    assert body["success"] is True
    assert [item["name"] for item in captured["cost_items"]] == ["运费", "包装费", "平台佣金"]
    assert captured["pricing_config"] == {"target_gross_margin": 30}
    assert Path(captured["config_file"]) == pricing_env.config_file

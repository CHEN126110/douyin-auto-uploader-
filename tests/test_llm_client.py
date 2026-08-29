# -*- coding: utf-8 -*-
"""LLM 客户端(阶段A)单元测试。全程 mock requests，不真调外部 API。"""
import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest

from src.config import sanitize_model_configs, ALLOWED_PUBLISH_AI_PROVIDERS
from src.llm_client import (
    LLMClient,
    LLMError,
    build_client_from_config,
    get_active_llm_client,
)


# ---------- config.sanitize_model_configs ----------
def test_sanitize_keeps_allowed_providers():
    configs = [
        {"provider": "deepseek", "api_key": "sk-x", "model": "deepseek-chat"},
        {"provider": "xiaomi", "api_key": "k", "base_url": "https://x.example.com"},
        {"provider": "openai", "api_key": "sk-y"},  # 应被过滤
    ]
    out = sanitize_model_configs(configs)
    providers = [c["provider"] for c in out]
    assert "deepseek" in providers
    assert "xiaomi" in providers
    assert "openai" not in providers


def test_sanitize_deepseek_fills_preset_base_url_and_model():
    out = sanitize_model_configs([{"provider": "deepseek", "api_key": "sk-x"}])
    assert len(out) == 1
    c = out[0]
    assert c["base_url"] == "https://api.deepseek.com"
    assert c["model"] == "deepseek-chat"
    assert c["enabled"] is True  # 有密钥+端点


def test_sanitize_disabled_when_missing_key():
    # 无密钥 -> 不可用（小米/DeepSeek 的 base_url 均由预设提供）
    out = sanitize_model_configs([{"provider": "xiaomi", "api_key": ""}])
    assert out[0]["enabled"] is False
    out2 = sanitize_model_configs([{"provider": "deepseek", "api_key": ""}])
    assert out2[0]["enabled"] is False


def test_sanitize_xiaomi_enabled_with_key_only():
    # 小米已有预设 base_url(实证确认)，只填密钥即可用
    out = sanitize_model_configs([{"provider": "xiaomi", "api_key": "k"}])
    assert out[0]["enabled"] is True
    assert out[0]["base_url"] == "https://api.xiaomimimo.com/v1"


def test_sanitize_non_list():
    assert sanitize_model_configs(None) == []
    assert sanitize_model_configs("x") == []


# ---------- LLMClient.chat ----------
def _mock_resp(status=200, json_data=None, text=""):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = json_data if json_data is not None else {}
    r.text = text
    return r


def test_chat_success():
    client = LLMClient("deepseek", "sk-x", "https://api.deepseek.com", "deepseek-chat")
    payload_holder = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        payload_holder["url"] = url
        payload_holder["json"] = json
        payload_holder["headers"] = headers
        return _mock_resp(200, {"choices": [{"message": {"content": "男士纯棉中筒袜"}}]})

    with patch("src.llm_client.requests.post", side_effect=fake_post):
        out = client.chat([{"role": "user", "content": "生成标题"}])
    assert out == "男士纯棉中筒袜"
    assert payload_holder["url"] == "https://api.deepseek.com/chat/completions"
    assert payload_holder["headers"]["Authorization"] == "Bearer sk-x"
    assert payload_holder["json"]["model"] == "deepseek-chat"


def test_chat_401_clear_message():
    client = LLMClient("deepseek", "sk-bad", "https://api.deepseek.com", "deepseek-chat")
    with patch("src.llm_client.requests.post", return_value=_mock_resp(401, text="unauthorized")):
        with pytest.raises(LLMError) as ei:
            client.chat([{"role": "user", "content": "x"}])
    assert "密钥" in str(ei.value) and "401" in str(ei.value)


def test_chat_429():
    client = LLMClient("deepseek", "sk-x", "https://api.deepseek.com", "deepseek-chat")
    with patch("src.llm_client.requests.post", return_value=_mock_resp(429)):
        with pytest.raises(LLMError) as ei:
            client.chat([{"role": "user", "content": "x"}])
    assert "429" in str(ei.value)


def test_chat_non_openai_format():
    client = LLMClient("xiaomi", "k", "https://x.example.com", "milm")
    with patch("src.llm_client.requests.post", return_value=_mock_resp(200, {"unexpected": 1})):
        with pytest.raises(LLMError) as ei:
            client.chat([{"role": "user", "content": "x"}])
    assert "OpenAI 兼容" in str(ei.value)


def test_validate_missing_fields():
    with pytest.raises(LLMError):
        LLMClient("deepseek", "", "https://api.deepseek.com", "deepseek-chat").chat([])
    with pytest.raises(LLMError):
        LLMClient("xiaomi", "k", "", "milm").chat([])
    with pytest.raises(LLMError):
        LLMClient("unknown", "k", "https://x", "m").chat([])


# ---------- get_active_llm_client ----------
def test_get_active_returns_none_when_no_config():
    assert get_active_llm_client(None) is None
    assert get_active_llm_client([]) is None
    # 未启用
    assert get_active_llm_client([{"provider": "deepseek", "api_key": "k", "base_url": "https://api.deepseek.com", "enabled": False}]) is None


def test_get_active_picks_enabled():
    cfgs = sanitize_model_configs([{"provider": "deepseek", "api_key": "sk-x"}])
    client = get_active_llm_client(cfgs)
    assert client is not None
    assert client.provider == "deepseek"
    assert client.base_url == "https://api.deepseek.com"


# ---------- 推理模型(mimo)场景 ----------
def test_test_connection_success_even_empty_content():
    """推理模型 content 空但响应结构合法 → 连接成功（不误判失败）。"""
    client = LLMClient("xiaomi", "k", "https://api.xiaomimimo.com/v1", "mimo-v2.5-pro")
    with patch("src.llm_client.requests.post",
               return_value=_mock_resp(200, {"choices": [{"message": {"content": ""}}]})):
        ok, detail = client.test_connection()
    assert ok is True


def test_test_connection_401():
    client = LLMClient("deepseek", "bad", "https://api.deepseek.com", "deepseek-chat")
    with patch("src.llm_client.requests.post", return_value=_mock_resp(401)):
        ok, detail = client.test_connection()
    assert ok is False and "401" in detail


def test_test_connection_non_openai_format():
    client = LLMClient("xiaomi", "k", "https://x.example.com/v1", "mimo-v2.5-pro")
    with patch("src.llm_client.requests.post", return_value=_mock_resp(200, {"unexpected": 1})):
        ok, detail = client.test_connection()
    assert ok is False and "choices" in detail


def test_chat_reasoning_content_fallback():
    """content 空但有 reasoning_content → chat 取 reasoning（推理模型）。"""
    client = LLMClient("xiaomi", "k", "https://api.xiaomimimo.com/v1", "mimo-v2.5-pro")
    with patch("src.llm_client.requests.post",
               return_value=_mock_resp(200, {"choices": [{"message": {"content": "", "reasoning_content": "思考过程"}}]})):
        out = client.chat([{"role": "user", "content": "x"}])
    assert out == "思考过程"


# ---------- list_models（动态获取模型）----------
def test_list_models_success():
    client = LLMClient("deepseek", "sk-x", "https://api.deepseek.com", "")
    with patch("src.llm_client.requests.get",
               return_value=_mock_resp(200, {"data": [{"id": "deepseek-chat"}, {"id": "deepseek-reasoner"}]})):
        ok, models = client.list_models()
    assert ok is True
    assert "deepseek-chat" in models and "deepseek-reasoner" in models


def test_list_models_401():
    client = LLMClient("xiaomi", "bad", "https://api.xiaomimimo.com/v1", "")
    with patch("src.llm_client.requests.get", return_value=_mock_resp(401)):
        ok, err = client.list_models()
    assert ok is False and "401" in err


def test_list_models_non_openai_format():
    client = LLMClient("xiaomi", "k", "https://x.example.com/v1", "")
    with patch("src.llm_client.requests.get", return_value=_mock_resp(200, {"unexpected": 1})):
        ok, err = client.list_models()
    assert ok is False and "data" in err


def test_list_models_needs_key():
    client = LLMClient("deepseek", "", "https://api.deepseek.com", "")
    ok, err = client.list_models()
    assert ok is False and "密钥" in err

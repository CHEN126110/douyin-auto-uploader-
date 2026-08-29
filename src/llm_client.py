# -*- coding: utf-8 -*-
"""LLM 客户端（发布信息优化用）

通用 OpenAI 兼容 Chat Completions 客户端，支持 DeepSeek / 小米大模型两个系列。
仅供"发布信息优化"（标题/属性/卖点）调用；运营决策(ops)不使用本模块。

设计：
- OpenAI 兼容：POST {base_url}/chat/completions，Authorization: Bearer <api_key>。
  DeepSeek 确认兼容；小米按其开放平台端点填 base_url（多数国产大模型 OpenAI 兼容）。
- 错误信息明确可诊断（哪一步失败、什么原因、关联 provider/base_url），不吞错、不兜底假数据。
- 不在日志/异常中回显完整 api_key。
"""
from __future__ import annotations

from typing import Dict, List, Optional, Sequence

import requests

from .config import ALLOWED_PUBLISH_AI_PROVIDERS, LLM_PROVIDER_PRESETS


class LLMError(Exception):
    """LLM 调用错误，message 已是面向用户的可诊断中文描述。"""


class LLMClient:
    def __init__(self, provider: str, api_key: str, base_url: str, model: str):
        self.provider = (provider or "").strip().lower()
        self.api_key = (api_key or "").strip()
        self.base_url = (base_url or "").strip().rstrip("/")
        self.model = (model or "").strip()

    def _validate(self) -> None:
        if self.provider not in ALLOWED_PUBLISH_AI_PROVIDERS:
            raise LLMError(f"不支持的模型厂商：{self.provider or '(空)'}（仅允许 {', '.join(ALLOWED_PUBLISH_AI_PROVIDERS)}）")
        if not self.api_key:
            raise LLMError(f"{self.provider} 调用失败：未配置 API 密钥")
        if not self.base_url:
            label = LLM_PROVIDER_PRESETS.get(self.provider, {}).get("label", self.provider)
            raise LLMError(f"{label} 调用失败：未配置 API 端点 base_url（请在设置中填写）")
        if not self.model:
            raise LLMError(f"{self.provider} 调用失败：未指定模型名")

    def chat(
        self,
        messages: Sequence[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 512,
        timeout: float = 30.0,
    ) -> str:
        """调用 chat completions，返回首条回复文本。失败抛 LLMError（含可诊断原因）。"""
        self._validate()
        url = self.base_url + "/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": list(messages),
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
        except requests.exceptions.Timeout:
            raise LLMError(f"{self.provider} 调用超时（{timeout}s，端点 {self.base_url}）")
        except requests.exceptions.ConnectionError:
            raise LLMError(f"{self.provider} 无法连接到端点 {self.base_url}（请检查网络或 base_url 是否正确）")
        except Exception as e:  # noqa: BLE001 - 统一转可诊断错误
            raise LLMError(f"{self.provider} 请求发送失败：{e}")

        if resp.status_code == 401:
            raise LLMError(f"{self.provider} API 密钥无效或未授权（401）")
        if resp.status_code == 429:
            raise LLMError(f"{self.provider} 请求过于频繁或额度不足（429）")
        if resp.status_code >= 500:
            raise LLMError(f"{self.provider} 服务端错误（{resp.status_code}），稍后重试")
        if resp.status_code != 200:
            snippet = (resp.text or "")[:200]
            raise LLMError(f"{self.provider} 调用返回异常状态 {resp.status_code}：{snippet}")

        try:
            data = resp.json()
        except Exception:
            raise LLMError(f"{self.provider} 响应不是合法 JSON（端点 {self.base_url} 可能非 OpenAI 兼容接口）")

        try:
            msg = data["choices"][0]["message"]
            text = (msg.get("content") or "").strip()
            if not text:
                # 推理模型(如 mimo-v2.5-pro)答案可能在 reasoning_content；content 空也常因 max_tokens 不足
                text = (msg.get("reasoning_content") or "").strip()
        except (KeyError, IndexError, TypeError, AttributeError):
            raise LLMError(f"{self.provider} 响应缺少 choices[0].message.content（端点可能非 OpenAI 兼容格式）")

        if not text:
            raise LLMError(f"{self.provider} 返回空内容（若为推理模型请增大 max_tokens 后重试）")
        return text

    def complete(self, prompt: str, system: Optional[str] = None, **kwargs) -> str:
        messages: List[Dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        return self.chat(messages, **kwargs)

    def test_connection(self, timeout: float = 20.0):
        """连通性测试：验证密钥/端点/模型可用。返回 (ok: bool, detail: str)。
        判定标准是"响应结构合法"而非"content 非空"——推理模型(如 mimo)在小 max_tokens 下
        content 可能为空但连接其实正常，不应误判为失败。"""
        self._validate()
        url = self.base_url + "/chat/completions"
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": "你好"}],
            "max_tokens": 64,
            "stream": False,
        }
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
        except requests.exceptions.Timeout:
            return False, f"调用超时（{timeout}s，端点 {self.base_url}）"
        except requests.exceptions.ConnectionError:
            return False, f"无法连接端点 {self.base_url}（请检查网络或 base_url）"
        except Exception as e:  # noqa: BLE001
            return False, f"请求发送失败：{e}"

        if resp.status_code == 401:
            return False, "API 密钥无效或未授权（401）"
        if resp.status_code == 429:
            return False, "请求过于频繁或额度不足（429）"
        if resp.status_code >= 500:
            return False, f"服务端错误（{resp.status_code}）"
        if resp.status_code != 200:
            return False, f"异常状态 {resp.status_code}：{(resp.text or '')[:120]}"

        try:
            data = resp.json()
        except Exception:
            return False, "响应不是合法 JSON（端点可能非 OpenAI 兼容接口）"

        choices = data.get("choices") if isinstance(data, dict) else None
        if not (isinstance(choices, list) and choices):
            return False, "响应缺少 choices（端点可能非 OpenAI 兼容格式）"
        msg = choices[0].get("message", {}) if isinstance(choices[0], dict) else {}
        content = (msg.get("content") or "").strip() if isinstance(msg, dict) else ""
        reasoning = (msg.get("reasoning_content") or "").strip() if isinstance(msg, dict) else ""
        if content:
            return True, f"连接成功：{content[:40]}"
        if reasoning:
            return True, "连接成功（推理模型，思考链正常）"
        return True, "连接成功（本次未返回文本，属正常，调用时会用更大 max_tokens）"

    def list_models(self, timeout: float = 15.0):
        """调 OpenAI 兼容 GET /models 列出可用模型。返回 (ok: bool, models|error)。
        只需 api_key + base_url，不需要预先指定 model。"""
        if self.provider not in ALLOWED_PUBLISH_AI_PROVIDERS:
            return False, f"不支持的厂商：{self.provider or '(空)'}"
        if not self.api_key:
            return False, "未配置 API 密钥"
        if not self.base_url:
            return False, "未配置 API 端点 base_url"
        url = self.base_url + "/models"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        try:
            resp = requests.get(url, headers=headers, timeout=timeout)
        except requests.exceptions.Timeout:
            return False, f"获取模型超时（{timeout}s，端点 {self.base_url}）"
        except requests.exceptions.ConnectionError:
            return False, f"无法连接端点 {self.base_url}（请检查网络或 base_url）"
        except Exception as e:  # noqa: BLE001
            return False, f"请求发送失败：{e}"

        if resp.status_code == 401:
            return False, "API 密钥无效或未授权（401）"
        if resp.status_code == 429:
            return False, "请求过于频繁或额度不足（429）"
        if resp.status_code != 200:
            return False, f"获取模型失败（{resp.status_code}）：{(resp.text or '')[:120]}"

        try:
            data = resp.json()
        except Exception:
            return False, "响应不是合法 JSON（端点可能非 OpenAI 兼容接口）"

        items = data.get("data") if isinstance(data, dict) else None
        if not isinstance(items, list):
            return False, "响应缺少 data 列表（端点可能非 OpenAI 兼容格式）"
        models: List[str] = []
        for m in items:
            if isinstance(m, dict) and m.get("id"):
                models.append(str(m["id"]))
            elif isinstance(m, str) and m.strip():
                models.append(m.strip())
        if not models:
            return False, "模型列表为空"
        return True, models


def build_client_from_config(cfg: Dict) -> LLMClient:
    """从单条模型配置构造客户端。base_url 缺省用厂商预设。"""
    provider = str(cfg.get("provider") or "").strip().lower()
    preset = LLM_PROVIDER_PRESETS.get(provider, {})
    # 兼容前端字段名(api_base/model_name)
    base_url = str(cfg.get("base_url") or cfg.get("api_base") or preset.get("base_url") or "").strip()
    models = preset.get("models") or []
    model = str(cfg.get("model") or cfg.get("model_name") or "").strip() or (models[0] if models else "")
    return LLMClient(
        provider=provider,
        api_key=str(cfg.get("api_key") or ""),
        base_url=base_url,
        model=model,
    )


def get_active_llm_client(model_configs: Optional[Sequence[Dict]]) -> Optional[LLMClient]:
    """从模型配置列表选出第一个可用(enabled+密钥+端点)的客户端；无则返回 None。
    返回 None 表示应回退到本地引擎（混合模式的兜底）。"""
    if not model_configs:
        return None
    for cfg in model_configs:
        if not isinstance(cfg, dict):
            continue
        if not cfg.get("enabled"):
            continue
        if not (cfg.get("api_key") and (cfg.get("base_url") or LLM_PROVIDER_PRESETS.get(str(cfg.get("provider", "")).lower(), {}).get("base_url"))):
            continue
        try:
            return build_client_from_config(cfg)
        except Exception:
            continue
    return None

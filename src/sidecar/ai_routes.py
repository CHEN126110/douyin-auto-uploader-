# -*- coding: utf-8 -*-
"""发布优化 LLM 配置与连通性接口（/api/ai/*）。

外部 AI 对运营闭环是禁用的（见 ``AI_POLICY``）；这里只服务「发布优化」所允许的厂商。"""
import traceback

from flask import Blueprint, request

from src.config import ALLOWED_PUBLISH_AI_PROVIDERS, LLM_PROVIDER_PRESETS, settings_manager
from src.llm_client import LLMClient, LLMError
from src.ops_engine import AI_POLICY
from .responses import api_error, api_ok


def create_ai_blueprint():
    """不需要注入依赖：设置、LLM 客户端都直接来自 src 下的轻量模块。"""
    routes = Blueprint('ai', __name__)

    @routes.get('/api/ai/config')
    def get_ai_config():
        """获取AI配置API"""
        return api_ok('外部 AI 已禁用', data={
            'ai_policy': dict(AI_POLICY),
            'providers': {
                'deepseek': {'enabled': False, 'api_key': '', 'model': '', 'priority': 1},
                'openai': {'enabled': False, 'api_key': '', 'model': '', 'priority': 2},
                'claude': {'enabled': False, 'api_key': '', 'model': '', 'priority': 3},
            }
        })

    @routes.post('/api/ai/config')
    def save_ai_config():
        """保存AI配置API"""
        return api_ok('外部 AI 已禁用，配置未保存', data={
            'ai_policy': dict(AI_POLICY),
            'model_configs': [],
        })

    @routes.post('/api/ai/test')
    def test_ai_connection():
        """测试发布优化 LLM 连接（仅小米/DeepSeek）。
    payload: {provider: {api_key, model, api_base?/base_url?}}；逐个真实调用一次短 prompt。"""
        try:
            data = request.get_json(silent=True) or {}
            if not isinstance(data, dict) or not data:
                return api_error('未提供模型配置')
            results = {}
            for provider, cfg in data.items():
                if not isinstance(cfg, dict):
                    continue
                p = str(provider).strip().lower()
                if p not in ALLOWED_PUBLISH_AI_PROVIDERS:
                    results[provider] = {
                        'success': False,
                        'error': f'仅支持发布优化厂商 {", ".join(ALLOWED_PUBLISH_AI_PROVIDERS)}，不支持 {provider}',
                    }
                    continue
                preset = LLM_PROVIDER_PRESETS.get(p, {})
                base_url = str(cfg.get('base_url') or cfg.get('api_base') or preset.get('base_url') or '')
                preset_models = preset.get('models') or []
                model = str(cfg.get('model') or cfg.get('model_name') or '') or (preset_models[0] if preset_models else '')
                client = LLMClient(p, str(cfg.get('api_key') or ''), base_url, model)
                try:
                    ok, detail = client.test_connection(timeout=20)
                    if ok:
                        results[provider] = {'success': True, 'reply': detail, 'model': model}
                    else:
                        results[provider] = {'success': False, 'error': detail}
                except LLMError as e:
                    results[provider] = {'success': False, 'error': str(e)}
                except Exception as e:
                    results[provider] = {'success': False, 'error': f'测试失败：{e}'}
            if not results:
                return api_error('未提供有效的模型配置')
            return api_ok('测试完成', data=results)
        except Exception as e:
            traceback.print_exc()
            return api_error(f'测试失败：{e}')

    @routes.post('/api/ai/models')
    def list_ai_models():
        """获取某厂商可用模型列表（OpenAI 兼容 GET /models）。
    payload: {provider, api_key?, api_base?/base_url?}；未传密钥时回退已存配置。"""
        try:
            data = request.get_json(silent=True) or {}
            provider = str(data.get('provider') or '').strip().lower()
            if provider not in ALLOWED_PUBLISH_AI_PROVIDERS:
                return api_error(f'仅支持 {", ".join(ALLOWED_PUBLISH_AI_PROVIDERS)}')
            preset = LLM_PROVIDER_PRESETS.get(provider, {})
            api_key = str(data.get('api_key') or '').strip()
            base_url = str(data.get('base_url') or data.get('api_base') or preset.get('base_url') or '').strip()
            # 前端未带密钥（如只回传占位）时，回退到已保存配置
            if not api_key:
                for c in (settings_manager.get_settings().model_configs or []):
                    if str(c.get('provider') or '').lower() == provider and c.get('api_key'):
                        api_key = c.get('api_key')
                        if not base_url:
                            base_url = c.get('base_url') or c.get('api_base') or ''
                        break
            client = LLMClient(provider, api_key, base_url, '')
            ok, result = client.list_models()
            if ok:
                return api_ok('获取成功', data={'models': result})
            return api_error(result)
        except Exception as e:
            traceback.print_exc()
            return api_error(f'获取模型失败：{e}')

    return routes

# -*- coding: utf-8 -*-
"""各业务域的新旧对打场景。每个场景：setup / patch_old / build_new / requests / final。"""
import json
from datetime import datetime

SCENARIOS = {}

SKUS = [
    {'name': '动物白 / 均码', 'path': 'a.jpg', 'price': 2.0},
    {'name': '动物粉 / 均码', 'path': 'b.jpg', 'price': 2.5, 'ops_goods_cost': 1.8},
]


def make_records(ctx):
    R = ctx.Record
    R.create(id=101, name='测试袜子A', path='uploads/products/A', type=1, status=0, repo=3,
             title='小雏菊碎花袜子女', clazz='2', remark='春夏款', content=json.dumps(SKUS, ensure_ascii=False),
             update_time=datetime(2026, 1, 1), source_url='https://example.invalid/a')
    R.create(id=102, name='纯棉中筒袜男', path='uploads/products/B', type=1, status=0, repo=0,
             title='', clazz='1', content='[]', update_time=datetime(2026, 1, 2))
    R.create(id=103, name='坏内容', path='uploads/products/C', type=1, status=1, repo=1,
             title='x', clazz='3', content='not json', update_time=datetime(2026, 1, 3))


# ------------------------------------------------------------------ ai + title
class FakeLLMError(Exception):
    pass


def _fake_llm_factory(error_cls):
    class FakeLLM:
        calls = []

        def __init__(self, provider, api_key, base_url, model):
            self.args = (provider, api_key, base_url, model)
            FakeLLM.calls.append(('init', provider, api_key, base_url, model))

        def test_connection(self, timeout=0):
            FakeLLM.calls.append(('test', self.args[0], timeout))
            if self.args[1] == 'boom':
                raise error_cls('模拟失败')
            if self.args[1] == 'crash':
                raise RuntimeError('模拟崩溃')
            if not self.args[1]:
                return False, '缺少密钥'
            return True, 'pong'

        def list_models(self):
            FakeLLM.calls.append(('list', self.args[0]))
            if not self.args[1]:
                return False, '缺少密钥'
            return True, ['m1', 'm2']
    return FakeLLM


def ai_title_patch_old(ctx):
    Fake = _fake_llm_factory(ctx.mod.LLMError)
    ctx.state['llm'] = Fake
    ctx.mod.LLMClient = Fake


def ai_title_build_new(ctx):
    from src.sidecar import ai_routes
    from src.sidecar.title_routes import create_title_blueprint
    Fake = _fake_llm_factory(ai_routes.LLMError)
    ctx.state['llm'] = Fake
    ai_routes.LLMClient = Fake
    return [ai_routes.create_ai_blueprint(), create_title_blueprint(record_model=ctx.Record)]


def _seed(ctx):
    import random
    random.seed(20261018)


# 专业标题生成器内部用 random 选词：固定种子后，新旧两边才有可比性
SEEDED = {'before': _seed}


def ai_title_requests(ctx):
    return [
        ('GET', '/api/ai/config', None),
        ('POST', '/api/ai/config', {'deepseek': {'api_key': 'x'}}),
        ('POST', '/api/ai/test', {}),
        ('POST', '/api/ai/test', {'openai': {'api_key': 'k'}}),
        ('POST', '/api/ai/test', {'deepseek': {'api_key': 'k', 'model': 'dm'}}),
        ('POST', '/api/ai/test', {'deepseek': {'api_key': 'boom'}, 'xiaomi': {'api_key': 'crash'}}),
        ('POST', '/api/ai/test', {'deepseek': 'not-a-dict'}),
        ('POST', '/api/ai/models', {}),
        ('POST', '/api/ai/models', {'provider': 'deepseek', 'api_key': 'k'}),
        ('POST', '/api/ai/models', {'provider': 'deepseek'}),
        ('POST', '/api/ai/models', {'provider': 'bogus'}),
        ('POST', '/api/generate_smart_title', {}),
        ('POST', '/api/generate_smart_title', {'record_id': 999999}),
        ('POST', '/api/generate_smart_title', {'record_id': 101}),
        ('POST', '/api/generate_smart_title', {'record_id': 103}),
        ('POST', '/api/generate_smart_title_enhanced', {}),
        ('POST', '/api/generate_smart_title_enhanced', {'record_id': 101}),
        ('POST', '/api/generate_smart_title_enhanced', {'record_id': 103}),
        ('GET', '/api/trending_keywords/3?limit=5', None),
        ('GET', '/api/trending_keywords/9', None),
        ('POST', '/api/refresh_trending_keywords', {'category_id': 2}),
        ('POST', '/api/refresh_trending_keywords', {}),
        ('POST', '/api/generate_professional_title', {}),
        ('POST', '/api/generate_professional_title', {'record_id': 999999}),
        ('POST', '/api/generate_professional_title', {'record_id': 101}, SEEDED),
        ('POST', '/api/generate_professional_title', {'record_id': 102}, SEEDED),
        ('POST', '/api/generate_professional_title', {'record_id': 103}, SEEDED),
    ]


SCENARIOS['ai_title'] = dict(
    setup=make_records,
    patch_old=ai_title_patch_old,
    build_new=ai_title_build_new,
    requests=ai_title_requests,
    final=lambda ctx: {'llm_calls': [list(c) for c in ctx.state['llm'].calls]},
)

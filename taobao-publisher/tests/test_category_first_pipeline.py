# -*- coding: utf-8 -*-
"""共同HTTP入口→真实类目处理器→下一步；浏览器始终为独立 file: 模型。"""
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from test_offline_pipeline_handoff import handoff, save_and_start, save_case, browser, fixture_contracts
from test_candidate_form_adapters import item
from taobao_publish import page, pipeline, stages, form_adapters
from taobao_publish.constants import STAGE_ORDER
from taobao_publish.contracts import load_contracts


ROOT = Path(__file__).resolve().parents[2]
REAL_CATEGORY_HANDLER = stages.stage_select_category
CATEGORY_URL = 'https://item.upload.taobao.com/sell/ai/category.htm'


class LocalCategoryClient:
    """只替换导航地址边界；输入、按钮、候选和面包屑表达式真实执行。"""
    def __init__(self, browser, ns, cancel_after_next=False):
        self.browser = browser
        self.ns = ns
        self.cancel_after_next = cancel_after_next

    def evaluate(self, expression, **kwargs):
        if expression == 'location.href':
            href = self.browser.evaluate('window.categoryModel.href')
            if self.cancel_after_next and href != CATEGORY_URL:
                for task in self.ns['_taobao_tasks'].values():
                    task['cancelled'] = True
            return href
        return self.browser.evaluate(expression, **kwargs)

    def navigate(self, url, **kwargs):
        raise AssertionError('本地模型不得发起平台导航：' + url)

    def close(self):
        pass  # 底层仅由新建浏览器夹具统一关闭。

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def __getattr__(self, name):
        return getattr(self.browser, name)


def install_model(handoff, contracts, monkeypatch, variant='ok', cancel=False):
    assert handoff.browser.evaluate('location.protocol') == 'file:'
    source = Path(__file__).parent / 'fixtures/category-stage.js'
    handoff.browser.evaluate(source.read_text(encoding='utf-8'))
    handoff.browser.evaluate('setupCategoryModel(%s)' % json.dumps(variant))
    client = LocalCategoryClient(handoff.browser, handoff.case.ns, cancel_after_next=cancel)
    monkeypatch.setattr(stages, '_open_publish_page', lambda *_args, **_kwargs: client)
    monkeypatch.setitem(stages.STAGE_HANDLERS, 'select_category',
        replace(stages.STAGE_HANDLERS['select_category'], run=REAL_CATEGORY_HANDLER))
    actual_run = pipeline.run_from_record
    handoff.case.ns['_load_taobao_pipeline'] = lambda: SimpleNamespace(
        run_from_record=lambda *args, **kwargs: actual_run(*args, **kwargs, contracts=contracts))
    # 缩短固定等待，仍让真实异步面包屑/地址更新发生，不替换任何类目DOM动作。
    actual_sleep = time.sleep
    monkeypatch.setattr(page.time, 'sleep', lambda seconds: actual_sleep(min(seconds, 0.02)))
    actual_wait = page.wait_for_confirm_button
    monkeypatch.setattr(page, 'wait_for_confirm_button', lambda c: actual_wait(c, timeout=0.4, interval=0.02))
    actual_confirm = page.confirm_category_and_read_id
    monkeypatch.setattr(page, 'confirm_category_and_read_id',
                        lambda c: actual_confirm(c, wait=3.0))
    return client


def assert_no_platform_writes(handoff):
    assert handoff.uploads == []
    assert handoff.browser.evaluate('window.submitCalls + window.draftCalls') == 0
    assert handoff.browser.evaluate('location.protocol') == 'file:'


def test_real_http_task_continues_through_images_before_missing_detail_adapter(handoff, monkeypatch):
    install_model(handoff, load_contracts(), monkeypatch)
    _, task = save_and_start(handoff)
    assert task['status'] == 'failed', task
    assert task['result']['stage'] == 'fill_detail'
    assert task['result']['stopped_before_submit'] is True
    # 跑到 `fill_detail` 失败为止；阶段清单按 STAGE_ORDER 取前缀，
    # **不手写清单**——加阶段时这里会自动跟着走（否则每加一个阶段都要改这一行）。
    ran = [step['name'] for step in task['steps']]
    expected_names = list(STAGE_ORDER[:STAGE_ORDER.index('fill_detail') + 1])
    assert ran == expected_names, ran
    assert [step['status'] for step in task['steps']][:-1] == ['ok'] * (len(ran) - 1)
    assert task['steps'][-1]['status'] == 'failed'
    state = handoff.browser.evaluate('window.categoryModel')
    assert state['keyword'] == '中筒袜'
    assert state['candidateClicks'] == 1 and state['nextClicks'] == 1
    assert state['events'] == ['input', 'change', 'search', 'category_tab', 'select_category', 'brand_open', 'brand_search', 'brand_select', 'next']
    assert page.category_id_from_publish_url(state['href']) == '900000001'
    assert task['result']['error']['code'] == 'PAGE_ERROR'
    assert '文本输入模式' in task['error']
    deferred = task['result']['data']['deferred_adapter_blockers']
    assert deferred == {}
    assert len(handoff.uploads) == 5
    assert page.read_main_image_slots(handoff.browser)['filled'] == 1
    assert handoff.browser.evaluate('window.submitCalls + window.draftCalls') == 0
    from taobao_publish.sanitize import assert_clean
    artifact = {'scope': 'local_file_model_with_real_http_worker_and_category_handler',
        'boundaries_simulated': ['browser_bootstrap', 'session_metadata', 'navigation_address'],
        'live_platform_tested': False, 'next_clicks': state['nextClicks'],
        'category_events': state['events'], 'result': task['result'],
        'actual_browser_protocol': 'file:', 'platform_writes': False,
        'model_upload_count': len(handoff.uploads), 'model_main_image_count': 1,
        'test_source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    assert_clean(artifact)
    (ROOT / 'taobao-publisher/outputs/category_first_pipeline_handoff.json').write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


@pytest.mark.parametrize('variant,code,next_clicks', [
    ('ambiguous', 'CANDIDATE_NOT_FOUND', 0), ('missing', 'CANDIDATE_NOT_FOUND', 0),
    ('brand_missing', 'CANDIDATE_NOT_FOUND', 0), ('search_disabled', 'PAGE_ERROR', 0),
    ('next_stays', 'PAGE_ERROR', 1), ('invalid_id', 'PAGE_ERROR', 1)])
def test_category_failure_stops_before_any_upload(handoff, monkeypatch, variant, code, next_clicks):
    install_model(handoff, load_contracts(), monkeypatch, variant=variant)
    _, task = save_and_start(handoff)
    assert task['status'] == 'failed' and task['result']['stage'] == 'select_category', task
    assert task['result']['error']['code'] == code
    assert handoff.browser.evaluate('window.categoryModel.nextClicks') == next_clicks
    assert_no_platform_writes(handoff)


def test_cancel_after_next_stops_at_stage_boundary_without_upload(handoff, monkeypatch):
    install_model(handoff, load_contracts(), monkeypatch, cancel=True)
    _, task = save_and_start(handoff)
    assert task['status'] == 'cancelled'
    assert task['steps'][2]['name'] == 'select_category' and task['steps'][2]['status'] == 'ok'
    assert task['result']['error']['code'] == 'CANCELLED'
    assert handoff.browser.evaluate('window.categoryModel.nextClicks') == 1
    assert_no_platform_writes(handoff)


def test_verified_fixture_continues_after_real_category_handler(handoff, fixture_contracts, monkeypatch):
    install_model(handoff, fixture_contracts, monkeypatch)
    _, task = save_and_start(handoff)
    assert task['status'] == 'succeeded', task['error']
    # ⚠️ 阶段数**不要硬编码**（加一个阶段就要回去改一堆测试）。
    # 离线跑到 `readback` 就停（停在提交前），所以是 STAGE_ORDER 去掉 submit。
    ran = [step['name'] for step in task['steps']]
    assert ran == [name for name in STAGE_ORDER if name != 'submit'], ran
    # `save_draft` **默认 skipped**（未显式请求保存草稿），其余都必须是 ok。
    assert all(step['status'] in ('ok', 'skipped') for step in task['steps']), task['steps']
    others = [step['status'] for step in task['steps'] if step['name'] != 'save_draft']
    assert others == ['ok'] * len(others), task['steps']
    assert handoff.browser.evaluate('window.categoryModel.nextClicks') == 1
    assert len(handoff.uploads) == 5
    assert task['result']['data']['form_verification']['status'] == 'partial'
    assert handoff.browser.evaluate('window.submitCalls + window.draftCalls') == 0


@pytest.mark.parametrize('purpose,expected', [
    ('media', ['media.image_card']),
    ('detail', ['detail.editor', 'media.image_card']),
    ('sku', list(form_adapters.CUSTOM_KEYS + form_adapters.SKU_IMAGE_KEYS)),
    ('readback', ['sku.table_image', 'detail.editor'])])
def test_adapter_dependencies_are_scoped_to_actual_operation(item, purpose, expected):
    assert list(form_adapters.required_keys(item, purpose=purpose)) == expected
    blockers = form_adapters.adapter_blockers(item, load_contracts(), purpose=purpose)
    assert blockers == []


def test_unknown_adapter_purpose_is_explicit_failure(item):
    with pytest.raises(ValueError, match='未知控件用途'):
        form_adapters.config_for(item, load_contracts(), purpose='unchecked')


def test_unrelated_editor_evidence_does_not_block_media_configuration(item, fixture_contracts):
    payload = json.loads(json.dumps(fixture_contracts.selectors._payload))
    for entry in payload['selectors']:
        if entry['key'] in form_adapters.CUSTOM_KEYS or entry['key'] == 'detail.editor':
            entry['evidence'] = {'level': 'unknown', 'source': 'LOCAL_PENDING_EDITOR'}
    from taobao_publish.contracts import SelectorContract
    contracts = replace(fixture_contracts, selectors=SelectorContract(payload))
    config = form_adapters.config_for(item, contracts, purpose='media')
    assert set(config) == {'media.image_card'}
    assert form_adapters.adapter_blockers(item, contracts, purpose='sku')
    assert form_adapters.adapter_blockers(item, contracts, purpose='detail')


def test_orphan_sku_image_fails_before_any_upload_action(item, fixture_contracts, monkeypatch):
    item.images.sku.append('未关联的本地模型.jpg')
    opener = Mock(side_effect=AssertionError('不能先上传主图再发现规格图没有对应关系'))
    monkeypatch.setattr(stages, '_open_publish_page', opener)
    outcome = stages.stage_upload_images(stages.PipelineContext(
        item=item, dry_run=False, contracts=fixture_contracts))
    assert not outcome.ok and '未指定对应' in outcome.summary
    assert outcome.blockers[0].field == 'images.sku'
    opener.assert_not_called()


@pytest.mark.parametrize('stage', ['upload_images', 'fill_detail', 'fill_skus', 'readback'])
def test_stage_guard_stops_before_handler_or_page(item, stage, monkeypatch):
    from taobao_publish.authorization import WriteAuthorization
    action = Mock(side_effect=AssertionError('缺失证据不能开始阶段动作'))
    monkeypatch.setitem(stages.STAGE_HANDLERS, stage, replace(stages.STAGE_HANDLERS[stage], run=action))
    contracts = load_contracts()
    from taobao_publish.contracts import SelectorContract
    payload = json.loads(json.dumps(contracts.selectors._payload))
    key = {'upload_images':'media.image_card', 'fill_detail':'detail.editor',
           'fill_skus':'sku.custom_mode', 'readback':'detail.editor'}[stage]
    for entry in payload['selectors']:
        if entry['key'] == key:
            entry['evidence'] = {'level':'unknown','source':'LOCAL_UNCONFIRMED_CONTROL'}
    contracts = replace(contracts, selectors=SelectorContract(payload))
    ctx = stages.PipelineContext(item=item, dry_run=False, contracts=contracts, authorization=WriteAuthorization.for_form_filling())
    outcome = stages.run_stage(stage, ctx, index=3, total=10, steps=[]).outcome
    assert not outcome.ok and outcome.error_code == 'EVIDENCE_INSUFFICIENT'
    action.assert_not_called()

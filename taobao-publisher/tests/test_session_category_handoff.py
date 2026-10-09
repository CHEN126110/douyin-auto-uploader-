# -*- coding: utf-8 -*-
"""类目页是连接阶段的合法起点；全部使用隔离替身，不访问用户浏览器。"""
from dataclasses import replace
from unittest.mock import Mock

import pytest

from taobao_publish import cdp, page, stages
from taobao_publish.authorization import WriteAuthorization
from taobao_publish.cdp import SessionProbe
from taobao_publish.constants import STAGE_PRECHECK, STAGE_SESSION
from taobao_publish.models import ImageSet, PublishItem, SkuEntry, build_stage_plan
from taobao_publish.preflight import check_workbench_ready
from test_candidate_form_adapters import browser


REAL_OPEN_PUBLISH_PAGE = stages._open_publish_page


CATEGORY_URL = 'https://item.upload.taobao.com/sell/ai/category.htm'
FACTS = {
    'url': CATEGORY_URL, 'title': 'LOCAL_TEST_ONLY',
    'has_workbench_root': False, 'has_category_page': True,
    'has_blocking_overlay': False, 'has_submit_control': False,
    'has_save_draft_control': False,
}


@pytest.fixture
def session_case(monkeypatch):
    probe = SessionProbe(cdp_list_url='http://127.0.0.1:9334/json/list', target_count=1,
                         publish_target_found=True, taobao_target_found=True,
                         current_url=CATEGORY_URL)
    monkeypatch.setattr(stages, 'probe_session', Mock(return_value=probe))
    target = {'type': 'page', 'url': CATEGORY_URL, 'webSocketDebuggerUrl': 'ws://local-test-only'}
    monkeypatch.setattr(cdp, 'list_targets', Mock(return_value=[target]))
    client = Mock()
    client.__enter__ = Mock(return_value=client)
    def close_context(*_):
        client.close()
        return False
    client.__exit__ = Mock(side_effect=close_context)
    client.health_check.return_value = True
    client.evaluate.return_value = dict(FACTS)
    connect = Mock(return_value=client)
    monkeypatch.setattr(page.PageClient, 'connect', connect)
    wait = Mock(side_effect=AssertionError('选择类目前不允许等待填写页'))
    monkeypatch.setattr(page, 'wait_for_publish_form', wait)
    ctx = stages.PipelineContext(item=PublishItem(record_id=1, record_name='LOCAL_TEST_ONLY'),
                                 dry_run=False, authorization=WriteAuthorization.for_form_filling())
    ctx.scratch['stage_plan'] = build_stage_plan(include_submit=False)
    return ctx, client, connect, wait


@pytest.mark.parametrize('on_form', [False, True])
def test_session_accepts_category_or_form_without_waiting_for_form(session_case, on_form):
    ctx, client, _, wait = session_case
    client.evaluate.return_value.update(has_workbench_root=on_form, has_category_page=not on_form)
    outcome = stages.stage_session(ctx)
    assert outcome.ok
    snapshot = ctx.scratch['snapshot']
    assert snapshot.has_workbench_root is on_form
    assert snapshot.has_category_page is not on_form
    assert not check_workbench_ready(snapshot, require_write=True)
    wait.assert_not_called()
    client.health_check.assert_called_once_with(timeout=6.0)
    client.close.assert_called_once()


def test_category_session_hands_off_to_precheck_then_category(session_case, monkeypatch, tmp_path):
    from PIL import Image
    ctx, _, _, wait = session_case
    images = []
    for index in range(5):
        path = tmp_path / ('model-%s.jpg' % index)
        Image.new('RGB', (800, 800), 'white').save(path)
        images.append(str(path))
    ctx.item = PublishItem(record_id=1, record_name='LOCAL_TEST_ONLY',
        title='本地模型女款纯色中筒袜秋冬柔软舒适袜子', images=ImageSet(main=images),
        skus=[SkuEntry(spec_values={'颜色分类': '黑色'}, price=9.9, stock=100)])
    visits = []
    def category(context):
        assert context.scratch['snapshot'].has_category_page is True
        visits.append('select_category')
        return stages.StageOutcome(ok=True, summary='本地类目处理替身')
    monkeypatch.setitem(stages.STAGE_HANDLERS, 'select_category',
                        stages.StageHandlerSpec(run=category, mutates_page=True))
    for index, stage in enumerate([STAGE_SESSION, STAGE_PRECHECK, 'select_category']):
        result = stages.run_stage(stage, ctx, index=index, total=10, steps=[])
        assert result.outcome.ok, result.outcome.summary
    assert visits == ['select_category']
    wait.assert_not_called()


def test_session_page_failure_is_terminal_at_session(session_case):
    ctx, client, _, wait = session_case
    client.evaluate.side_effect = page.PageError('模型页面读取超时')
    outcome = stages.stage_session(ctx)
    assert not outcome.ok and outcome.status == 'failed'
    assert outcome.error_code == 'PAGE_ERROR'
    assert '模型页面读取超时' in outcome.summary
    assert outcome.blockers[0].field == 'page.session'
    assert ctx.scratch['snapshot'].has_category_page is None
    wait.assert_not_called()
    client.close.assert_called_once()


def test_session_unexpected_failure_cannot_return_success(session_case):
    ctx, client, _, _ = session_case
    client.evaluate.side_effect = RuntimeError('不得回显的原始内容')
    outcome = stages.stage_session(ctx)
    assert not outcome.ok
    assert outcome.error_code == 'PLATFORM_ERROR'
    assert 'RuntimeError' in outcome.summary
    assert '不得回显的原始内容' not in outcome.summary


def test_renderer_failure_keeps_its_code_and_closes_connection(session_case):
    ctx, client, _, wait = session_case
    client.health_check.return_value = False
    outcome = stages.stage_session(ctx)
    assert not outcome.ok and outcome.error_code == 'RENDERER_HUNG'
    assert outcome.blockers[0].field == 'page.renderer'
    client.evaluate.assert_not_called()
    wait.assert_not_called()
    client.close.assert_called_once()


@pytest.mark.parametrize('facts', [None, [], {}, {'has_category_page': True},
    {**FACTS, 'has_category_page': None}, {**FACTS, 'has_blocking_overlay': 'false'},
    {**FACTS, 'has_workbench_root': 0}, {**FACTS, 'has_submit_control': 1}])
def test_missing_or_nonboolean_page_facts_cannot_be_success(session_case, facts):
    ctx, client, _, wait = session_case
    client.evaluate.return_value = facts
    outcome = stages.stage_session(ctx)
    assert not outcome.ok and outcome.error_code == 'PAGE_ERROR'
    assert ctx.scratch['snapshot'].has_blocking_overlay is None
    wait.assert_not_called()


def test_injected_probe_does_not_connect_a_real_browser(session_case):
    ctx, _, connect, wait = session_case
    ctx.session_probe = stages.probe_session
    assert stages.stage_session(ctx).ok
    connect.assert_not_called()
    wait.assert_not_called()


def test_probe_failure_does_not_open_a_page(session_case):
    from taobao_publish.errors import Blocker
    ctx, _, connect, _ = session_case
    stages.probe_session.return_value.blockers = [Blocker(code='CDP_UNREACHABLE', detail='本地模型断开')]
    outcome = stages.stage_session(ctx)
    assert not outcome.ok and outcome.error_code == 'CDP_UNREACHABLE'
    connect.assert_not_called()


def test_precheck_defers_gaps_with_explicit_later_failure(session_case, monkeypatch):
    from taobao_publish.preflight import PreflightResult
    ctx, _, _, _ = session_case
    from taobao_publish.contracts import load_contracts, SelectorContract
    from taobao_publish.form_adapters import RUNTIME_GUARDED_KEYS
    import copy
    ctx.item = replace(ctx.item, sku_mode='custom',
                       skus=[SkuEntry(spec_values={'颜色分类': '本地规格'}, image_path='model.jpg')],
                       images=ImageSet(sku=['model.jpg'], detail=['detail.jpg']))
    contracts = load_contracts()
    payload = copy.deepcopy(contracts.selectors._payload)
    for entry in payload['selectors']:
        if entry['key'] in RUNTIME_GUARDED_KEYS or entry['key'] == 'media.image_card':
            entry['evidence'] = {'level': 'unknown', 'source': 'LOCAL_NEGATIVE_MODEL'}
    ctx.contracts = replace(contracts, selectors=SelectorContract(payload))
    monkeypatch.setattr(stages, 'run_preflight', Mock(return_value=PreflightResult(ready=True)))
    outcome = stages.stage_precheck(ctx)
    assert outcome.ok and not outcome.blockers
    deferred = outcome.data['deferred_adapter_blockers']
    assert len({b['field'] for entries in deferred.values() for b in entries}) == 8
    failures = [stages._stage_adapter_guard(ctx, stage) for stage in deferred]
    details = '；'.join(failure.summary for failure in failures)
    assert '自定义规格' in details
    assert 'SKU 图片' in details
    assert '宝贝详情' in details
    assert '图片空间卡片' in details


def test_form_filling_still_waits_for_rendered_form(session_case, monkeypatch):
    ctx, client, _, _ = session_case
    wait = Mock(return_value=[])
    monkeypatch.setattr(page, 'wait_for_publish_form', wait)
    with pytest.raises(page.PageError, match='填写页仍然没有渲染'):
        stages._open_publish_page(ctx)
    wait.assert_called_once_with(client)
    client.close.assert_called_once()


@pytest.mark.parametrize('on_form', [False, True])
def test_real_local_dom_session_reads_category_or_form(browser, session_case, monkeypatch, on_form):
    """独立 file: 浏览器执行真实页面表达式；目标发现替换为本地边界。"""
    ctx, _, _, wait = session_case
    assert browser.evaluate('location.protocol') == 'file:'
    markup = '<div class="sell-component-info-wrapper-wrap">LOCAL_FORM</div>' if on_form else \
        '<input placeholder="可输入产品名称" style="width:200px;height:40px">'
    import json
    browser.evaluate('document.body.innerHTML = %s' % json.dumps(markup))
    monkeypatch.setattr(page.PageClient, 'connect', Mock(return_value=browser))
    monkeypatch.setattr(stages, '_open_publish_page', REAL_OPEN_PUBLISH_PAGE)
    outcome = stages.stage_session(ctx)
    assert outcome.ok, outcome.summary
    snapshot = ctx.scratch['snapshot']
    assert snapshot.url.startswith('file:')
    assert snapshot.has_workbench_root is on_form
    assert snapshot.has_category_page is not on_form
    assert snapshot.has_blocking_overlay is False
    wait.assert_not_called()

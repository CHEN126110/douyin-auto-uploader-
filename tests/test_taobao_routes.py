# -*- coding: utf-8 -*-
"""淘宝发布接口（``src/sidecar/taobao_routes.py``，``/api/taobao/*``）：真实的 Blueprint + 真实的服务对象 + 真实的账户门禁。

后台线程换成只记录参数不启动的替身；浏览器、淘宝模块（就绪度 / 资料检查 / 导出）、商品表都是假件。
资料检查 / 导出的请求体校验矩阵在 ``test_taobao_desktop_api.py`` 里用真实离线模块测过，这里只钉响应映射和依赖的传递。
"""
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))

from src.sidecar import taobao_routes  # noqa: E402
from taobao_test_support import make_app, make_record_model, make_registry, make_row, make_service  # noqa: E402

ACCOUNT = 'taobao-test'
URL = 'http://127.0.0.1:9501/json/list'
START, START_ALL = '/api/taobao/publish/start', '/api/taobao/publish/start-all'


def build(rows=None, *, registry=None, require_product_revision=None, **service_overrides):
    workers = []

    class Worker:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            workers.append(self)

        def start(self):
            self.kwargs['started'] = True

    rows = rows if rows is not None else {7: make_row(7), 8: make_row(8)}
    service = make_service(record_model=make_record_model(rows), registry=registry, **service_overrides)
    # 默认：有可用的淘宝浏览器；翻译用真实的（本地契约）
    service.cdp_list_url = Mock(return_value=URL)
    service.ensure_fill_browser = Mock(return_value=URL)
    revision = require_product_revision or Mock(return_value=None)
    app, accounts = make_app(service, require_product_revision=revision)
    return SimpleNamespace(service=service, client=app.test_client(), workers=workers, revision=revision, accounts=accounts,
                           Worker=Worker, app=app)


@pytest.fixture
def env(monkeypatch):
    holder = {}

    def make(*args, **kwargs):
        case = build(*args, **kwargs)
        monkeypatch.setattr(taobao_routes, 'threading', SimpleNamespace(Thread=case.Worker))
        holder['case'] = case
        return case
    return make


def body(**extra):
    base = {'record_id': 7, 'platform': 'taobao', 'account_profile': ACCOUNT}
    base.update(extra)
    return base


def fill(**extra):
    return body(fill_only=True, dry_run=False, stop_before_submit=True, product={'title': '棉袜', 'category_keyword': '中筒袜'}, **extra)


# ------------------------------------------------------------------------------------------ 就绪度 / 资料检查 / 导出
def fake_desktop(**members):
    return SimpleNamespace(**members)


def test_readiness_returns_whatever_the_taobao_module_reports(env):
    case = env()
    case.service.load_desktop = lambda: fake_desktop(desktop_readiness=lambda: {'ready': True, 'platform': 'taobao'})
    response = case.client.get('/api/taobao/readiness')
    assert response.status_code == 200 and response.get_json() == {'success': True, 'data': {'ready': True, 'platform': 'taobao'}}


@pytest.mark.parametrize('error', [ImportError('缺依赖'), OSError('磁盘'), ValueError('契约坏了')])
def test_readiness_failures_are_503_with_the_reason(env, error):
    case = env()

    def broken():
        raise error
    case.service.load_desktop = lambda: fake_desktop(desktop_readiness=broken)
    response = case.client.get('/api/taobao/readiness')
    assert response.status_code == 503 and response.get_json() == {'success': False, 'msg': '淘宝模块不可用：%s' % error}


def test_readiness_does_not_swallow_unexpected_errors(env):
    case = env()

    def broken():
        raise RuntimeError('未预期')
    case.service.load_desktop = lambda: fake_desktop(desktop_readiness=broken)
    with pytest.raises(RuntimeError, match='未预期'):
        case.client.get('/api/taobao/readiness')


@pytest.mark.parametrize('route,member,message', [('prepare', 'prepare_product', '淘宝资料检查完成，尚未向平台发布'),
                                                   ('export', 'export_packet', '本地淘宝资料包已生成，尚未向平台发布')])
def test_prepare_and_export_hand_the_record_and_overrides_to_the_module(env, route, member, message):
    case = env()
    calls = []

    def run(record, overrides, *extra):
        calls.append((record['id'], overrides, extra))
        return {'ok': True}
    case.service.load_desktop = lambda: fake_desktop(**{member: run})
    response = case.client.post('/api/taobao/publish/' + route, json=body(overrides={'title': 'x'}))
    assert response.status_code == 200
    assert response.get_json() == {'success': True, 'msg': message, 'data': {'ok': True, 'account_profile': ACCOUNT}}
    expected_extra = (case.service._resolve_data_file('taobao_publish_packets'),) if route == 'export' else ()
    assert calls == [(7, {'title': 'x'}, expected_extra)]


@pytest.mark.parametrize('route,member,prefix', [('prepare', 'prepare_product', '淘宝资料检查失败：'),
                                                 ('export', 'export_packet', '淘宝资料包生成失败：')])
@pytest.mark.parametrize('error,status', [(ValueError('资料不合法'), 400), (ImportError('缺依赖'), 503), (OSError('磁盘'), 503)])
def test_prepare_and_export_map_errors_to_statuses(env, route, member, prefix, error, status):
    case = env()

    def broken(*_args):
        raise error
    case.service.load_desktop = lambda: fake_desktop(**{member: broken})
    response = case.client.post('/api/taobao/publish/' + route, json=body())
    assert response.status_code == status
    assert response.get_json()['msg'] == (str(error) if status == 400 else prefix + str(error))


@pytest.mark.parametrize('route', ['prepare', 'export'])
@pytest.mark.parametrize('payload,status', [
    ([1], 400), ({'record_id': 7, 'extra': 1}, 400), ({'record_id': 7, 'platform': 'douyin'}, 400),
    ({'record_id': True}, 400), ({'record_id': '7'}, 400), ({'record_id': 0}, 400), ({}, 400),
    ({'record_id': 7, 'overrides': []}, 400), ({'record_id': 99}, 404),
    ({'record_id': 7, 'account_profile': 'other'}, 409), ({'record_id': 7, 'account_profile': ' '}, 400),
])
def test_prepare_and_export_refuse_bad_requests_before_touching_the_module(env, route, payload, status):
    case = env()
    case.service.load_desktop = Mock(side_effect=AssertionError('被拒绝的请求不得加载淘宝模块'))
    assert case.client.post('/api/taobao/publish/' + route, json=payload).status_code == status


@pytest.mark.parametrize('route', ['prepare', 'export'])
def test_prepare_and_export_are_blocked_for_a_non_taobao_account(env, route):
    case = env(registry=make_registry(platform='douyin'))
    case.service.load_desktop = Mock(side_effect=AssertionError('不该走到这里'))
    response = case.client.post('/api/taobao/publish/' + route, json=body())
    assert response.status_code == 409 and response.get_json()['code'] == 'ACCOUNT_PLATFORM_MISMATCH'


# ------------------------------------------------------------------------------------------ 启动：请求校验
@pytest.mark.parametrize('payload,status,message', [
    ([1], 400, '请求必须是 JSON 对象'),
    (body(platform='douyin'), 400, '淘宝接口只能处理淘宝商品'),
    (body(unknown=1), 400, '请求包含不支持的参数'),
    (body(dry_run='false'), 400, 'dry_run 必须是布尔值'),
    (body(listing_mode='上架到月球'), 400, 'listing_mode 只能是 立刻上架、定时上架、放入仓库 之一'),
    (body(record_id=None), 400, '请选择有效的商品编号'),
    (body(record_id=True), 400, '请选择有效的商品编号'),
    (body(record_id='7'), 400, '请选择有效的商品编号'),
    (body(record_id=0), 400, '请选择有效的商品编号'),
    (body(record_id=-1), 400, '请选择有效的商品编号'),
    (body(fill_only=True), 400, '填写任务必须真实填写并在提交前停止'),                     # dry_run 默认 True
    (body(fill_only=True, dry_run=False, stop_before_submit=False), 400, '填写任务必须真实填写并在提交前停止'),
    (body(record_id=99), 404, '商品不存在，请刷新商品列表'),
    (body(product=[]), 400, 'product 必须是 JSON 对象'),
    (body(product={'title': ''}), 400, '宝贝标题不能为空'),
    (body(product={'title': '袜' * 31}), 400, None),
    (body(product={'skus': [{'price': -1}]}), 400, '第1条SKU的price超出有效范围'),
])
def test_bad_requests_are_refused_without_creating_anything(env, payload, status, message):
    case = env()
    response = case.client.post(START, json=payload)
    assert response.status_code == status
    result = response.get_json()
    assert result['success'] is False
    if message:
        assert result['msg'] == message
    assert case.service.tasks == {} and case.workers == []
    case.service.ensure_fill_browser.assert_not_called()
    case.service.cdp_list_url.assert_not_called()


def test_a_body_that_is_not_json_is_treated_as_empty_and_asks_for_a_record(env):
    case = env()
    response = case.client.post(START, data='not json', content_type='text/plain')
    assert response.status_code == 400 and response.get_json()['msg'] == '请选择有效的商品编号'


def test_platform_gate_runs_before_the_record_is_read(env):
    case = env(registry=make_registry(platform='douyin'))
    case.service._record_model.get_by_id = Mock(side_effect=AssertionError('平台对不上就不该读商品'))
    response = case.client.post(START, json=body())
    assert response.status_code == 409 and response.get_json()['code'] == 'ACCOUNT_PLATFORM_MISMATCH'


def test_stale_account_snapshot_is_refused(env):
    case = env()
    response = case.client.post(START, json=body(account_profile='another-00000000'))
    assert response.status_code == 409 and response.get_json()['code'] == 'ACCOUNT_CHANGED'


def test_expected_revision_is_checked_against_the_stored_row_and_its_error_is_returned(env):
    revision = Mock(return_value=({'success': False, 'msg': '商品资料已改变'}, 409))
    case = env(require_product_revision=revision)
    response = case.client.post(START, json=body(expected_record_revision='a' * 64))
    assert response.status_code == 409 and response.get_json()['msg'] == '商品资料已改变'
    (row, expected), _kwargs = revision.call_args
    assert row['id'] == 7 and expected == 'a' * 64
    assert case.service.tasks == {} and case.workers == []


def test_revision_is_not_checked_when_the_request_does_not_carry_one(env):
    case = env()
    assert case.client.post(START, json=body()).status_code == 200
    case.revision.assert_not_called()


# ------------------------------------------------------------------------------------------ 启动：浏览器
@pytest.mark.parametrize('error', [OSError('无法启动'), ValueError('当前账户不属于淘宝'), RuntimeError('浏览器未能启动')])
def test_fill_task_reports_a_browser_that_cannot_be_started(env, error):
    case = env()
    case.service.ensure_fill_browser = Mock(side_effect=error)
    response = case.client.post(START, json=fill())
    assert response.status_code == 503 and response.get_json()['msg'] == '启动淘宝浏览器失败：%s' % error
    assert case.service.tasks == {} and case.workers == []


def test_unexpected_browser_errors_are_not_disguised(env):
    case = env()
    case.service.ensure_fill_browser = Mock(side_effect=KeyError('profile'))
    with pytest.raises(KeyError):
        case.client.post(START, json=fill())


def test_fill_task_is_refused_while_a_publish_task_is_running_and_the_browser_is_left_alone():
    """账户切换互斥：有任务在跑，填写任务不能去动浏览器。"""
    running = {'value': True}
    workers = []
    service = make_service(has_running_publish_tasks=lambda: running['value'], record_model=make_record_model({7: make_row(7)}))
    service.ensure_fill_browser = Mock(return_value=URL)
    app, _accounts = make_app(service)
    response = app.test_client().post(START, json=fill())
    assert response.status_code == 409 and '发布任务运行中' in response.get_json()['msg']
    service.ensure_fill_browser.assert_not_called()
    assert service.tasks == {} and workers == []


def test_non_fill_task_needs_a_taobao_browser_of_the_current_account(env):
    case = env()
    case.service.cdp_list_url = Mock(return_value='')
    response = case.client.post(START, json=body())
    assert response.status_code == 200                       # 统一的 api_error 结构：HTTP 200 + success False
    assert response.get_json() == {'success': False, 'msg': '没有找到淘宝账户的浏览器；请先在账户菜单里登录淘宝店铺', 'data': None}
    assert case.service.tasks == {} and case.workers == []
    case.service.ensure_fill_browser.assert_not_called()


# ------------------------------------------------------------------------------------------ 启动：创建任务
def test_dry_run_task_is_created_and_started(env):
    case = env()
    response = case.client.post(START, json=body())
    assert response.status_code == 200
    data = response.get_json()
    assert data['success'] is True and data['msg'] == '淘宝校对（dry-run，不写平台）任务已启动'
    task_id = data['data']['task_id']
    assert data['data'] == {'task_id': task_id, 'dry_run': True, 'stop_before_submit': True}
    task = case.service.tasks[task_id]
    assert task == dict(task, task_id=task_id, platform='taobao', account_profile=ACCOUNT, record_id=7, record_name='商品7',
                        status='pending', progress=0, message='任务已创建', current_step=None, steps=[], error=None, blockers=[],
                        result=None, dry_run=True, stop_before_submit=True, fill_only=False, save_draft=False, listing_mode='',
                        publish_confirmed=False, started_at=None, finished_at=None)
    assert task['created_at']
    (worker,) = case.workers
    assert worker.kwargs['target'] == case.service.run_publish_task and worker.kwargs['daemon'] is True
    assert worker.kwargs['started'] is True
    task_arg, row, request, options = worker.kwargs['args']
    assert task_arg == task_id and row['id'] == 7 and request == {'record_id': 7, 'record_name': '商品7'}
    assert options == {'dry_run': True, 'stop_before_submit': True, 'fill_only': False, 'save_draft': False, 'listing_mode': '',
                       'cdp_list_url': URL}
    case.service.ensure_fill_browser.assert_not_called()


def test_write_task_message_says_it_writes(env):
    case = env()
    response = case.client.post(START, json=fill(listing_mode=' 定时上架 ', save_draft=True))
    assert response.status_code == 200 and response.get_json()['msg'] == '淘宝写入任务已启动'
    (worker,) = case.workers
    options = worker.kwargs['args'][3]
    assert options == {'dry_run': False, 'stop_before_submit': True, 'fill_only': True, 'save_draft': True,
                       'listing_mode': '定时上架', 'cdp_list_url': URL}
    task = next(iter(case.service.tasks.values()))
    assert (task['fill_only'], task['listing_mode'], task['save_draft']) == (True, '定时上架', True)
    case.service.ensure_fill_browser.assert_called_once_with()
    case.service.cdp_list_url.assert_not_called()


def test_ui_product_is_translated_into_the_pipeline_request(env):
    case = env()
    case.client.post(START, json=fill())
    (worker,) = case.workers
    request = worker.kwargs['args'][2]
    assert request['record_id'] == 7 and request['record_name'] == '商品7'
    assert request['title'] == '棉袜' and request['category'] == {'search_keyword': '中筒袜'}


def test_translation_gets_the_stored_row_so_images_can_be_checked_against_it(env):
    case = env()
    calls = []

    def translate(product, record=None):
        calls.append((product, record))
        return {'title': '翻译后'}
    case.service.product_request_payload = translate
    case.client.post(START, json=fill())
    assert calls[0][0] == {'title': '棉袜', 'category_keyword': '中筒袜'} and calls[0][1]['id'] == 7
    assert case.workers[0].kwargs['args'][2] == {'title': '翻译后', 'record_id': 7, 'record_name': '商品7'}


def test_task_ids_are_distinct_and_the_task_table_keeps_them_separately(env):
    case = env()
    first = case.client.post(START, json=body()).get_json()['data']['task_id']
    case.service.tasks[first]['status'] = 'succeeded'
    second = case.client.post(START, json=body()).get_json()['data']['task_id']
    assert first != second and set(case.service.tasks) == {first, second}


@pytest.mark.parametrize('status', ['pending', 'running'])
def test_only_one_unfinished_task_at_a_time(env, status):
    case = env()
    case.service.tasks['busy'] = {'task_id': 'busy', 'status': status, 'record_name': '占着的任务'}
    response = case.client.post(START, json=body())
    assert response.status_code == 409
    assert response.get_json()['msg'] == '已有一个淘宝发布任务在进行中（busy，占着的任务），请等它结束后再发起'
    assert list(case.service.tasks) == ['busy'] and case.workers == []


@pytest.mark.parametrize('status', ['succeeded', 'failed', 'cancelled'])
def test_finished_tasks_do_not_block(env, status):
    case = env()
    case.service.tasks['old'] = {'task_id': 'old', 'status': status}
    assert case.client.post(START, json=body()).status_code == 200 and len(case.service.tasks) == 2


# ------------------------------------------------------------------------------------------ 批量发布
def test_batch_validation_mirrors_the_single_start(env):
    case = env()
    for payload, status in (([1], 400), ({'platform': 'douyin'}, 400), ({'unknown': 1}, 400), ({'dry_run': 'no'}, 400),
                            ({'account_profile': 'other'}, 409), ({'account_profile': ' '}, 400)):
        assert case.client.post(START_ALL, json=payload).status_code == status, payload
    assert case.service.tasks == {} and case.workers == []
    case.service.ensure_fill_browser.assert_not_called()


def test_batch_needs_the_account_to_be_a_taobao_one(env):
    case = env(registry=make_registry(platform='douyin'))
    response = case.client.post(START_ALL, json={})
    assert response.status_code == 409 and response.get_json()['code'] == 'ACCOUNT_PLATFORM_MISMATCH'


def test_batch_with_no_pending_records_says_so(env):
    case = env(rows={7: make_row(7, status=1)})
    response = case.client.post(START_ALL, json={})
    assert response.status_code == 200
    assert response.get_json() == {'success': False, 'msg': '没有待上传的商品（status=0）', 'data': None}
    case.service.ensure_fill_browser.assert_not_called()


def test_batch_reports_a_browser_that_cannot_be_started(env):
    case = env()
    case.service.ensure_fill_browser = Mock(side_effect=RuntimeError('Chrome启动失败'))
    response = case.client.post(START_ALL, json={})
    assert response.status_code == 503 and response.get_json()['msg'] == '启动淘宝浏览器失败：Chrome启动失败'
    assert case.service.tasks == {} and case.workers == []


def test_batch_task_is_created_and_started(env):
    case = env()
    response = case.client.post(START_ALL, json={'account_profile': ACCOUNT, 'fill_only': True, 'dry_run': False,
                                                  'listing_mode': '放入仓库', 'save_draft': True})
    assert response.status_code == 200
    data = response.get_json()
    task_id = data['data']['task_id']
    assert data['msg'] == '已启动淘宝批量发布（2个商品）'
    assert data['data'] == {'task_id': task_id, 'count': 2, 'dry_run': False, 'stop_before_submit': True}
    task = case.service.tasks[task_id]
    assert task == dict(task, task_id=task_id, platform='taobao', account_profile=ACCOUNT, record_id=None, record_name='批量(2个)',
                        status='pending', progress=0, message='批量上传 2 个商品', current_step=None, steps=[], error=None,
                        blockers=[], result=None, dry_run=False, stop_before_submit=True, fill_only=True, publish_confirmed=False,
                        cancelled=False, started_at=None, finished_at=None)
    (worker,) = case.workers
    assert worker.kwargs['target'] == case.service.run_publish_batch_task and worker.kwargs['daemon'] is True
    assert worker.kwargs['args'] == (task_id, {'dry_run': False, 'stop_before_submit': True, 'fill_only': True, 'save_draft': True,
                                               'listing_mode': '放入仓库', 'account_profile': ACCOUNT, 'cdp_list_url': URL})
    case.service.ensure_fill_browser.assert_called_once_with()


def test_batch_without_account_snapshot_records_an_empty_account(env):
    case = env()
    case.client.post(START_ALL, json={})
    task = next(iter(case.service.tasks.values()))
    assert task['account_profile'] == '' and case.workers[0].kwargs['args'][1]['account_profile'] == ''


# 批量发布的准入：与单个发布同一套规则。批量也要拉起账户的素材中心浏览器、也驱动同一个浏览器页面。
def test_batch_is_refused_while_a_publish_task_is_running_and_the_browser_is_left_alone():
    """账户切换互斥：有任务在跑，批量任务不能去动浏览器（与单品填写任务同一道门）。"""
    service = make_service(has_running_publish_tasks=lambda: True, record_model=make_record_model({7: make_row(7)}))
    service.ensure_fill_browser = Mock(return_value=URL)
    app, _accounts = make_app(service)
    response = app.test_client().post(START_ALL, json={'account_profile': ACCOUNT})
    assert response.status_code == 409 and '发布任务运行中' in response.get_json()['msg']
    service.ensure_fill_browser.assert_not_called()
    assert service.tasks == {}


@pytest.mark.parametrize('status', ['pending', 'running'])
def test_batch_allows_only_one_unfinished_task_at_a_time(env, status):
    """流水线驱动的是同一个浏览器页面：两个任务同时跑会互相导航、交叉写表单，各自还在按自己的期望值回读。"""
    case = env()
    case.service.tasks['busy'] = {'task_id': 'busy', 'status': status, 'record_name': '占着的任务'}
    response = case.client.post(START_ALL, json={'account_profile': ACCOUNT})
    assert response.status_code == 409
    assert response.get_json() == {'success': False, 'msg': '已有一个淘宝发布任务在进行中（busy，占着的任务），请等它结束后再发起'}
    assert list(case.service.tasks) == ['busy'] and case.workers == []


@pytest.mark.parametrize('status', ['succeeded', 'failed', 'cancelled'])
def test_finished_tasks_do_not_block_a_batch(env, status):
    case = env()
    case.service.tasks['old'] = {'task_id': 'old', 'status': status}
    response = case.client.post(START_ALL, json={'account_profile': ACCOUNT})
    assert response.status_code == 200 and len(case.service.tasks) == 2 and len(case.workers) == 1


def test_a_started_batch_blocks_the_next_batch_and_the_next_single_task(env):
    case = env()
    first = case.client.post(START_ALL, json={'account_profile': ACCOUNT}).get_json()['data']['task_id']
    for route, payload in ((START_ALL, {'account_profile': ACCOUNT}), (START, body())):
        response = case.client.post(route, json=payload)
        assert response.status_code == 409, route
        assert response.get_json()['msg'] == '已有一个淘宝发布任务在进行中（%s，批量(2个)），请等它结束后再发起' % first
    assert list(case.service.tasks) == [first] and len(case.workers) == 1


# ------------------------------------------------------------------------------------------ 进度 / 取消 / 列表
def test_status_returns_a_copy_of_the_task(env):
    case = env()
    case.service.tasks['t'] = {'task_id': 't', 'status': 'running', 'steps': []}
    response = case.client.get('/api/taobao/publish/status/t')
    assert response.status_code == 200 and response.get_json()['data'] == {'task_id': 't', 'status': 'running', 'steps': []}
    case.service.tasks['t']['status'] = 'failed'
    assert response.get_json()['data']['status'] == 'running'


def test_status_of_an_unknown_task_is_404(env):
    case = env()
    response = case.client.get('/api/taobao/publish/status/nope')
    assert response.status_code == 404 and response.get_json() == {'success': False, 'msg': '任务不存在，请重新发起'}


@pytest.mark.parametrize('status', ['pending', 'running'])
def test_cancel_only_requests_it_and_does_not_claim_the_worker_stopped(env, status):
    case = env()
    case.service.tasks['t'] = {'task_id': 't', 'status': status}
    response = case.client.post('/api/taobao/publish/cancel/t')
    assert response.status_code == 200
    assert response.get_json()['data'] == {'task_id': 't', 'status': status}
    assert '阶段边界' in response.get_json()['msg']
    assert case.service.tasks['t']['cancelled'] is True and case.service.tasks['t']['status'] == status
    assert case.service.tasks['t']['message'] == '已请求取消，将在阶段边界停止'


@pytest.mark.parametrize('status', ['succeeded', 'failed', 'cancelled'])
def test_cancel_of_a_finished_task_changes_nothing(env, status):
    case = env()
    case.service.tasks['t'] = {'task_id': 't', 'status': status}
    response = case.client.post('/api/taobao/publish/cancel/t')
    assert response.status_code == 200 and response.get_json()['msg'] == '任务已结束，无需取消'
    assert case.service.tasks['t'] == {'task_id': 't', 'status': status}


def test_cancel_of_an_unknown_task_is_404(env):
    case = env()
    response = case.client.post('/api/taobao/publish/cancel/nope')
    assert response.status_code == 404 and response.get_json() == {'success': False, 'msg': '任务不存在'}


def test_task_list_is_newest_first_and_made_of_copies(env):
    case = env()
    case.service.tasks.update({
        'a': {'task_id': 'a', 'created_at': '2026-10-01T10:00:00'},
        'b': {'task_id': 'b', 'created_at': '2026-10-03T10:00:00'},
        'c': {'task_id': 'c', 'created_at': '2026-10-02T10:00:00'},
        'd': {'task_id': 'd'},
    })
    response = case.client.get('/api/taobao/publish/tasks')
    data = response.get_json()['data']
    assert data['count'] == 4 and [t['task_id'] for t in data['tasks']] == ['b', 'c', 'a', 'd']
    case.service.tasks['b']['task_id'] = 'changed'
    assert data['tasks'][0]['task_id'] == 'b'


def test_task_list_of_nothing_is_empty(env):
    case = env()
    assert case.client.get('/api/taobao/publish/tasks').get_json()['data'] == {'count': 0, 'tasks': []}

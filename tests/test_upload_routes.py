# -*- coding: utf-8 -*-
"""抖店上传接口（``upload_routes.create_upload_blueprint``）的直接测试（2026-10-21 从 app.py 搬出）。

真实的 Blueprint + 真实的 ``UploadService``（依赖全是 ``tests/upload_test_support.py`` 里的剧本替身）；账户门禁用一个假件
（平台门禁本身由 ``test_shop_platform_api.py`` 用真实的 ``ShopAccountGuard`` 测过）。后台线程换成只记录调度、不执行的假线程，
所以这里没有任何浏览器、数据库、网络、真线程。
"""
import sys
from functools import wraps
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from flask import Flask

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.sidecar import upload_routes  # noqa: E402
from src.sidecar.upload_routes import create_upload_blueprint  # noqa: E402
from upload_test_support import World, make_record  # noqa: E402


class Gate:
    """账户门禁的假件：记录谁进了账户锁、平台门禁被问了什么；``platform_error`` 非空时门禁拒绝。"""

    def __init__(self):
        self.lock_entries = 0
        self.platform_calls = []
        self.platform_error = None
        self.profile = 'shop-a'

    def with_lock(self, func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            self.lock_entries += 1
            return func(*args, **kwargs)
        return wrapper

    def require_publish_platform(self, platform, account_profile=None):
        self.platform_calls.append((platform, account_profile))
        return self.platform_error

    def active_account(self):
        return {'profile_name': self.profile, 'platform': 'douyin'}


class FakeThread:
    started = []

    def __init__(self, target, args, daemon):
        self.target, self.args, self.daemon = target, args, daemon

    def start(self):
        FakeThread.started.append(self)


@pytest.fixture
def api(tmp_path, monkeypatch):
    FakeThread.started = []
    monkeypatch.setattr(upload_routes, 'threading', SimpleNamespace(Thread=FakeThread))
    records = [make_record(7, name='白袜_货号_x_商品七', __data__={'id': 7, 'title': 't'}),
               make_record(8, name='', __data__={'id': 8}),
               make_record(9, name='已发布', status=1)]
    world = World(tmp_path, records=records)
    gate = Gate()
    revision = Mock(return_value=None)
    app = Flask('upload-routes-test')
    app.config.update(TESTING=True)
    app.register_blueprint(create_upload_blueprint(
        service=world.service, accounts=gate, record_model=world.records, require_product_revision=revision))
    return SimpleNamespace(client=app.test_client(), world=world, service=world.service, gate=gate, revision=revision,
                           threads=FakeThread.started)


def post(api, route, body=None, **kwargs):
    return api.client.post(route, json=body if body is not None else {}, **kwargs)


# ============================================================================================ /api/upload/start
def test_start_rejects_other_platforms_and_non_object_bodies(api):
    for body in ({'platform': 'taobao'}, ['not', 'an', 'object']):
        response = post(api, '/api/upload/start', body)
        assert response.status_code == 400 and '该接口仅用于抖音发布' in response.get_json()['msg']
    assert api.service.tasks == {} and api.threads == []


def test_start_returns_the_platform_gates_refusal_untouched(api):
    api.gate.platform_error = ({'success': False, 'msg': '当前账户是淘宝'}, 409)
    response = post(api, '/api/upload/start', {'account_profile': '店铺甲'})
    assert response.status_code == 409 and response.get_json()['msg'] == '当前账户是淘宝'
    assert api.gate.platform_calls == [('douyin', '店铺甲')]
    assert api.service.tasks == {} and api.threads == []


def test_start_without_final_publish_confirmation_is_refused(api):
    response = post(api, '/api/upload/start', {'stop_before_submit': False})
    body = response.get_json()
    assert body['success'] is False and 'confirm_final_publish=true' in body['msg']
    assert api.service.tasks == {} and api.threads == []


def test_start_unknown_record(api):
    assert post(api, '/api/upload/start', {'record_id': 99}).get_json()['msg'] == '未找到要上传的商品'


def test_start_checks_the_record_revision_the_ui_saw(api):
    api.revision.return_value = ({'success': False, 'msg': '资料已改变'}, 409)
    response = post(api, '/api/upload/start', {'record_id': 7, 'expected_record_revision': 'abc'})
    assert response.status_code == 409 and response.get_json()['msg'] == '资料已改变'
    api.revision.assert_called_once_with({'id': 7, 'title': 't'}, 'abc')
    assert api.service.tasks == {} and api.threads == []


def test_start_revision_must_be_bound_to_a_single_record(api):
    response = post(api, '/api/upload/start', {'expected_record_revision': 'abc'})
    assert response.status_code == 400 and response.get_json()['msg'] == '商品资料版本必须绑定单件商品'
    api.revision.assert_not_called()


def test_start_creates_a_pending_task_and_hands_it_to_a_daemon_worker(api):
    response = post(api, '/api/upload/start', {'record_id': 7, 'account_profile': '店铺甲', 'expected_record_revision': 'rev-1'})
    body = response.get_json()
    assert response.status_code == 200 and body['success'] is True and body['msg'] == '上传任务已启动'
    task_id = body['data']['task_id']
    task = api.service.tasks[task_id]
    assert (task['status'], task['progress'], task['message'], task['platform']) == ('pending', 0, '任务已创建', 'douyin')
    assert (task['account_profile'], task['record_id'], task['record_name']) == ('shop-a', 7, '白袜_货号_x_商品七')
    assert (task['stop_before_submit'], task['final_publish_confirmed'], task['cancelled']) == (True, False, False)
    assert task['created_at'] and task['started_at'] is None and task['error'] is None and task['steps'] == []
    (thread,) = api.threads
    assert thread.target == api.service.run_upload_task and thread.args == (task_id, 7, True) and thread.daemon is True
    assert api.gate.lock_entries == 1
    api.revision.assert_called_once()


def test_start_final_publish_with_confirmation(api):
    task_id = post(api, '/api/upload/start', {'record_id': 7, 'stop_before_submit': False, 'confirm_final_publish': True}).get_json()['data']['task_id']
    task = api.service.tasks[task_id]
    assert (task['stop_before_submit'], task['final_publish_confirmed']) == (False, True)
    assert api.threads[0].args == (task_id, 7, False)


def test_start_names_the_task_after_the_record_or_a_fallback(api):
    named = post(api, '/api/upload/start', {'record_id': 8}).get_json()['data']['task_id']
    assert api.service.tasks[named]['record_name'] == '商品8'                      # 记录没名字时的兜底
    whole = post(api, '/api/upload/start', {}).get_json()['data']['task_id']
    assert api.service.tasks[whole]['record_name'] == '全部商品' and api.service.tasks[whole]['record_id'] is None


# ============================================================================================ /api/upload/start-all
def test_start_all_shares_the_gate_and_the_confirmation_rules(api):
    assert post(api, '/api/upload/start-all', {'platform': 'taobao'}).status_code == 400
    api.gate.platform_error = ({'success': False, 'msg': '拒绝'}, 409)
    assert post(api, '/api/upload/start-all', {}).status_code == 409
    api.gate.platform_error = None
    assert 'confirm_final_publish=true' in post(api, '/api/upload/start-all', {'stop_before_submit': False}).get_json()['msg']
    assert api.service.tasks == {} and api.threads == []


def test_start_all_counts_only_unpublished_records(api):
    body = post(api, '/api/upload/start-all', {}).get_json()
    assert body['success'] is True and body['msg'] == '已启动批量上传(2个商品)' and body['data']['count'] == 2
    task = api.service.tasks[body['data']['task_id']]
    assert (task['record_name'], task['message'], task['record_id']) == ('全部(2个)', '批量上传2个商品', None)
    assert api.threads[0].args == (body['data']['task_id'], None, True)           # 批量任务的 record_id 是 None


def test_start_all_with_nothing_to_upload(api):
    for row in api.world.records.rows.values():
        row.status = 1
    assert post(api, '/api/upload/start-all', {}).get_json()['msg'] == '没有待上传的商品'
    assert api.threads == []


# ============================================================================================ /api/upload/ensure-session
def test_ensure_session_is_gated(api):
    api.gate.platform_error = ({'success': False, 'msg': '拒绝'}, 409)
    assert post(api, '/api/upload/ensure-session').status_code == 409
    assert api.gate.platform_calls == [('douyin', None)]


def test_ensure_session_reports_the_browser_and_the_last_progress_events(api):
    tab = SimpleNamespace(url='https://fxg.jinritemai.com/ffa/g/create', title='发布商品')
    api.world.state.page = object()

    def ensure(report):
        for index in range(25):
            report(index, '步骤%d' % index)
        return tab, None
    api.service.ensure_publish_session = ensure
    body = post(api, '/api/upload/ensure-session').get_json()
    assert body['success'] is True and body['msg'] == '上传浏览器会话已就绪'
    assert body['data']['browser_status'] == {'has_browser': True, 'is_logged_in': True,
                                              'current_url': 'https://fxg.jinritemai.com/ffa/g/create', 'title': '发布商品'}
    assert len(body['data']['events']) == 20 and body['data']['events'][-1] == {'progress': 24, 'message': '步骤24'}


def test_ensure_session_tolerates_a_tab_that_cannot_report_its_url(api):
    class Broken:
        @property
        def url(self):
            raise RuntimeError('gone')
        title = None
    api.service.ensure_publish_session = lambda report: (Broken(), None)
    status = post(api, '/api/upload/ensure-session').get_json()['data']['browser_status']
    assert status['current_url'] is None and status['title'] is None and status['is_logged_in'] is True


def test_ensure_session_failure_carries_the_reason_and_the_events(api):
    def ensure(report):
        report(13, '正在打开浏览器')
        return None, '浏览器启动失败：x'
    api.service.ensure_publish_session = ensure
    body = post(api, '/api/upload/ensure-session').get_json()
    assert body['success'] is False and body['msg'] == '浏览器启动失败：x'
    assert body['data']['browser_status'] == {'has_browser': False, 'is_logged_in': False, 'current_url': None, 'title': None}
    assert body['data']['events'] == [{'progress': 13, 'message': '正在打开浏览器'}]


def test_ensure_session_exceptions_are_reported_not_raised(api):
    api.service.ensure_publish_session = Mock(side_effect=RuntimeError('炸了'))
    body = post(api, '/api/upload/ensure-session').get_json()
    assert body['success'] is False and body['msg'] == '上传浏览器会话检查失败：炸了'
    assert body['data']['browser_status']['is_logged_in'] is False


# ============================================================================================ status / cancel / tasks
def seed(api, **tasks):
    with api.service.lock:
        api.service.tasks.update(tasks)


def test_status_of_an_unknown_task(api):
    assert get(api, '/api/upload/status/nope')['msg'] == '上传任务不存在'


def test_status_serializes_with_defaults_for_missing_keys(api):
    seed(api, t1={'task_id': 't1', 'status': 'running', 'secret_internal_field': 'x'})
    data = get(api, '/api/upload/status/t1')['data']
    assert data['task_id'] == 't1' and data['status'] == 'running'
    assert (data['platform'], data['progress'], data['message'], data['steps']) == ('douyin', 0, '', [])
    assert (data['stop_before_submit'], data['final_publish_confirmed'], data['cancelled']) == (False, False, False)
    assert 'secret_internal_field' not in data and len(data) == 18


def get(api, route):
    return api.client.get(route).get_json()


def test_cancel_unknown_and_finished_tasks_are_refused(api):
    assert post(api, '/api/upload/cancel/nope').get_json()['msg'] == '上传任务不存在'
    for status in ('success', 'completed', 'failed', 'cancelled'):
        seed(api, **{'t-' + status: {'status': status}})
        body = post(api, '/api/upload/cancel/t-' + status).get_json()
        assert body['success'] is False and body['msg'] == '任务已完成，无法取消（状态：%s）' % status
        assert 'cancelled' not in api.service.tasks['t-' + status]


def test_cancel_marks_a_running_task_and_leaves_the_stop_to_the_worker(api):
    seed(api, t1={'task_id': 't1', 'status': 'running'})
    body = post(api, '/api/upload/cancel/t1').get_json()
    assert body['success'] is True and body['msg'] == '已发送取消指令，任务将在当前步骤完成后停止'
    assert api.service.tasks['t1']['cancelled'] is True and api.service.tasks['t1']['message'] == '正在取消...'
    assert api.service.tasks['t1']['status'] == 'running'                   # 状态由 worker 在当前步骤做完后改
    assert api.gate.lock_entries == 0                                       # 取消 / 查询不进账户锁


def test_tasks_are_listed_newest_first_and_the_running_one_is_reported(api):
    seed(api, old={'task_id': 'old', 'status': 'success', 'created_at': '2026-10-01T10:00:00'},
         mid={'task_id': 'mid', 'status': 'running', 'created_at': '2026-10-02T10:00:00'},
         new={'task_id': 'new', 'status': 'pending', 'created_at': '2026-10-03T10:00:00'},
         nodate={'task_id': 'nodate', 'status': 'failed'})
    body = get(api, '/api/upload/tasks')
    assert [t['task_id'] for t in body['data']['tasks']] == ['new', 'mid', 'old', 'nodate']
    assert body['data']['browser_status'] == {'current_task': 'new', 'has_browser': False, 'is_running': True}


def test_tasks_when_nothing_is_running_and_a_browser_exists(api):
    api.world.state.page = object()
    seed(api, done={'task_id': 'done', 'status': 'success', 'created_at': 'x'})
    status = get(api, '/api/upload/tasks')['data']['browser_status']
    assert status == {'current_task': None, 'has_browser': True, 'is_running': False}


def test_only_the_three_starting_routes_enter_the_account_lock(api):
    api.service.ensure_publish_session = lambda report: (SimpleNamespace(url='u', title='t'), None)
    post(api, '/api/upload/start', {'record_id': 7})
    post(api, '/api/upload/start-all', {})
    post(api, '/api/upload/ensure-session')
    entered = api.gate.lock_entries
    seed(api, t1={'task_id': 't1', 'status': 'running'})
    get(api, '/api/upload/tasks')
    get(api, '/api/upload/status/t1')
    post(api, '/api/upload/cancel/t1')
    get(api, '/api/upload/debug/injection')
    assert entered == 3 and api.gate.lock_entries == 3


# ============================================================================================ 调试注入 / 协议运行时配置 / 旧 /start
def test_debug_injection_reads_both_files_and_survives_garbage(api, tmp_path, monkeypatch):
    monkeypatch.setattr('tempfile.gettempdir', lambda: str(tmp_path))
    assert get(api, '/api/upload/debug/injection')['data'] == {'result': None, 'error': None}
    (tmp_path / 'sku_inject_result.json').write_text('{"ok": 1}', encoding='utf-8')
    (tmp_path / 'sku_inject_error.txt').write_text('boom', encoding='utf-8')
    assert get(api, '/api/upload/debug/injection')['data'] == {'result': {'ok': 1}, 'error': 'boom'}
    (tmp_path / 'sku_inject_result.json').write_text('not json', encoding='utf-8')
    assert get(api, '/api/upload/debug/injection')['data'] == {'result': None, 'error': 'boom'}


def test_runtime_options_success_and_failure(api):
    api.service.run_fxg_runtime_options_probe = Mock(return_value={'options': [1]})
    body = post(api, '/api/protocol/fxg/runtime-options', {'category_id': 5}).get_json()
    assert body == {'success': True, 'msg': '运行时配置读取成功。', 'data': {'options': [1]}}
    api.service.run_fxg_runtime_options_probe.assert_called_once_with({'category_id': 5})
    api.service.run_fxg_runtime_options_probe = Mock(side_effect=ValueError('缺少类目关键词或类目 ID。'))
    body = post(api, '/api/protocol/fxg/runtime-options', {}).get_json()
    assert body['success'] is False and body['msg'] == '缺少类目关键词或类目 ID。'


def test_legacy_start_runs_the_flow_in_the_request(api):
    api.service.execute_upload_flow = Mock(return_value={'success': True, 'msg': '跑完', 'data': None})
    body = post(api, '/start', {'record_id': 7}).get_json()
    assert body['msg'] == '跑完'
    api.service.execute_upload_flow.assert_called_once_with(record_id=7, stop_before_submit=True)
    assert api.threads == [] and api.service.tasks == {}                      # 旧入口不建任务、不起线程


def test_legacy_start_without_confirmation_never_reaches_the_flow(api):
    api.service.execute_upload_flow = Mock()
    body = post(api, '/start', {'stop_before_submit': False}).get_json()
    assert body['success'] is False and 'confirm_final_publish=true' in body['msg']
    api.service.execute_upload_flow.assert_not_called()


def test_the_blueprint_serves_every_url_the_frontend_and_mcp_use():
    app = Flask('urls')
    app.register_blueprint(create_upload_blueprint(
        service=SimpleNamespace(), accounts=Gate(), record_model=SimpleNamespace(), require_product_revision=Mock()))
    rules = sorted((rule.rule, tuple(sorted(rule.methods - {'HEAD', 'OPTIONS'}))) for rule in app.url_map.iter_rules() if rule.endpoint != 'static')
    assert rules == [
        ('/api/protocol/fxg/runtime-options', ('POST',)),
        ('/api/upload/cancel/<task_id>', ('POST',)),
        ('/api/upload/debug/injection', ('GET',)),
        ('/api/upload/ensure-session', ('POST',)),
        ('/api/upload/start', ('POST',)),
        ('/api/upload/start-all', ('POST',)),
        ('/api/upload/status/<task_id>', ('GET',)),
        ('/api/upload/tasks', ('GET',)),
        ('/start', ('POST',)),
    ]

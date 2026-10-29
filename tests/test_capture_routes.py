# -*- coding: utf-8 -*-
"""商品链接采集接口（src/sidecar/capture_routes.py）：参数校验、任务状态接口、互斥锁与取消、采集线程的完整流程。

直接构造 ``CaptureService`` + 注册 ``capture`` 蓝图，浏览器 / 网络 / 睡眠都用 ``capture_fake_world`` 里的假件；
采集线程是真线程（互斥锁、取消、日志都只有在线程里才有意义），用事件等待而不是固定睡眠。
"""
import logging
import os
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from flask import Flask

from capture_fake_world import FakeEngine, FakeWorld, PAGE_1688, wait_until
from capture_test_support import make_blueprint, make_service

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'taobao-publisher'))
from taobao_publish import captured_attributes  # noqa: E402

START = '/api/capture/start'
WORKER = '_run_capture_task_with_lock_release'          # 采集后台线程的函数名（Python 3.10+ 会出现在线程名里）


class ListHandler(logging.Handler):
    def __init__(self):
        super().__init__(logging.INFO)
        self.records = []

    def emit(self, record):
        self.records.append(record)


def worker_threads():
    return [t for t in threading.enumerate() if WORKER in t.name]


def wait_worker_done():
    wait_until(lambda: not worker_threads())


@pytest.fixture
def env(tmp_path, monkeypatch):
    world = FakeWorld().install(monkeypatch)
    engine = FakeEngine()
    handler = ListHandler()
    logger = logging.getLogger('capture-routes-test')
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    logger.propagate = False

    def normalize(path):
        return path if os.path.isabs(path) else str(tmp_path / path)
    settings = SimpleNamespace(get_settings=lambda: SimpleNamespace(automation_config={}),
                               normalize_automation_config=lambda config: {'capture_preferences': {}})
    service = make_service(logger=logger, protocol_capture_engine=engine, find_cdp_port=lambda: 9401,
                           load_capture_attributes=lambda: captured_attributes, normalize_save_path=normalize)
    app = Flask('capture-routes-test')
    app.register_blueprint(make_blueprint(service, normalize_save_path=normalize, get_app_root=lambda: str(tmp_path),
                                          settings_manager=settings))
    monkeypatch.setenv('DOUYIN_DATA_DIR', str(tmp_path))      # 采集浏览器的 profile 目录跟随数据目录
    yield SimpleNamespace(world=world, engine=engine, service=service, client=app.test_client(), logs=handler.records,
                          root=tmp_path)
    wait_worker_done()
    logger.removeHandler(handler)


def start(env, url=PAGE_1688, **payload):
    return env.client.post(START, json=dict(url=url, **payload))


def finished(env, task_id):
    wait_until(lambda: env.service.tasks[task_id]['status'] in ('completed', 'failed'))
    wait_worker_done()
    return env.service.tasks[task_id]


# ------------------------------------------------------------------------------------------ 参数校验
def test_bad_start_requests_never_take_the_mutex(env, monkeypatch):
    cases = [(None, '启动任务失败'), ({}, '无效的请求数据'), ({'url': '  '}, '请输入商品或店铺链接'),
             ({'url': 'https://example.com/a'}, '仅支持淘宝/天猫/1688商品链接，或淘宝/天猫店铺链接')]
    for payload, message in cases:
        body = env.client.post(START, json=payload).get_json()
        assert body['success'] is False and body['message'].startswith(message), (payload, body)
    monkeypatch.setattr('requests.get', lambda url, **kw: (_ for _ in ()).throw(OSError('断网')))
    body = env.client.post(START, json={'url': 'https://m.tb.cn/h.abc'}).get_json()
    assert body['success'] is False and '解析淘宝短链失败：断网' in body['message']
    assert env.service.tasks == {} and env.service.running_task_id is None


# ------------------------------------------------------------------------------------------ 任务状态接口
def seed(env):
    tasks = env.service.tasks
    tasks['done'] = {'task_id': 'done', 'url': 'u1', 'status': 'completed', 'progress': 100, 'message': '采集完成', 'error_code': '',
                     'platform': '1688', 'capture_mode': 'dom', 'result': {'title': 'x'}, 'created_at': '2026-01-01T00:00:01'}
    tasks['bad'] = {'task_id': 'bad', 'url': 'u2', 'status': 'failed', 'progress': 0, 'message': '登录超时', 'error_code': 'login_timeout',
                    'platform': 'taobao', 'capture_mode': 'dom', 'result': None, 'created_at': '2026-01-01T00:00:02'}
    tasks['live'] = {'task_id': 'live', 'url': 'u3', 'status': 'running', 'progress': 50, 'message': '提取中', 'error_code': '',
                     'platform': '1688', 'capture_mode': 'protocol', 'result': None, 'created_at': '2026-01-01T00:00:03'}


def test_status_and_history_read_the_service_task_dictionary(env):
    seed(env)
    body = env.client.get('/api/capture/status/bad').get_json()
    assert (body['success'], body['status'], body['error_code'], body['can_retry'], body['user_action_required']) == (True, 'failed', 'login_timeout', True, True)
    assert body['action_hint'] and body['platform'] == 'taobao' and body['created_at'] == '2026-01-01T00:00:02'
    assert env.client.get('/api/capture/status/missing').get_json() == {'success': False, 'message': '任务不存在'}
    history = env.client.get('/api/capture/history').get_json()['data']['tasks']
    assert [t['task_id'] for t in history] == ['live', 'bad', 'done']                  # 最新的在前
    assert 'result' not in history[0] and history[0]['capture_mode'] == 'protocol'


def test_cancel_marks_the_task_and_releases_only_its_own_mutex(env):
    seed(env)
    assert env.client.post('/api/capture/cancel/missing').status_code == 404
    finished_view = env.client.post('/api/capture/cancel/done').get_json()
    assert finished_view == {'success': True, 'message': '任务已结束', 'task_id': 'done'}
    assert env.service.tasks['done']['status'] == 'completed'
    env.service.running_task_id = 'someone-else'
    body = env.client.post('/api/capture/cancel/live').get_json()
    assert body['success'] and body['message'] == '已取消采集任务'
    live = env.service.tasks['live']
    assert (live['status'], live['progress'], live['cancelled'], live['error_code'], live['message']) == ('failed', 0, True, 'cancelled', '任务已取消')
    assert env.service.running_task_id == 'someone-else'                               # 别人的互斥锁不能被顺手释放
    env.service.tasks['live2'] = dict(env.service.tasks['live'], task_id='live2', status='running', cancelled=False)
    env.service.running_task_id = 'live2'
    env.client.post('/api/capture/cancel/live2')
    assert env.service.running_task_id is None


# ------------------------------------------------------------------------------------------ 互斥锁
def test_a_second_start_is_rejected_while_one_is_running(env):
    env.service.running_task_id = 'capture_busy'
    body = start(env).get_json()
    assert body['success'] is False and '已有采集任务正在运行 (capture_busy)' in body['message']
    assert env.service.tasks == {} and env.service.running_task_id == 'capture_busy'


def test_an_error_after_taking_the_mutex_releases_it(env, monkeypatch):
    def broken(**kwargs):
        raise RuntimeError('协议记录初始化异常')
    original = env.service.start_protocol_capture_record
    monkeypatch.setattr(env.service, 'start_protocol_capture_record', broken)
    body = start(env).get_json()
    assert body['success'] is False and '启动任务失败: 协议记录初始化异常' in body['message']
    assert env.service.running_task_id is None and env.service.tasks == {}
    monkeypatch.setattr(env.service, 'start_protocol_capture_record', original)
    assert start(env).get_json()['success'] is True                                    # 锁已释放，下一次可以启动
    wait_worker_done()


# ------------------------------------------------------------------------------------------ 采集线程
def test_worker_failure_is_recorded_and_the_mutex_is_released(env, monkeypatch):
    monkeypatch.setitem(sys.modules, 'DrissionPage', None)                             # 函数内 import 抛 ImportError
    task_id = start(env).get_json()['task_id']
    task = finished(env, task_id)
    assert task['status'] == 'failed' and task['progress'] == 0 and task['error_code'] == 'Exception'
    assert '缺少依赖库 DrissionPage' in task['message']
    assert env.service.running_task_id is None
    summaries = [w for w in env.engine.writes if w[1] == 'task-summary']
    assert summaries and summaries[-1][2]['status'] == 'failed' and summaries[-1][2]['task_id'] == task_id


def test_1688_capture_runs_end_to_end_in_the_worker_thread(env):
    body = start(env, PAGE_1688 + '?spm=a', options={'download_images': True, 'extract_sku': True, 'extract_params': True}).get_json()
    assert body['success'] and body['message'] == '采集任务已启动'
    task = finished(env, body['task_id'])
    assert (task['status'], task['progress'], task['message'], task['error_code']) == ('completed', 100, '采集完成', '')
    result = task['result']
    assert result['title'] == '儿童纯棉袜' and result['price']['current'] == 6.8 and result['product_id'] == '123456'
    assert [s['name'] for s in result['sku_info']] == ['白色', '灰色']
    assert result['captured_attributes']['status'] == 'captured' and result['parameters'] == [{'name': '材质', 'value': '纯棉'}]
    folder = Path(result['download_path'])
    assert folder == env.root / 'uploads' / 'products' / 'ID-123456'
    files = sorted(str(p.relative_to(folder)).replace('\\', '/') for p in folder.rglob('*') if p.is_file())
    assert files == ['SKU/01_白色.jpg', 'SKU/02_灰色.png', '主图/主图_01.jpg', '主图/主图_02.png', '详情页/详情_001.jpg']
    assert env.service.running_task_id is None
    # 协议采集记录：任务摘要 + 采集结果
    assert [w[1] for w in env.engine.writes if w[0] in ('session', 'import_manifest')][-2:] == ['task-summary', 'capture-result']
    # 状态 / 历史接口看到的是同一份任务
    assert env.client.get('/api/capture/status/' + body['task_id']).get_json()['status'] == 'completed'
    assert [t['task_id'] for t in env.client.get('/api/capture/history').get_json()['data']['tasks']] == [body['task_id']]


def test_worker_logs_through_the_injected_logger(env):
    # 后台线程里没有 Flask 应用上下文：日志必须走注入的 logger，不能用 current_app
    task_id = start(env).get_json()['task_id']
    finished(env, task_id)
    in_worker = [r for r in env.logs if r.threadName != threading.main_thread().name]
    assert any('开始执行采集任务' in r.getMessage() for r in in_worker)
    assert any('采集任务完成' in r.getMessage() for r in in_worker)


def test_cancelling_a_waiting_worker_stops_it_and_keeps_the_mutex_free(env):
    env.world.behavior['antibot'] = True                                               # 一直处于风控验证页
    gate = threading.Event()
    env.world.gate = gate                                                              # 采集线程在下一次 sleep 里挂起
    task_id = start(env).get_json()['task_id']
    wait_until(env.world.entered.is_set)
    assert env.service.running_task_id == task_id
    assert env.client.post('/api/capture/cancel/' + task_id).get_json()['success']
    assert env.service.running_task_id is None                                         # 取消时同步释放互斥锁
    gate.set()                                                                         # 放行：线程发现任务已取消就直接返回
    wait_worker_done()
    task = env.service.tasks[task_id]
    assert (task['status'], task['error_code'], task['cancelled']) == ('failed', 'cancelled', True)
    assert env.world.downloads == [] and env.service.running_task_id is None           # 没去等 120 秒的验证，也没下载任何图片


def test_state_belongs_to_the_service_instance():
    first, second = make_service(), make_service()
    assert first.tasks is not second.tasks and first.lock is not second.lock
    assert first.mtop_product_cache is not second.mtop_product_cache
    assert first.running_task_id is None and first.tasks == {}

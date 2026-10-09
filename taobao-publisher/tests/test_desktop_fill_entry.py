# -*- coding: utf-8 -*-
"""真实HTTP处理函数的隔离验证：填写动作、来源、任务与提交锁。"""
import ast
import json
import math
import os
import threading
from datetime import datetime
from functools import wraps
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from flask import Flask, jsonify, request

from taobao_publish import desktop, mapping
from taobao_publish.authorization import WriteAuthorization
from taobao_publish.models import LocalProduct
from taobao_publish.folder_import import MATERIAL_CENTER_URL

APP_PATH = Path(__file__).resolve().parents[2] / 'tauri-app/python-sidecar/app.py'


@pytest.fixture
def entry(tmp_path):
    app = Flask(__name__)
    image = tmp_path / 'SKU' / '白色.jpg'
    image.parent.mkdir()
    image.write_bytes(b'local-test-image')
    row = {'id': 1, 'name': '商品一', 'path': str(tmp_path),
           'content': json.dumps([{'path': str(image), 'name': '白色', 'price': 12}])}
    calls = []
    tasks = {}
    gui = SimpleNamespace(page=None)
    browser = Mock(return_value=SimpleNamespace(address='127.0.0.1:9501'))

    class Record:
        DoesNotExist = LookupError

        @staticmethod
        def get_by_id(record_id):
            if record_id != 1:
                raise LookupError()
            return SimpleNamespace(__data__=row, name=row['name'])

    class Worker:
        def __init__(self, **kwargs):
            calls.append(kwargs)

        def start(self):
            # 不启动线程，不调用流水线或浏览器。
            pass

    namespace = {
        'app': app, 'request': request, 'jsonify': jsonify, 'json': json, 'os': os,
        'datetime': datetime, 'Record': Record,
        'wraps': wraps, '_shop_account_lock': threading.RLock(),
        'threading': SimpleNamespace(Thread=Worker),
        '_with_shop_account_lock': lambda fn: fn,
        '_require_publish_platform': lambda *args: None,
        '_active_shop_account': lambda: {'profile_name': 'taobao-test', 'platform': 'taobao'},
        'gui': gui, 'get_page': browser,
        'shop_session': SimpleNamespace(profile_dir=lambda name: str(tmp_path / name)),
        '_set_browser_debug_instance': Mock(),
        '_get_gui_page_debug_address': lambda: getattr(gui.page, 'address', ''),
        '_normalize_debug_address': lambda address: str(address or '').replace('localhost', '127.0.0.1'),
        '_TAOBAO_SHOP_LOGIN_URL': 'https://item.upload.taobao.com/sell/ai/category.htm',
        '_SHOP_LOGIN_URL': 'https://fxg.jinritemai.com/',
        '_taobao_cdp_list_url': Mock(return_value='http://127.0.0.1:9501/json/list'),
        '_load_taobao_desktop': lambda: desktop,
        '_load_taobao_pipeline': Mock(),
        '_taobao_tasks': tasks, '_taobao_tasks_lock': threading.RLock(),
        '_upload_tasks': {}, '_upload_tasks_lock': threading.RLock(),
        'api_ok': lambda msg='', data=None: jsonify(success=True, msg=msg, data=data),
        'api_error': lambda msg='', data=None: (jsonify(success=False, msg=msg, data=data), 503),
        'traceback': SimpleNamespace(print_exc=lambda: None),
    }
    tree = ast.parse(APP_PATH.read_text(encoding='utf-8'))
    names = {'_taobao_product_request_payload', '_run_taobao_publish_task', 'taobao_publish_start',
             '_with_shop_account_lock', '_activate_shop_profile', '_ensure_taobao_fill_browser',
             '_account_change_blocked',
             # ⚠️ 参数解析的**纯函数**：`taobao_publish_start` 会调它，不在名单里就
             # 撞 `NameError` → 500，测试只报"状态码不对"，看不到真因。
             '_parse_taobao_publish_options'}
    module = ast.Module(body=[node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names], type_ignores=[])
    # 允许值常量只有一份（在 app.py 里），校验必须用真正那份。
    constants = [node for node in tree.body
                 if isinstance(node, ast.Assign)
                 and any(getattr(t, 'id', None) == 'TAOBAO_LISTING_MODES' for t in node.targets)]
    assert len(constants) == 1, 'app.py 里应当只有一份 TAOBAO_LISTING_MODES'
    module.body = constants + module.body
    exec(compile(ast.fix_missing_locations(module), str(APP_PATH), 'exec'), namespace)
    return SimpleNamespace(client=app.test_client(), ns=namespace, calls=calls, tasks=tasks,
                           row=row, image=image, root=tmp_path, browser=browser, gui=gui, app=app)


def payload(entry):
    return {'record_id': 1, 'platform': 'taobao', 'account_profile': 'taobao-test',
            'fill_only': True, 'dry_run': False, 'stop_before_submit': True,
            'product': {'title': '棉袜', 'category_keyword': '中筒袜',
                        'skus': [{'spec_values': {'颜色分类': '白色'}, 'price': 12,
                                  'stock': 3, 'image_path': str(entry.image)}]}}


def test_current_form_reaches_real_task_and_category_mapping(entry):
    response = entry.client.post('/api/taobao/publish/start', json=payload(entry))
    assert response.status_code == 200 and response.json['success'] is True
    assert len(entry.calls) == 1
    task_id, row, intent, options = entry.calls[0]['args']
    assert row == entry.row
    assert intent['category'] == {'search_keyword': '中筒袜'}
    assert intent['skus'][0]['spec_values'] == {'颜色分类': '白色'}
    assert intent['skus'][0]['image_path'] == str(entry.image)
    assert options['fill_only'] is True and options['dry_run'] is False
    assert options['stop_before_submit'] is True
    assert options['cdp_list_url'] == 'http://127.0.0.1:9501/json/list'
    entry.browser.assert_called_once_with(
        MATERIAL_CENTER_URL, profile_name='taobao-test')
    assert entry.tasks[task_id]['publish_confirmed'] is False
    built = mapping.build_publish_item(LocalProduct(record_id=1, record_name='商品一'), intent)
    assert built.item.category.search_keyword == '中筒袜'
    assert built.item.category.category_id == '' and built.item.category.path == ()


@pytest.mark.parametrize('changed', [
    {'dry_run': True}, {'stop_before_submit': False}, {'fill_only': 'true'},
    {'dry_run': 'false'}, {'stop_before_submit': 'true'},
])
def test_fill_scope_cannot_relax_submit_or_skip_writes(entry, changed):
    body = payload(entry)
    body.update(changed)
    response = entry.client.post('/api/taobao/publish/start', json=body)
    assert response.status_code == 400
    assert entry.calls == [] and entry.tasks == {}
    entry.ns['_taobao_cdp_list_url'].assert_not_called()
    entry.browser.assert_not_called()


def test_keyword_only_request_preserves_explicit_category_id(entry):
    body = payload(entry)
    body['product']['category_id'] = '201581801'
    response = entry.client.post('/api/taobao/publish/start', json=body)
    assert response.status_code == 200
    assert entry.calls[0]['args'][2]['category'] == {
        'search_keyword': '中筒袜', 'category_id': '201581801'}


@pytest.mark.parametrize('title', ['袜' * 31, 'A' * 61, '袜' * 29 + 'ABC', '   '])
def test_invalid_title_stops_before_browser_launch(entry, title):
    body = payload(entry)
    body['product']['title'] = title
    response = entry.client.post('/api/taobao/publish/start', json=body)
    assert response.status_code == 400 and response.json['success'] is False
    assert '标题' in response.json['msg']
    entry.browser.assert_not_called()
    assert entry.tasks == {} and entry.calls == []


@pytest.mark.parametrize('title', ['袜' * 30, 'A' * 60, '袜' * 29 + 'AB'])
def test_title_at_limit_can_start_the_real_form_task(entry, title):
    body = payload(entry)
    body['product']['title'] = title
    response = entry.client.post('/api/taobao/publish/start', json=body)
    assert response.status_code == 200 and response.json['success'] is True
    assert entry.calls[0]['args'][2]['title'] == title


def test_overlong_guide_title_cannot_start_browser(entry):
    body = payload(entry)
    body['product']['guide_title'] = '好' * 16
    response = entry.client.post('/api/taobao/publish/start', json=body)
    assert response.status_code == 400 and '导购标题' in response.json['msg']
    entry.browser.assert_not_called()


@pytest.mark.parametrize('key', ['title', 'guide_title', 'freight_template_name', 'outer_id'])
@pytest.mark.parametrize('invalid', [None, True, 100, []])
def test_non_text_fields_are_not_silently_dropped(entry, key, invalid):
    body = payload(entry)
    body['product'][key] = invalid
    response = entry.client.post('/api/taobao/publish/start', json=body)
    assert response.status_code == 400 and key in response.json['msg']
    entry.browser.assert_not_called()
    assert entry.tasks == {} and entry.calls == []


@pytest.mark.parametrize('category_id', [True, 1.5, -1, '０１２', 'abc'])
def test_bad_explicit_category_id_fails_before_browser_resolution(entry, category_id):
    body = payload(entry)
    body['product']['category_id'] = category_id
    response = entry.client.post('/api/taobao/publish/start', json=body)
    assert response.status_code == 400
    entry.ns['_taobao_cdp_list_url'].assert_not_called()
    entry.browser.assert_not_called()


@pytest.mark.parametrize('field,value', [('price', True), ('price', -1), ('price', math.inf),
                                        ('stock', True), ('stock', -1), ('stock', 1.5)])
def test_bad_sku_numbers_fail_before_browser_resolution(entry, field, value):
    body = payload(entry)
    body['product']['skus'][0][field] = value
    response = entry.client.post('/api/taobao/publish/start', json=body)
    assert response.status_code == 400 and not response.json['success']
    assert entry.calls == []
    entry.ns['_taobao_cdp_list_url'].assert_not_called()
    entry.browser.assert_not_called()


def test_sku_image_must_be_registered_for_this_product(entry):
    other = entry.root / '另一个文件.jpg'
    other.write_bytes(b'not-a-registered-SKU')
    body = payload(entry)
    body['product']['skus'][0]['image_path'] = str(other)
    response = entry.client.post('/api/taobao/publish/start', json=body)
    assert response.status_code == 400 and '来源不匹配' in response.json['msg']
    assert entry.calls == []
    entry.ns['_taobao_cdp_list_url'].assert_not_called()
    entry.browser.assert_not_called()


def test_existing_browser_is_reused_through_the_same_account_lifecycle(entry):
    existing = SimpleNamespace(address='127.0.0.1:9501')
    entry.gui.page = existing
    entry.browser.return_value = existing
    response = entry.client.post('/api/taobao/publish/start', json=payload(entry))
    assert response.status_code == 200 and response.json['success'] is True
    assert entry.gui.page is existing
    entry.browser.assert_called_once_with(
        MATERIAL_CENTER_URL, profile_name='taobao-test')
    # 不在启动前另跑账户身份读取或遍历其它调试浏览器。
    entry.ns['_taobao_cdp_list_url'].assert_not_called()


@pytest.mark.parametrize('problem', ['Chrome启动失败', '没有调试地址'])
def test_browser_start_failure_does_not_create_a_fake_task(entry, problem):
    if problem == 'Chrome启动失败':
        entry.browser.side_effect = OSError(problem)
    else:
        entry.browser.return_value = SimpleNamespace(address='')
    response = entry.client.post('/api/taobao/publish/start', json=payload(entry))
    assert response.status_code == 503 and response.json['success'] is False
    assert '启动淘宝浏览器失败' in response.json['msg']
    assert entry.tasks == {} and entry.calls == []


@pytest.mark.parametrize('platform', ['taobao', 'douyin'])
@pytest.mark.parametrize('status', ['pending', 'running'])
def test_in_flight_upload_blocks_browser_navigation_before_it_happens(entry, platform, status):
    tasks = entry.tasks if platform == 'taobao' else entry.ns['_upload_tasks']
    tasks['existing'] = {'status': status, 'platform': platform}
    response = entry.client.post('/api/taobao/publish/start', json=payload(entry))
    assert response.status_code == 409 and response.json['success'] is False
    entry.browser.assert_not_called()
    assert entry.calls == [] and list(tasks) == ['existing']


def test_concurrent_clicks_do_not_open_or_navigate_the_browser_twice(entry):
    entered, release = threading.Event(), threading.Event()
    responses = []

    def fake_browser(*args, **kwargs):
        entered.set()
        assert release.wait(3)
        return SimpleNamespace(address='127.0.0.1:9501')

    def post():
        with entry.app.test_client() as client:
            responses.append(client.post('/api/taobao/publish/start', json=payload(entry)))

    entry.browser.side_effect = fake_browser
    first = threading.Thread(target=post)
    second = threading.Thread(target=post)
    first.start()
    assert entered.wait(3)
    second.start()
    release.set()
    first.join(3)
    second.join(3)
    assert not first.is_alive() and not second.is_alive()
    assert sorted(r.status_code for r in responses) == [200, 409]
    entry.browser.assert_called_once()
    assert len(entry.tasks) == 1 and len(entry.calls) == 1


def test_fill_grant_never_inherits_environment_submit_unlock(monkeypatch):
    monkeypatch.setenv('TAOBAO_UPLOAD_ALLOW_WRITE', 'submit_publish,update_item')
    monkeypatch.setenv('TAOBAO_UPLOAD_ALLOW_SUBMIT', '1')
    auth = WriteAuthorization.for_form_filling()
    assert auth.granted == frozenset(('upload_image', 'save_draft'))
    assert auth.submit_unlocked is False
    assert not auth.is_granted('submit_publish') and not auth.is_granted('update_item')


def test_worker_uses_scoped_grant_and_truthful_stop_result(entry):
    intent = {'title': '棉袜'}
    fake_pipeline = SimpleNamespace(run_from_record=Mock(return_value=SimpleNamespace(
        to_dict=lambda: {'success': True, 'stopped_before_submit': True, 'steps': []})))
    entry.ns['_load_taobao_pipeline'] = lambda: fake_pipeline
    entry.tasks['t'] = {'status': 'pending', 'steps': []}
    entry.ns['_run_taobao_publish_task']('t', entry.row, intent,
                                      {'fill_only': True, 'dry_run': False,
                                       'stop_before_submit': True, 'cdp_list_url': 'mock'})
    kwargs = fake_pipeline.run_from_record.call_args.kwargs
    assert kwargs['authorization'].source == 'desktop_form_filling'
    assert kwargs['authorization'].submit_unlocked is False
    assert kwargs['stop_before_submit'] is True and kwargs['dry_run'] is False
    assert entry.tasks['t']['status'] == 'succeeded'
    assert entry.tasks['t']['publish_confirmed'] is False
    assert '停在提交前' in entry.tasks['t']['message']


def test_pipeline_import_failure_finishes_task_as_failed(entry):
    entry.ns['_load_taobao_pipeline'] = Mock(side_effect=ImportError('missing module'))
    entry.tasks['t'] = {'status': 'pending', 'steps': []}
    entry.ns['_run_taobao_publish_task']('t', entry.row, {}, {'fill_only': True})
    assert entry.tasks['t']['status'] == 'failed'
    assert entry.tasks['t']['error'] == 'missing module'

# -*- coding: utf-8 -*-
"""真实HTTP处理函数的隔离验证：填写动作、来源、任务与提交锁。

2026-10-20 起淘宝接口来自真实的 ``src/sidecar/taobao_routes.py`` / ``taobao_service.py``，账户门禁与店铺会话服务也是真对象
（``shop_accounts.py`` / ``shop_service.py``）；以前是按名字从 app.py 里抽函数再 exec。只有商品表、浏览器、后台线程和
流水线是替身。「有没有发布任务在跑」那个问句仍由 app.py 里的 ``_publish_tasks_running`` 回答，从源码里抽出来用。
"""
import ast
import json
import math
import sys
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from flask import Flask

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
APP_PATH = REPO_ROOT / 'tauri-app/python-sidecar/app.py'

from src.sidecar import taobao_routes  # noqa: E402
from src.sidecar.shop_accounts import ShopAccountGuard  # noqa: E402
from src.sidecar.shop_service import ShopBrowserPort, ShopSessionService  # noqa: E402
from src.sidecar.taobao_routes import create_taobao_blueprint  # noqa: E402
from src.sidecar.taobao_service import TaobaoPublishService  # noqa: E402
from taobao_publish import mapping  # noqa: E402
from taobao_publish.authorization import WriteAuthorization  # noqa: E402
from taobao_publish.models import LocalProduct  # noqa: E402
from taobao_publish.folder_import import MATERIAL_CENTER_URL  # noqa: E402


@pytest.fixture
def entry(tmp_path, monkeypatch):
    app = Flask(__name__)
    image = tmp_path / 'SKU' / '白色.jpg'
    image.parent.mkdir()
    image.write_bytes(b'local-test-image')
    row = {'id': 1, 'name': '商品一', 'path': str(tmp_path),
           'content': json.dumps([{'path': str(image), 'name': '白色', 'price': 12}])}
    calls = []
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

    # 账户注册表假件：只有一个当前账户（淘宝 taobao-test）；其余都是真实的门禁 / 店铺会话服务在用
    registry = {'active_profile': 'taobao-test',
                'profiles': {'taobao-test': {'platform': 'taobao', 'label': '测试淘宝账户'}}}
    shop_session = SimpleNamespace(
        DEFAULT_PROFILE_NAME='upload-browser-profile',
        load_registry=lambda: registry,
        slugify_profile_name=lambda name: name,
        normalize_platform=lambda value: value,
        profile_dir=lambda name: str(tmp_path / name),
    )

    def normalize_address(address):
        return str(address or '').replace('localhost', '127.0.0.1')

    # 「有没有发布任务在跑」由 app.py 里的 _publish_tasks_running 回答（任务字典分属上传 / 淘宝两个域，留在入口）
    ns = {'upload_service': SimpleNamespace(tasks={}, lock=threading.RLock())}
    guard = ShopAccountGuard(shop_session=shop_session, has_running_publish_tasks=lambda: ns['_publish_tasks_running']())
    shop_service = ShopSessionService(
        accounts=guard,
        browser=ShopBrowserPort(
            page_state=lambda: gui,
            open_page=browser,
            normalize_address=normalize_address,
            gui_page_debug_address=lambda: getattr(gui.page, 'address', ''),
            find_browser_process=lambda _address: {},
            find_reusable_browser=lambda **_kwargs: {},
            set_debug_browser_instance=Mock(),
            host='127.0.0.1', shop_port_start=9500, shop_port_end=9599,
        ),
        shop_session=shop_session,
    )
    service = TaobaoPublishService(
        record_model=Record, repo_root=str(REPO_ROOT), accounts=guard, shop_service=shop_service,
        normalize_debug_address=normalize_address, resolve_data_file=lambda name: tmp_path / name,
        bootstrap_log=lambda message: None,
    )
    ns['taobao_service'] = service
    tree = ast.parse(APP_PATH.read_text(encoding='utf-8'))
    running = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == '_publish_tasks_running']
    assert len(running) == 1
    exec(compile(ast.Module(body=running, type_ignores=[]), str(APP_PATH), 'exec'), ns)

    # 本夹具没有浏览器：「当前账户的调试地址」换成固定值，流水线加载器换成可控的替身
    service.cdp_list_url = Mock(return_value='http://127.0.0.1:9501/json/list')
    service.load_pipeline = Mock()
    monkeypatch.setattr(taobao_routes, 'threading', SimpleNamespace(Thread=Worker))
    app.register_blueprint(create_taobao_blueprint(
        service=service, accounts=guard, record_model=Record, resolve_data_file=lambda name: tmp_path / name,
        require_product_revision=Mock(side_effect=AssertionError('本文件的请求不带 expected_record_revision')),
    ))
    return SimpleNamespace(client=app.test_client(), ns=ns, service=service, calls=calls, tasks=service.tasks,
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
    entry.service.cdp_list_url.assert_not_called()
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
    entry.service.cdp_list_url.assert_not_called()
    entry.browser.assert_not_called()


@pytest.mark.parametrize('field,value', [('price', True), ('price', -1), ('price', math.inf),
                                        ('stock', True), ('stock', -1), ('stock', 1.5)])
def test_bad_sku_numbers_fail_before_browser_resolution(entry, field, value):
    body = payload(entry)
    body['product']['skus'][0][field] = value
    response = entry.client.post('/api/taobao/publish/start', json=body)
    assert response.status_code == 400 and not response.json['success']
    assert entry.calls == []
    entry.service.cdp_list_url.assert_not_called()
    entry.browser.assert_not_called()


def test_sku_image_must_be_registered_for_this_product(entry):
    other = entry.root / '另一个文件.jpg'
    other.write_bytes(b'not-a-registered-SKU')
    body = payload(entry)
    body['product']['skus'][0]['image_path'] = str(other)
    response = entry.client.post('/api/taobao/publish/start', json=body)
    assert response.status_code == 400 and '来源不匹配' in response.json['msg']
    assert entry.calls == []
    entry.service.cdp_list_url.assert_not_called()
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
    entry.service.cdp_list_url.assert_not_called()


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
    tasks = entry.tasks if platform == 'taobao' else entry.ns['upload_service'].tasks
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
    entry.service.load_pipeline = lambda: fake_pipeline
    entry.tasks['t'] = {'status': 'pending', 'steps': []}
    entry.service.run_publish_task('t', entry.row, intent,
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
    entry.service.load_pipeline = Mock(side_effect=ImportError('missing module'))
    entry.tasks['t'] = {'status': 'pending', 'steps': []}
    entry.service.run_publish_task('t', entry.row, {}, {'fill_only': True})
    assert entry.tasks['t']['status'] == 'failed'
    assert entry.tasks['t']['error'] == 'missing module'

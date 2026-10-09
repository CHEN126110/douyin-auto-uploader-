# -*- coding: utf-8 -*-
"""保存到上传的数据交接：隔离 Flask/ORM，只运行真实处理函数，不开浏览器。"""
import ast
import copy
from datetime import datetime
from functools import wraps
import json
from pathlib import Path
import sys
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from flask import Flask, jsonify, request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'taobao-publisher'))
from taobao_publish import desktop


@pytest.fixture
def save_case():
    app = Flask('save-snapshot-test')
    # ⚠️ `notice` 是**真实库里仍然存在**的列（`src/orm.py` 保留列与迁移——删列是破坏性
    # 操作），只是代码不再使用它。夹具照实带着一个非空值，才能测出"资料指纹"容忍这一列。
    db = {'id': 7, 'name': '商品七', 'path': '商品资料', 'title': '旧标题',
          'remark': '旧备注', 'notice': '旧须知', 'repo': 88, 'clazz': '2', 'status': 0,
          'content': json.dumps([
              {'path': 'SKU/白色.jpg', 'name': '旧白色', 'price': 3.5, 'file_name': '白色.jpg'},
              {'path': 'SKU/黑色.jpg', 'name': '旧黑色', 'price': 4.5, 'file_name': '黑色.jpg'},
          ], ensure_ascii=False), 'update_time': datetime(2026, 10, 4)}
    instances = []
    save_effect = Mock(return_value=1)

    class Record:
        DoesNotExist = LookupError

        def __init__(self):
            self.__dict__.update(copy.deepcopy(db))
            instances.append(self)

        @property
        def __data__(self):
            return dict(self.__dict__)

        @classmethod
        def get_by_id(cls, record_id):
            if record_id != 7:
                raise LookupError()
            return cls()

        def save(self):
            count = save_effect()
            if count == 1:
                db.update(copy.deepcopy(self.__dict__))
            return count

    namespace = {
        'app': app, 'request': request, 'jsonify': jsonify, 'json': json,
        'wraps': wraps, 'Record': Record, '_shop_account_lock': threading.RLock(),
        '_upload_tasks': {}, '_upload_tasks_lock': threading.RLock(),
        '_taobao_tasks': {}, '_taobao_tasks_lock': threading.RLock(),
        '_require_publish_platform': Mock(return_value=None),
        '_load_taobao_desktop': lambda: desktop,
        'time': SimpleNamespace(now=lambda: datetime(2026, 10, 4, 1)),
        'traceback': SimpleNamespace(print_exc=lambda: None),
        'api_ok': lambda msg='', data=None: jsonify(success=True, msg=msg, data=data),
    }
    names = {'_with_shop_account_lock', '_product_edit_revision', '_require_product_revision',
             '_record_edit_blocked', '_validated_product_edits', 'save_info', '_taobao_product_request_payload'}
    source = ROOT / 'tauri-app/python-sidecar/app.py'
    tree = ast.parse(source.read_text(encoding='utf-8'))
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    assert {node.name for node in functions} == names
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(source), 'exec'), namespace)
    return SimpleNamespace(client=app.test_client(), db=db, ns=namespace, save=save_effect, instances=instances)


def payload(platform='douyin'):
    # 界面已撤掉「购买须知」（E-318），它也不再是可保存字段，所以这里不带 `notice`。
    return {'_id': 7, 'title': '当前标题', 'remark': '当前备注',
            'repo': 100, 'clazz': 2,
            'attr_size': 2, 'attr_path_1': 'SKU/白色.jpg', 'attr_name_1': '白色组合', 'attr_price_1': 29.8,
            'attr_path_2': 'SKU/黑色.jpg', 'attr_name_2': '黑色组合', 'attr_price_2': 32.8,
            'for_publish': True, 'platform': platform, 'account_profile': '测试账户'}


@pytest.mark.parametrize('platform', ['douyin', 'taobao'])
def test_current_form_is_saved_with_an_exact_record_acknowledgement(save_case, platform):
    response = save_case.client.post('/save_info', json=payload(platform))
    assert response.status_code == 200 and response.json['success'] is True
    assert save_case.db['title'] == '当前标题' and save_case.db['repo'] == 100
    assert [sku['price'] for sku in json.loads(save_case.db['content'])] == [29.8, 32.8]
    assert [sku['file_name'] for sku in json.loads(save_case.db['content'])] == ['白色.jpg', '黑色.jpg']
    assert response.json['data']['id'] == 7
    assert response.json['data']['record_revision'] == save_case.ns['_product_edit_revision'](save_case.db)
    save_case.ns['_require_publish_platform'].assert_called_once_with(platform, '测试账户')


@pytest.mark.parametrize('key,value', [
    ('repo', True), ('repo', -1), ('repo', 1.5), ('repo', None), ('clazz', []),
    ('attr_price_1', None), ('attr_price_1', 'bad'), ('attr_price_1', float('nan')),
    ('attr_price_1', float('inf')), ('attr_price_1', -1), ('attr_price_1', 0),
    ('attr_price_1', 1.001), ('attr_price_1', True), ('attr_path_1', '其它资料.jpg'),
    ('attr_path_2', 'SKU/白色.jpg'), ('attr_size', 1), ('attr_size', True),
    ('attr_name_2', '白色组合'), ('attr_name_1', ''), ('title', None), ('title', ''),
    ('for_publish', 'false'), ('platform', 'unknown'), ('account_profile', None),
])
def test_invalid_input_cannot_change_any_record_or_turn_into_zero(save_case, key, value):
    before = copy.deepcopy(save_case.db)
    body = payload()
    body[key] = value
    response = save_case.client.post('/save_info', json=body)
    assert response.status_code == 400 and response.json['success'] is False
    assert save_case.db == before
    save_case.save.assert_not_called()
    assert all(record.__data__ == before for record in save_case.instances)


def test_taobao_title_rule_is_checked_before_the_record_is_modified(save_case):
    before = copy.deepcopy(save_case.db)
    body = payload('taobao')
    body['title'] = '袜' * 31
    response = save_case.client.post('/save_info', json=body)
    assert response.status_code == 400 and '标题' in response.json['msg']
    assert save_case.db == before
    save_case.save.assert_not_called()


def test_manual_save_can_preserve_explicit_zero_draft_price(save_case):
    body = payload()
    body.pop('for_publish')
    body['attr_price_1'] = 0
    response = save_case.client.post('/save_info', json=body)
    assert response.status_code == 200 and response.json['success'] is True
    assert json.loads(save_case.db['content'])[0]['price'] == 0
    save_case.ns['_require_publish_platform'].assert_not_called()


def test_partial_save_preserves_unsupplied_fields(save_case):
    before = copy.deepcopy(save_case.db)
    response = save_case.client.post('/save_info', json={'_id': 7, 'remark': '仅改备注'})
    assert response.status_code == 200
    assert save_case.db['remark'] == '仅改备注'
    for field in ('title', 'repo', 'clazz', 'content', 'name', 'path', 'status'):
        assert save_case.db[field] == before[field]


@pytest.mark.parametrize('platform,scope', [('douyin', 7), ('douyin', None), ('taobao', 7)])
@pytest.mark.parametrize('status', ['pending', 'running'])
def test_save_is_blocked_while_the_record_is_in_use(save_case, platform, scope, status):
    tasks = save_case.ns['_upload_tasks' if platform == 'douyin' else '_taobao_tasks']
    tasks['existing'] = {'status': status, 'record_id': scope}
    response = save_case.client.post('/save_info', json=payload())
    assert response.status_code == 409
    save_case.save.assert_not_called()


def test_another_record_task_does_not_block_this_local_save(save_case):
    save_case.ns['_upload_tasks']['other'] = {'status': 'running', 'record_id': 8}
    assert save_case.client.post('/save_info', json=payload()).status_code == 200


def test_database_failure_and_zero_affected_rows_are_not_success(save_case):
    before = copy.deepcopy(save_case.db)
    save_case.save.return_value = 0
    response = save_case.client.post('/save_info', json=payload())
    assert response.status_code == 500 and response.json['success'] is False
    assert save_case.db == before
    save_case.save.side_effect = OSError('数据库不可写')
    response = save_case.client.post('/save_info', json=payload())
    assert response.status_code == 500 and '数据库不可写' in response.json['msg']
    assert save_case.db == before


def test_revision_changes_with_price_but_not_timestamp_or_orm_clazz_cast(save_case):
    fn = save_case.ns['_product_edit_revision']
    first = fn(save_case.db)
    updated = copy.deepcopy(save_case.db)
    updated['clazz'] = 2
    updated['update_time'] = datetime(2026, 10, 5)
    assert fn(updated) == first
    content = json.loads(updated['content'])
    content[0]['price'] = 29.8
    updated['content'] = json.dumps(content, ensure_ascii=False)
    assert fn(updated) != first


def test_the_retired_notice_key_can_no_longer_write_anything(save_case):
    """「购买须知」的保存通路已删除：再发 `notice` 不再产生任何改动（只有时间戳会更新）。

    留这一条是因为它**曾经能写库**——只发 `notice` 就能改记录。现在保存白名单里没有它，
    这次请求等于"什么都没改"，指纹也不动。哪天有人把这一项加回白名单，这里会先红。
    """

    before = copy.deepcopy(save_case.db)
    first = save_case.ns['_product_edit_revision'](save_case.db)
    response = save_case.client.post('/save_info', json={'_id': 7, 'notice': '接回来的话这里会变'})
    assert response.status_code == 200 and response.json['success'] is True
    changed = {key for key in before if save_case.db[key] != before[key]}
    assert changed <= {'update_time'}, 'notice 已不是可保存字段，不该改到别的列：{}'.format(changed)
    assert save_case.db['notice'] == '旧须知'
    assert save_case.ns['_product_edit_revision'](save_case.db) == first


def test_revision_ignores_the_retired_notice_column(save_case):
    """`notice` 不再进"资料指纹"：流水线不消费它，改它不该让上传被判「资料已改变」。

    ⚠️ 真实库里这一列还在（`src/orm.py` 保留列与迁移），所以夹具也带着一个非空值——
    指纹函数要**容忍真实存在的列**，而不是要求库里没有它。
    """

    fn = save_case.ns['_product_edit_revision']
    first = fn(save_case.db)
    updated = copy.deepcopy(save_case.db)
    updated['notice'] = '改过的须知'
    assert fn(updated) == first


def test_stale_revision_is_an_explicit_rejection(save_case):
    fn = save_case.ns['_require_product_revision']
    revision = save_case.ns['_product_edit_revision'](save_case.db)
    with save_case.client.application.app_context():
        assert fn(save_case.db, revision) is None
        response, status = fn(save_case.db, '0' * 64)
        assert status == 409 and response.json['success'] is False


def use_sqlite_record(save_case):
    """真实 Peewee/SQLite 数据类型转换验证，不导入会绑定用户库的 src.orm。"""
    from peewee import AutoField, CharField, DateTimeField, IntegerField, Model, SqliteDatabase, TextField
    case_database = SqliteDatabase(':memory:')

    class Row(Model):
        id = AutoField()
        name = CharField()
        path = TextField(null=True)
        title = CharField(null=True)
        remark = TextField(null=True)
        # 购买须知：真实 Record 表**保留**这一列（`src/orm.py`，删列是破坏性操作），
        # 所以这里也照实带上。它已不在 `_product_edit_revision` 的字段里。
        notice = TextField(null=True)
        repo = IntegerField(null=True)
        clazz = CharField(null=True)
        content = TextField()
        update_time = DateTimeField()

        class Meta:
            database = case_database

    case_database.create_tables([Row])
    Row.create(**{key: value for key, value in save_case.db.items() if key != 'status'})
    save_case.ns['Record'] = Row
    return case_database, Row


def wire_starts(save_case):
    calls = []

    class Worker:
        def __init__(self, **kwargs):
            calls.append(kwargs)

        def start(self):
            pass  # 不启动实际线程，尤其不调用真实发布函数。

    save_case.ns.update({
        'datetime': datetime, 'threading': SimpleNamespace(Thread=Worker),
        '_active_shop_account': lambda: {'profile_name': '测试账户'},
        '_ensure_taobao_fill_browser': Mock(return_value='http://127.0.0.1:9501/json/list'),
        '_account_change_blocked': lambda: None,
        '_resolve_upload_stop_before_submit': lambda data: (True, False),
        '_run_taobao_publish_task': Mock(), '_run_upload_task': Mock(),
    })
    source = ROOT / 'tauri-app/python-sidecar/app.py'
    tree = ast.parse(source.read_text(encoding='utf-8'))
    # ⚠️ `taobao_publish_start` 会调用参数解析的**纯函数**（以及它用的允许值常量）。
    # 不把这两个一起 exec，路由会撞 `NameError` → 500，而测试报的是"状态码不对"，
    # 看不到真正原因。它们都不依赖 Flask/账户/数据库。
    names = {'taobao_publish_start', 'upload_start', '_parse_taobao_publish_options'}
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    constants = [node for node in tree.body
                 if isinstance(node, ast.Assign)
                 and any(getattr(t, 'id', None) == 'TAOBAO_LISTING_MODES' for t in node.targets)]
    assert len(constants) == 1, 'app.py 里应当只有一份 TAOBAO_LISTING_MODES'
    exec(compile(ast.Module(body=constants + functions, type_ignores=[]), str(source), 'exec'),
         save_case.ns)
    return calls


def test_actual_sqlite_saved_values_and_reload_share_the_acknowledged_revision(save_case):
    database, Row = use_sqlite_record(save_case)
    try:
        response = save_case.client.post('/save_info', json=payload())
        assert response.status_code == 200 and response.json['success'] is True
        row = Row.get_by_id(7)
        assert row.clazz == '2' and row.repo == 100
        assert [entry['price'] for entry in json.loads(row.content)] == [29.8, 32.8]
        assert save_case.ns['_product_edit_revision'](row.__data__) == response.json['data']['record_revision']
    finally:
        database.close()


@pytest.mark.parametrize('platform', ['douyin', 'taobao'])
@pytest.mark.parametrize('changed', [False, True])
def test_upload_only_starts_with_the_saved_form_version(save_case, platform, changed):
    database, Row = use_sqlite_record(save_case)
    try:
        calls = wire_starts(save_case)
        saved = save_case.client.post('/save_info', json=payload(platform))
        assert saved.status_code == 200
        revision = saved.json['data']['record_revision']
        if changed:
            row = Row.get_by_id(7)
            content = json.loads(row.content)
            content[0]['price'] = 99
            row.content = json.dumps(content)
            row.save()
        body = {'record_id': 7, 'platform': platform, 'account_profile': '测试账户',
                'stop_before_submit': True, 'expected_record_revision': revision}
        if platform == 'taobao':
            body.update(fill_only=True, dry_run=False, product={'title': '当前标题', 'category_keyword': '中筒袜'})
        route = '/api/taobao/publish/start' if platform == 'taobao' else '/api/upload/start'
        response = save_case.client.post(route, json=body)
        if changed:
            assert response.status_code == 409 and '资料已改变' in response.json['msg']
            assert calls == [] and save_case.ns['_taobao_tasks'] == {} and save_case.ns['_upload_tasks'] == {}
            save_case.ns['_ensure_taobao_fill_browser'].assert_not_called()
        else:
            assert response.status_code == 200 and response.json['success'] is True
            assert len(calls) == 1
    finally:
        database.close()

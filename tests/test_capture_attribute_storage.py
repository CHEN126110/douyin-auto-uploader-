"""隔离 SQLite + Flask 验证采集导入；绝不 import 会初始化真实库的 src.orm。"""
import ast
from copy import deepcopy
from datetime import datetime
import json
import os
from pathlib import Path
import re
import sys
from types import SimpleNamespace
from unittest.mock import Mock

from flask import Flask, jsonify, request
from PIL import Image
import peewee
import pytest

from capture_test_support import capture_routes, make_blueprint, make_service
from test_product_save_snapshot import save_case

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'taobao-publisher'))
from taobao_publish import captured_attributes


def envelope(value='四季'):
    return {'version':1,'source':captured_attributes.SOURCE,'status':'captured',
            'attributes':[{'name':'适用季节','value':value}]}


def definitions(path,names):
    nodes=[node for node in ast.parse(path.read_text(encoding='utf-8')).body
           if isinstance(node,(ast.ClassDef,ast.FunctionDef)) and node.name in names]
    assert len(nodes)==len(names)
    return compile(ast.Module(body=nodes,type_ignores=[]),str(path),'exec')


@pytest.fixture
def storage(tmp_path, monkeypatch):
    database=peewee.SqliteDatabase(':memory:')
    namespace={name:getattr(peewee,name) for name in peewee.__all__}
    namespace['database']=database
    exec(definitions(ROOT/'src/orm.py',{'BaseModel','Record','_ensure_record_columns'}),namespace)
    Record=namespace['Record']
    database.create_tables([Record])
    app=Flask('capture-attribute-test')
    # 采集服务和导入接口是真实的（直接构造 CaptureService + 注册 capture 蓝图）；ns 是给同夹具里
    # 其它「从 app.py 抽函数」的测试（白底图选择等）准备的公共命名空间。
    service=make_service(record_model=Record,load_capture_attributes=lambda:captured_attributes)
    app.register_blueprint(make_blueprint(service,get_app_root=lambda:str(tmp_path)))
    monkeypatch.setattr(capture_routes.traceback,'print_exc',lambda:None)
    ns={'app':app,'request':request,'jsonify':jsonify,'os':os,'re':re,'json':json,
        'datetime':datetime,'Record':Record,'traceback':SimpleNamespace(print_exc=lambda:None),
        '_load_capture_attributes':lambda:captured_attributes}
    product=tmp_path/'商品资料'
    (product/'SKU').mkdir(parents=True)
    Image.new('RGB', (80, 80), 'white').save(product/'SKU/模型袜子.jpg')
    value={'title':'本地测试商品','download_path':str(product),'url':'https://example.invalid/product/1',
           'sku_info':[{'name':'模型袜子','price':20.8}],'main_images':[],
           'captured_attributes':envelope()}
    yield SimpleNamespace(ns=ns,service=service,Record=Record,database=database,product=value,client=app.test_client(),
                          migrate=namespace['_ensure_record_columns'])
    database.close()


@pytest.mark.parametrize('route',['helper','single','store'])
def test_all_capture_import_entries_persist_attributes(storage,route):
    if route=='helper':
        result=storage.service.import_capture_product_record(storage.product)
        record_id=result['record_id']
    else:
        product=storage.product if route=='single' else {'capture_type':'store','products':[storage.product]}
        storage.service.tasks['local']={'result':product}
        response=storage.client.post('/api/capture/import',json={'task_id':'local'})
        assert response.json['success'],response.json
        record_id=storage.Record.select().get().id
    record=storage.Record.get_by_id(record_id)
    assert json.loads(record.captured_attributes)==envelope()
    assert json.loads(record.content)[0]['price']==20.8


@pytest.mark.parametrize('route',['helper','single'])
def test_invalid_attributes_are_rejected_before_replacing_an_existing_product(storage,route):
    storage.service.import_capture_product_record(storage.product)
    before=storage.Record.select().get().__data__.copy()
    storage.product['captured_attributes']['source']='trackParams'
    if route=='helper':
        with pytest.raises(ValueError): storage.service.import_capture_product_record(storage.product)
    else:
        response=storage.client.post('/api/capture/import',json={'task_id':'local','product_data':storage.product})
        assert response.json['success'] is False
    assert storage.Record.select().get().__data__==before


@pytest.mark.parametrize('route',['helper','single'])
def test_create_failure_rolls_back_record_replacement(storage,route,monkeypatch):
    storage.service.import_capture_product_record(storage.product)
    before=storage.Record.select().get().__data__.copy()
    monkeypatch.setattr(storage.Record,'update',Mock(side_effect=RuntimeError('模拟写入失败')))
    if route=='helper':
        with pytest.raises(RuntimeError): storage.service.import_capture_product_record(storage.product)
    else:
        response=storage.client.post('/api/capture/import',json={'task_id':'local','product_data':storage.product})
        assert response.json['success'] is False
    assert storage.Record.select().get().__data__==before


def test_unproven_parameters_do_not_enter_automatic_filling(storage):
    del storage.product['captured_attributes']
    storage.product['parameters']=[{'name':'适用季节','value':'埋点值'}]
    storage.service.import_capture_product_record(storage.product)
    assert storage.Record.select().get().captured_attributes is None


def test_migration_is_additive_idempotent_and_preserves_old_rows(storage):
    storage.database.execute_sql('DROP TABLE record')
    storage.database.execute_sql('CREATE TABLE record (id INTEGER PRIMARY KEY, title TEXT, content TEXT)')
    storage.database.execute_sql('INSERT INTO record (title,content) VALUES (?,?)',('旧商品','旧资料'))
    storage.migrate()
    storage.migrate()
    assert storage.database.execute_sql('SELECT title,content,captured_attributes FROM record').fetchone()==('旧商品','旧资料',None)


def test_save_preserves_captured_attributes_and_revision_binds_values(save_case):
    save_case.ns['_load_capture_attributes']=lambda:captured_attributes
    save_case.db['captured_attributes']=captured_attributes.dumps(envelope())
    revision=save_case.ns['_product_edit_revision'](save_case.db)
    response=save_case.client.post('/save_info',json={'_id':7,'title':'用户修改标题'})
    assert response.json['success'],response.json
    assert json.loads(save_case.db['captured_attributes'])==envelope()
    assert save_case.ns['_product_edit_revision'](save_case.db)!=revision
    first=save_case.ns['_product_edit_revision'](save_case.db)
    save_case.db['captured_attributes']=json.dumps(envelope('冬季'),ensure_ascii=False)
    assert save_case.ns['_product_edit_revision'](save_case.db)!=first
    save_case.db['captured_attributes']=json.dumps(envelope(),ensure_ascii=False,indent=4)
    assert save_case.ns['_product_edit_revision'](save_case.db)==first


def test_capture_adapter_respects_extract_params_option_and_records_absence(storage):
    page=Mock()
    page.run_js.return_value={'version':1,'source':captured_attributes.SOURCE,'status':'not_found','attributes':[]}
    value={}
    storage.service.capture_product_attributes(page,value,{'extract_params':False})
    page.run_js.assert_not_called()
    assert value['captured_attributes']['status']=='disabled'
    storage.service.capture_product_attributes(page,value,{'extract_params':True})
    assert value['parameters']==[] and value['captured_attributes']['status']=='not_found'


def test_duplicate_history_records_are_never_overwritten(storage):
    storage.service.import_capture_product_record(storage.product)
    first = storage.Record.select().get()
    storage.Record.create(name=first.name,path=first.path,type=2,status=0,repo=1,title='重复的历史记录',clazz=2,
                          content='[]',remark='',update_time=datetime(2026,1,1))
    before = sorted((r.id,r.title,r.content) for r in storage.Record.select())
    with pytest.raises(ValueError,match='多条历史记录'):
        storage.service.import_capture_product_record(storage.product)
    assert sorted((r.id,r.title,r.content) for r in storage.Record.select()) == before

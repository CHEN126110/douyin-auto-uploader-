# -*- coding: utf-8 -*-
"""商品删除与文件生命周期：只使用隔离 SQLite 和本测试创建的目录。"""
import ast
import ctypes
from datetime import datetime
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from flask import Flask, jsonify, request
import peewee
import pytest

ROOT = Path(__file__).resolve().parents[1]


def definitions(path, names):
    nodes = [node for node in ast.parse(path.read_text(encoding='utf-8')).body
             if isinstance(node, (ast.ClassDef, ast.FunctionDef)) and node.name in names]
    assert {node.name for node in nodes} == names
    return compile(ast.Module(body=nodes, type_ignores=[]), str(path), 'exec')


@pytest.fixture
def deletion(tmp_path):
    database = peewee.SqliteDatabase(':memory:')
    models = {name: getattr(peewee, name) for name in peewee.__all__}
    models['database'] = database
    exec(definitions(ROOT / 'src/orm.py', {'BaseModel', 'Record'}), models)
    Record = models['Record']
    database.create_tables([Record])
    app = Flask('product-delete-files-test')
    ns = {'app': app, 'os': os, 'ctypes': ctypes, 'request': request, 'Record': Record,
          'api_ok': lambda msg, data=None: jsonify(success=True, message=msg, data=data),
          'api_error': lambda msg, data=None: jsonify(success=False, message=msg, data=data)}
    exec(definitions(ROOT / 'tauri-app/python-sidecar/app.py', {
        '_is_truthy', '_is_capture_managed_record', '_assert_safe_recycle_target',
        '_move_path_to_recycle_bin', '_delete_product_record', 'menu_delete', 'delete_all',
    }), ns)
    actual_recycle = ns['_move_path_to_recycle_bin']
    recycled = tmp_path / '模拟回收站'
    recycled.mkdir()

    def fake_recycle(path):
        source = Path(ns['_assert_safe_recycle_target'](path))
        if not source.exists():
            return False
        # 测试自己也必须确认移动起点、终点都在隔离目录内。
        assert source.resolve().is_relative_to(tmp_path.resolve())
        destination = recycled / source.name
        assert destination.resolve().is_relative_to(tmp_path.resolve())
        source.rename(destination)
        return True

    ns['_move_path_to_recycle_bin'] = Mock(side_effect=fake_recycle)

    def create(name='ID-123', *, source='capture', managed=True):
        folder = tmp_path / name
        folder.mkdir()
        for relative in ('主图/主图_01.jpg', 'SKU/白色.jpg', '详情页/详情_01.jpg',
                         '白底图/白色.jpg', 'SKU_1x1/白色.jpg', 'capture_manifest.json'):
            file = folder / relative
            file.parent.mkdir(exist_ok=True)
            file.write_bytes(relative.encode('utf-8'))
        return Record.create(name=name, path=str(folder), type=2, status=0,
                             content='[]', update_time=datetime.now(),
                             import_source=source, managed_files=managed)

    yield SimpleNamespace(ns=ns, Record=Record, database=database, create=create,
                          client=app.test_client(), root=tmp_path, recycled=recycled,
                          actual_recycle=actual_recycle)
    database.close()


def test_single_delete_recycles_entire_product_and_removes_record(deletion):
    record = deletion.create()
    original = {file.relative_to(record.path): file.read_bytes()
                for file in Path(record.path).rglob('*') if file.is_file()}
    response = deletion.client.get('/menu_delete', query_string={'_id': record.id})
    assert response.json['success'], response.json
    assert not deletion.Record.select().exists()
    assert not Path(record.path).exists()
    assert {file.relative_to(deletion.recycled / record.name): file.read_bytes()
            for file in (deletion.recycled / record.name).rglob('*') if file.is_file()} == original
    deletion.ns['_move_path_to_recycle_bin'].assert_called_once_with(record.path)


@pytest.mark.parametrize('source,managed', [('manual', False), ('manual', True), ('capture', False)])
def test_manual_or_unowned_files_are_preserved(deletion, source, managed):
    record = deletion.create(source=source, managed=managed)
    response = deletion.client.get('/menu_delete', query_string={'_id': record.id})
    assert response.json['success']
    assert not deletion.Record.select().exists()
    assert (Path(record.path) / 'SKU/白色.jpg').exists()
    deletion.ns['_move_path_to_recycle_bin'].assert_not_called()


def test_recycle_failure_rolls_back_record_and_reports_actual_error(deletion):
    record = deletion.create()
    deletion.ns['_move_path_to_recycle_bin'].side_effect = OSError('模拟文件被占用')
    response = deletion.client.get('/menu_delete', query_string={'_id': record.id})
    assert response.json['success'] is False
    assert '模拟文件被占用' in response.json['message']
    assert deletion.Record.get_by_id(record.id).path == record.path
    assert (Path(record.path) / 'SKU/白色.jpg').exists()


def test_readonly_database_cannot_move_files_first(deletion):
    record = deletion.create()
    deletion.database.execute_sql('PRAGMA query_only = ON')
    try:
        response = deletion.client.get('/menu_delete', query_string={'_id': record.id})
        assert response.json['success'] is False
        assert 'readonly' in response.json['message']
        assert deletion.Record.get_by_id(record.id)
        assert Path(record.path).exists()
        deletion.ns['_move_path_to_recycle_bin'].assert_not_called()
    finally:
        deletion.database.execute_sql('PRAGMA query_only = OFF')


def test_missing_folder_still_removes_obsolete_record(deletion):
    record = deletion.create()
    # 模拟用户已在资源管理器移走目录；仍保留文件用于测试，不做硬删除。
    folder = Path(record.path)
    folder.rename(deletion.root / '用户已移走')
    response = deletion.client.get('/menu_delete', query_string={'_id': record.id})
    assert response.json['success']
    assert not deletion.Record.select().exists()


def test_clear_all_uses_same_file_policy(deletion):
    first = deletion.create('ID-123')
    second = deletion.create('ID-456')
    manual = deletion.create('手工原始素材', source='manual', managed=False)
    response = deletion.client.delete('/delete_all')
    assert response.json['success'], response.json
    assert not deletion.Record.select().exists()
    assert not Path(first.path).exists() and not Path(second.path).exists()
    assert (Path(manual.path) / '主图/主图_01.jpg').exists()


def test_clear_all_partial_failure_preserves_failed_and_remaining_records(deletion):
    first, second, third = (deletion.create('ID-' + str(index)) for index in (1, 2, 3))
    recycle = deletion.ns['_move_path_to_recycle_bin']
    perform = recycle.side_effect

    def fail_second(path):
        if path == second.path:
            raise OSError('第二个目录被占用')
        return perform(path)

    recycle.side_effect = fail_second
    response = deletion.client.delete('/delete_all')
    assert response.json['success'] is False
    assert '已删除 1 个商品' in response.json['message']
    assert '第二个目录被占用' in response.json['message']
    assert [r.id for r in deletion.Record.select().order_by(deletion.Record.id)] == [second.id, third.id]
    assert not Path(first.path).exists()
    assert Path(second.path).exists() and Path(third.path).exists()


@pytest.mark.parametrize('bad', ['', '  ', '相对目录', '.', '../商品', None, '\\当前磁盘相对目录'])
def test_empty_or_relative_path_never_becomes_working_directory(deletion, bad):
    with pytest.raises(ValueError, match='绝对路径'):
        deletion.ns['_assert_safe_recycle_target'](bad)


@pytest.mark.parametrize('suffix', ['*', '?', '\0'])
def test_shell_wildcards_and_nul_are_rejected(deletion, suffix):
    with pytest.raises(ValueError, match='通配符'):
        deletion.ns['_assert_safe_recycle_target'](str(deletion.root) + suffix)


def test_root_and_mismatched_parent_folder_are_rejected(deletion):
    with pytest.raises(ValueError, match='根目录'):
        deletion.ns['_assert_safe_recycle_target'](str(deletion.root.anchor))
    record = deletion.create()
    deletion.Record.update(path=str(deletion.root)).where(deletion.Record.id == record.id).execute()
    response = deletion.client.get('/menu_delete', query_string={'_id': record.id})
    assert response.json['success'] is False
    assert '目录名称与记录不一致' in response.json['message']
    assert deletion.Record.get_by_id(record.id)
    deletion.ns['_move_path_to_recycle_bin'].assert_not_called()


@pytest.mark.skipif(os.name != 'nt', reason='Windows Shell 回收站接口')
@pytest.mark.parametrize('result,aborted,expected', [
    (120, False, '系统错误码: 120'), (0, True, '被系统取消'), (0, False, '文件仍然存在'),
])
def test_shell_error_cancel_or_unmoved_file_cannot_report_success(deletion, monkeypatch, result, aborted, expected):
    record = deletion.create()

    def shell_operation(pointer):
        pointer._obj.fAnyOperationsAborted = aborted
        return result

    monkeypatch.setattr(ctypes, 'windll', SimpleNamespace(
        shell32=SimpleNamespace(SHFileOperationW=shell_operation)))
    with pytest.raises(OSError, match=expected):
        deletion.actual_recycle(record.path)
    assert Path(record.path).exists()


@pytest.mark.skipif(os.name != 'nt', reason='本机 Windows 回收站实测')
def test_real_windows_recycles_only_the_isolated_product_directory(deletion):
    record = deletion.create('回收站验证商品-123')
    original = Path(record.path).resolve(strict=True)
    assert original.is_relative_to(deletion.root.resolve(strict=True))
    assert original.name == '回收站验证商品-123'
    neighbor = deletion.root / '相邻文件不能删除.txt'
    neighbor.write_text('保留', encoding='utf-8')
    deletion.ns['_move_path_to_recycle_bin'] = deletion.actual_recycle
    response = deletion.client.get('/menu_delete', query_string={'_id': record.id})
    assert response.json['success'], response.json
    assert not original.exists()
    assert not deletion.Record.select().exists()
    assert neighbor.read_text(encoding='utf-8') == '保留'

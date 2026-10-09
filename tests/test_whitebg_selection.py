# -*- coding: utf-8 -*-
"""商品白底图选择：隔离数据库、真实临时图片，不访问平台或用户数据库。"""
import ast
from datetime import datetime
import json
from pathlib import Path
import sys
import threading
from types import SimpleNamespace

from flask import jsonify
from PIL import Image
import pytest

from test_capture_attribute_storage import storage, definitions

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'taobao-publisher'))
from src import product_media
from src.sidecar.media_routes import create_media_blueprint
from src.sidecar.whitebg_service import WhiteBgService, processing_options
from taobao_publish import desktop, local_source


@pytest.fixture
def selection(storage):
    ns = storage.ns
    ns.update(_shop_account_lock=threading.RLock(),
              _upload_tasks={}, _upload_tasks_lock=threading.RLock(),
              _taobao_tasks={}, _taobao_tasks_lock=threading.RLock())
    exec(definitions(ROOT / 'tauri-app/python-sidecar/app.py', {
        '_record_edit_blocked', '_product_edit_revision',
    }), ns)
    # 不跑模型，仅把任务留在 pending，覆盖实际服务的生成互斥判断。
    jobs = WhiteBgService(lambda: Path(storage.product['download_path']).parent,
                         thread_factory=lambda **kw: SimpleNamespace(start=lambda: None))
    ns['app'].register_blueprint(create_media_blueprint(
        record_model=storage.Record, active_account=lambda: {},
        resolve_data_file=lambda name: name, edit_blocked=ns['_record_edit_blocked'],
        product_revision=ns['_product_edit_revision'], account_lock=ns['_shop_account_lock'], whitebg=jobs,
    ))
    info = ns['_import_capture_product_record'](storage.product)
    record_id = info['record_id']
    root = Path(storage.product['download_path'])
    (root / '自选图片').mkdir()
    (root / '主图').mkdir()
    (root / '白底图').mkdir()
    for path, color in [('白底图.jpg', 'white'), ('主图/白底图.jpg', 'red'),
                        ('白底图/自动图.jpg', 'yellow'), ('自选图片/选中的蓝色.png', 'blue')]:
        Image.new('RGB', (640, 640), color).save(root / path)
    return SimpleNamespace(**storage.__dict__, record_id=record_id, root=root, jobs=jobs,
                           selected='自选图片/选中的蓝色.png')


def choose(case, path):
    return case.client.put(f'/api/products/{case.record_id}/media/white-background', json={'path': path})


def record(case):
    return case.Record.get_by_id(case.record_id)


def douyin_white(case, row=None):
    source = ROOT / 'src/utils.py'
    node = next(n for n in ast.parse(source.read_text(encoding='utf-8')).body
                if isinstance(n, ast.FunctionDef) and n.name == 'get_white_pic')
    ns = {'__package__': 'src', 'os': __import__('os')}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(source), 'exec'), ns)
    return ns['get_white_pic'](row or record(case), [{'path': '原有SKU备用图'}])


def test_manual_choice_persists_and_all_local_publish_projections_use_it(selection):
    response = choose(selection, selection.selected)
    assert response.status_code == 200 and response.json['success'], response.json
    saved = record(selection)
    assert saved.white_bg_path == selection.selected
    assert response.json['data']['selection'] == {'path': selection.selected, 'valid': True, 'error': ''}
    expected = (selection.root / selection.selected).resolve()
    assert Path(douyin_white(selection)) == expected
    assert Path(desktop._asset_paths(selection.root, saved.white_bg_path)['white_bg']) == expected
    local = local_source.local_product_from_record(saved.__data__, product_dir=str(selection.root))
    assert Path(local.white_bg_image) == expected
    # 既有自动文件不被重命名、覆盖或删除。
    with Image.open(selection.root / '白底图.jpg') as image:
        assert image.getpixel((1, 1)) == (255, 255, 255)


def test_restore_automatic_reuses_existing_rules_without_deleting_selected_file(selection):
    assert choose(selection, selection.selected).json['success']
    assert choose(selection, '').json['success']
    assert record(selection).white_bg_path == ''
    assert Path(douyin_white(selection)) == selection.root / '白底图.jpg'
    assert Path(desktop._asset_paths(selection.root)['white_bg']) == selection.root / '白底图.jpg'
    assert (selection.root / selection.selected).is_file()


def test_old_record_without_setting_preserves_douyin_sku_fallback(selection):
    # 仅移动本测试建立的文件，验证旧规则保持不变。
    (selection.root / '白底图.jpg').rename(selection.root / '原根白底暂存.jpg')
    assert douyin_white(selection) == '原有SKU备用图'


@pytest.mark.parametrize('path', ['../外部.jpg', '/外部.jpg', 'C:/外部.jpg',
                                  '自选图片\\选中的蓝色.png', '自选图片//选中的蓝色.png',
                                  '不存在.jpg', '主图', None, 123])
def test_invalid_choice_cannot_replace_existing_setting(selection, path):
    assert choose(selection, selection.selected).json['success']
    response = choose(selection, path)
    assert response.status_code == 400 and response.json['success'] is False
    assert record(selection).white_bg_path == selection.selected


def test_corrupt_image_cannot_be_selected(selection):
    (selection.root / '假图片.jpg').write_text('这不是图片', encoding='utf-8')
    assert choose(selection, '假图片.jpg').status_code == 400
    assert not record(selection).white_bg_path


def test_missing_manual_image_is_reported_and_never_silently_replaced(selection):
    assert choose(selection, selection.selected).json['success']
    source = selection.root / selection.selected
    source.rename(source.with_name('已移动.png'))
    state = product_media.white_bg_selection(record(selection).__data__)
    assert state['path'] == selection.selected and state['valid'] is False
    assert '重新选择或恢复自动选择' in state['error']
    with pytest.raises(ValueError, match='重新选择或恢复自动选择'):
        douyin_white(selection)
    with pytest.raises(ValueError, match='重新选择或恢复自动选择'):
        local_source.local_product_from_record(record(selection).__data__, product_dir=str(selection.root))
    with pytest.raises(ValueError, match='重新选择或恢复自动选择'):
        desktop._asset_paths(selection.root, selection.selected)
    assert choose(selection, '').json['success']


def test_setting_is_product_scoped_and_capture_refresh_preserves_manual_choice(selection):
    assert choose(selection, selection.selected).json['success']
    second = selection.Record.create(name='其它商品', path=str(selection.root.parent), type=2,
                                     status=0, content='[]', update_time=datetime.now())
    assert not second.white_bg_path
    selection.ns['_import_capture_product_record'](selection.product)
    assert record(selection).white_bg_path == selection.selected


def test_choice_changes_publish_revision_and_running_publish_blocks_edits(selection):
    before = selection.ns['_product_edit_revision'](record(selection).__data__)
    response = choose(selection, selection.selected)
    assert response.json['data']['record_revision'] != before
    selection.ns['_taobao_tasks']['running'] = {'record_id': selection.record_id, 'status': 'running'}
    response = choose(selection, '')
    assert response.status_code == 409 and response.json['success'] is False
    assert record(selection).white_bg_path == selection.selected


def test_readonly_database_does_not_report_saved_selection(selection):
    selection.database.execute_sql('PRAGMA query_only = ON')
    try:
        response = choose(selection, selection.selected)
        assert response.status_code == 500 and response.json['success'] is False
        assert not record(selection).white_bg_path
    finally:
        selection.database.execute_sql('PRAGMA query_only = OFF')


def test_generation_in_progress_blocks_only_that_products_selection(selection):
    selection.jobs.start(str(selection.root), processing_options({}), record_id=selection.record_id)
    response = choose(selection, selection.selected)
    assert response.status_code == 409 and '图片正在生成' in response.json['msg']
    assert not record(selection).white_bg_path
    (selection.root / '另一个目录').mkdir()
    other_data = {key: value for key, value in record(selection).__data__.items() if key != 'id'}
    other_data.update(name='另一个商品', path=str(selection.root / '另一个目录'), content='[]')
    other = selection.Record.create(**other_data)
    response = selection.client.put(f'/api/products/{other.id}/media/white-background', json={'path': ''})
    assert response.json['success']


def test_invalid_product_revision_fails_before_persisting_choice(selection):
    selection.Record.update(content='broken JSON').where(selection.Record.id == selection.record_id).execute()
    response = choose(selection, selection.selected)
    assert response.status_code == 400 and response.json['success'] is False
    assert not record(selection).white_bg_path


def test_zero_updated_rows_cannot_report_success(selection, monkeypatch):
    monkeypatch.setattr(selection.Record, 'save', lambda *args, **kwargs: 0)
    response = choose(selection, selection.selected)
    assert response.status_code == 400 and response.json['success'] is False
    assert '记录已变化' in response.json['msg']
    assert not record(selection).white_bg_path


def test_migration_adds_nullable_choice_without_changing_existing_rows(storage):
    storage.database.execute_sql('DROP TABLE record')
    storage.database.execute_sql('CREATE TABLE record (id INTEGER PRIMARY KEY, title TEXT, content TEXT)')
    storage.database.execute_sql('INSERT INTO record (title, content) VALUES (?, ?)', ('旧商品', '旧资料'))
    storage.migrate()
    storage.migrate()
    row = storage.database.execute_sql('SELECT title,content,white_bg_path FROM record').fetchone()
    assert row == ('旧商品', '旧资料', None)


def test_regeneration_does_not_prune_an_explicitly_selected_image(selection, monkeypatch):
    from src.whitebg import product
    chosen = selection.root / '白底图/手动选图.PNG'
    stale = selection.root / '白底图/过期图.png'
    Image.new('RGB', (640, 640), 'green').save(chosen)
    Image.new('RGB', (640, 640), 'red').save(stale)
    original = chosen.read_bytes()

    def process_one(*args, **kwargs):
        return {'source': 'fixture', 'white_ok': False, 'white_path': '',
                'square_ok': False, 'square_path': '', 'name': '模拟拒绝', 'code': 'no_sock_found'}

    monkeypatch.setattr(product, '_process_one', process_one)
    product.process_product_dir(str(selection.root), processor=SimpleNamespace(model_dir='fixture'),
                                preserve_paths=['白底图/手动选图.PNG'])
    assert chosen.read_bytes() == original
    assert not stale.exists()

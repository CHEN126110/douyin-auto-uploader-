# -*- coding: utf-8 -*-
"""只使用临时商品目录和 Flask test_client，不连接运行中的应用或浏览器。"""
import threading
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace

from flask import Flask
from PIL import Image
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src import product_media as media
from src.sidecar.media_routes import create_media_blueprint
from src.sidecar.whitebg_service import WhiteBgService


@pytest.fixture
def product(tmp_path):
    root = tmp_path / '商品'
    folder = root / '主图' / '800'
    folder.mkdir(parents=True)
    for name in ['图10.jpg', '图2.jpg', '图1.jpg']:
        Image.new('RGB', (640, 480), 'red').save(folder / name)
    (root / 'SKU').mkdir()
    (root / '说明.json').write_text('{"name":"测试"}', encoding='utf-8')
    return {'id': 7, 'name': '测试商品', 'path': str(root)}


def observation(product, status='located'):
    path = Path(product['path']) / '主图/800/图1.jpg'
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return {'path': str(path), 'role': 'main', 'name': f'tb_7_main_1_{digest[:32]}.jpg',
            'sha256': digest, 'status': status,
            'folder_path': ['全部图片', '远端商品', '自定义目录', '主图'] if status == 'located' else []}


def test_browse_actual_children_natural_sort_and_empty_directory(product):
    root = media.list_directory(product, '')
    assert {e['name'] for e in root['entries'] if e['kind'] == 'folder'} == {'主图', 'SKU'}
    children = media.list_directory(product, '主图/800')
    assert [e['name'] for e in children['entries']] == ['图1.jpg', '图2.jpg', '图10.jpg']
    assert children['parent'] == '主图'
    assert media.list_directory(product, 'SKU')['entries'] == []
    assert len(media.list_directory(product, '主图/800', offset=1, limit=1)['entries']) == 1


@pytest.mark.parametrize('path', ['../outside', '/outside', '主图/../SKU', 'C:/Windows', '主图\\800', '主图//800', '.'])
def test_rejects_paths_outside_product(product, path):
    with pytest.raises(ValueError):
        media.list_directory(product, path)


def test_receipts_survive_restart_are_account_scoped_and_detect_content_changes(product, tmp_path):
    storage = tmp_path / 'registry'
    first = observation(product, 'uploaded_unlocated')
    located = observation(product)
    located['url'] = 'https://example.invalid/private?token=never-save-this'
    media.save_receipts(storage, product, 'taobao-A', [first, located])
    records = media.read_receipts(storage, product, 'taobao-A')
    assert len(records) == 1 and records[0]['folder_path'] == located['folder_path']
    assert not media.read_receipts(storage, product, 'taobao-B')
    assert 'token' not in next(storage.glob('*.json')).read_text(encoding='utf-8')
    row = media.list_directory(product, '主图/800', receipts=records)['entries'][0]
    assert row['receipts'][0]['content_matches'] is True
    Image.new('RGB', (600, 600), 'blue').save(first['path'])
    row = media.list_directory(product, '主图/800', receipts=records)['entries'][0]
    assert row['receipts'][0]['content_matches'] is False
    media.save_receipts(storage, product, 'taobao-A', [observation(product, 'uploaded_unlocated')])
    latest = media.read_receipts(storage, product, 'taobao-A')
    assert len(latest) == 1 and latest[0]['status'] == 'uploaded_unlocated' and latest[0]['folder_path'] == []


def test_corrupt_registry_is_not_treated_as_no_uploads(product, tmp_path):
    media.save_receipts(tmp_path / 'registry', product, 'A', [observation(product)])
    target = next((tmp_path / 'registry').glob('*.json'))
    target.write_text('broken JSON', encoding='utf-8')
    with pytest.raises(ValueError):
        media.read_receipts(tmp_path / 'registry', product, 'A')


def test_preview_does_not_modify_original_or_serve_non_images(product):
    image = Path(product['path']) / '主图/800/图1.jpg'
    before = image.read_bytes()
    with Image.open(media.preview_image(product, '主图/800/图1.jpg', thumbnail=True)) as thumb:
        assert thumb.size == (320, 240)
    assert before == image.read_bytes()
    with pytest.raises(ValueError):
        media.preview_image(product, '说明.json', thumbnail=False)


def test_junction_or_symlink_is_not_followed(product, tmp_path, monkeypatch):
    target = Path(product['path']) / '主图'
    real_lstat = Path.lstat
    def lstat(path):
        info = real_lstat(path)
        if path == target:
            return SimpleNamespace(st_mode=info.st_mode, st_file_attributes=0x400)
        return info
    monkeypatch.setattr(Path, 'lstat', lstat)
    with pytest.raises(ValueError, match='联接'):
        media.media_path(product, '主图/800/图1.jpg')


def test_http_routes_use_registered_root_and_expected_account(product, tmp_path):
    class Missing(Exception): pass
    class Record:
        DoesNotExist = Missing
        @classmethod
        def get_by_id(cls, value):
            if value != 7: raise Missing()
            return SimpleNamespace(__data__=product)
    app = Flask('isolated-media-api')
    app.register_blueprint(create_media_blueprint(
        record_model=Record, active_account=lambda: {'platform': 'taobao', 'profile_name': 'A'},
        resolve_data_file=lambda name: tmp_path / name, edit_blocked=lambda _id: None,
        product_revision=lambda row: '', account_lock=threading.RLock(),
        whitebg=WhiteBgService(lambda: tmp_path),
    ))
    client = app.test_client()
    response = client.get('/api/products/7/media', query_string={'path': '主图/800', 'account_profile': 'A'})
    assert response.status_code == 200 and len(response.json['data']['entries']) == 3
    assert client.get('/api/products/7/media?account_profile=B').status_code == 409
    assert client.get('/api/products/8/media').status_code == 404
    assert client.get('/api/products/7/media?path=../private').status_code == 400
    response = client.get('/api/products/7/media/image', query_string={'path': '主图/800/图1.jpg'})
    assert response.status_code == 200 and response.mimetype == 'image/jpeg'
    assert response.headers['Cache-Control'] == 'no-store'
    assert client.get('/api/products/7/media/image?path=../private').status_code == 400

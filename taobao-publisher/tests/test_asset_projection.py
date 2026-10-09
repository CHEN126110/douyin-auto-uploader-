# -*- coding: utf-8 -*-
"""只读素材投影：有效路径、角色、顺序与明确空值，不触碰平台。"""
import json
from pathlib import Path
from types import SimpleNamespace

from PIL import Image
import pytest

from taobao_publish.local_source import discover_product_assets, local_product_from_record
from taobao_publish.mapping import build_publish_item
from taobao_publish.models import LocalProduct


def image(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new('RGB', (800, 800), 'white').save(path)
    return str(path)


def test_square_assets_reach_product_without_changing_original_files(tmp_path):
    main = image(tmp_path / '主图/主图_1.jpg')
    sku = image(tmp_path / 'SKU/白色.jpg')
    square = image(tmp_path / 'SKU_1x1/白色.jpg')
    detail1 = image(tmp_path / '详情页/详情_1.jpg')
    detail2 = image(tmp_path / '详情页/详情_10.jpg')
    before = {str(p): p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    row = {'id': 1, 'name': '商品一', 'path': str(tmp_path),
           'content': json.dumps([{'name': '白色', 'path': sku, 'price': 10}])}
    discovery = discover_product_assets(tmp_path)
    assert discovery.square_images == [square]
    assert discovery.to_dict()['square_count'] == 1
    local = local_product_from_record(row, product_dir=str(tmp_path))
    assert local.square_images == [square]
    assert local.main_images == [main]
    assert local.detail_images == [detail1, detail2]
    assert local.skus[0].path == sku  # 只保存事实，不按同名猜图片替换关系。
    assert before == {str(p): p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}


def test_sku_images_come_from_the_requested_rows_and_preserve_order():
    local = LocalProduct(record_id=1, record_name='商品一')
    request = {'skus': [
        {'spec_values': {'颜色分类': '白色'}, 'image_path': '白色.jpg'},
        {'spec_values': {'颜色分类': '黑色'}, 'image_path': '黑色.jpg'},
        {'spec_values': {'颜色分类': '白色套装'}, 'image_path': '白色.jpg'},
    ]}
    item = build_publish_item(local, request).item
    assert item.images.sku == ['白色.jpg', '黑色.jpg']
    assert [sku.image_path for sku in item.skus] == ['白色.jpg', '黑色.jpg', '白色.jpg']
    request['images'] = {'sku': []}
    assert build_publish_item(local, request).item.images.sku == []


@pytest.mark.parametrize('role', ['主图', '详情页', 'SKU', 'SKU_1x1', '白底图'])
def test_symlink_directory_is_not_scanned_for_upload(tmp_path, role):
    product = tmp_path / '商品'
    product.mkdir()
    outside = tmp_path / '其它资料'
    image(outside / '文件.jpg')
    try:
        (product / role).symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip('此 Windows 环境没有创建符号链接的权限')
    with pytest.raises(ValueError, match='越出|符号链接|重解析点'):
        discover_product_assets(product)


def test_symlink_file_inside_main_directory_is_rejected(tmp_path):
    real = tmp_path / '主图/正常.jpg'
    image(real)
    try:
        (real.parent / '链接.jpg').symlink_to(real)
    except OSError:
        pytest.skip('此 Windows 环境没有创建符号链接的权限')
    with pytest.raises(ValueError, match='符号链接|重解析点'):
        discover_product_assets(tmp_path)


@pytest.mark.parametrize('target', ['root', 'directory', 'image'])
def test_windows_reparse_attribute_blocks_asset_scan_without_link_privileges(tmp_path, monkeypatch, target):
    file = tmp_path / '主图/文件.jpg'
    image(file)
    guarded = {'root': tmp_path, 'directory': file.parent, 'image': file}[target]
    original = Path.lstat

    def lstat(path, *args, **kwargs):
        result = original(path, *args, **kwargs)
        if path.absolute() == guarded.absolute():
            return SimpleNamespace(st_mode=result.st_mode,
                                   st_file_attributes=getattr(result, 'st_file_attributes', 0) | 0x400)
        return result

    monkeypatch.setattr(Path, 'lstat', lstat)
    with pytest.raises(ValueError, match='重解析点'):
        discover_product_assets(tmp_path)

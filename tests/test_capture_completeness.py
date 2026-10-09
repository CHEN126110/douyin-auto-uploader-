"""采集完整性与导入诊断；只执行生产函数，浏览器/HTTP/下载均隔离。"""
import ast
from copy import deepcopy
from datetime import datetime
import json
import os
from pathlib import Path
import re
import subprocess
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from test_capture_attribute_storage import storage

APP = Path(__file__).resolve().parents[1] / 'tauri-app/python-sidecar/app.py'


@pytest.fixture
def capture(monkeypatch):
    names = {'_capture_taobao_tmall_product_for_store', '_extract_taobao_ice_data',
             '_extract_taobao_tmall_product_snapshot'}
    nodes = [node for node in ast.parse(APP.read_text(encoding='utf-8')).body
             if isinstance(node, ast.FunctionDef) and node.name in names]
    ns = dict(json=json, re=re, datetime=datetime, app=SimpleNamespace(logger=Mock()),
              system_time=SimpleNamespace(sleep=Mock()), _mtop_product_cache={},
              _extract_capture_product_id=lambda url: str(url).split('id=')[-1] if 'id=' in str(url) else '')
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(APP), 'exec'), ns)
    url = 'https://example.invalid/item?id=17'
    page = SimpleNamespace(url=url, run_js=Mock())
    def navigate(target, **_): page.url = target
    page.get = Mock(side_effect=navigate)
    complete = {'title': '页面商品', 'price': {'current': 20.8},
                'main_images': ['https://img.example.invalid/main.jpg'],
                'detail_images': ['https://img.example.invalid/detail.jpg'],
                'sku_info': [{'index': 1, 'name': '白色+均码', 'price': 20.8,
                              'image': 'https://img.example.invalid/white.jpg'}], 'parameters': []}
    ns['_extract_taobao_ice_data'] = Mock(return_value=None)
    ns['_extract_taobao_tmall_product_snapshot'] = Mock(side_effect=lambda *_, **kwargs: deepcopy(complete))
    ns['_get_browser_cookies_for_http'] = Mock(return_value='offline-test-only')
    ns['_capture_product_attributes'] = Mock()
    ns['_collect_taobao_desc_images_via_browser'] = Mock(return_value=[])
    ns['_fetch_taobao_desc_images'] = Mock(return_value=[])
    ns['_download_capture_product_images'] = Mock(return_value='isolated-download-directory')
    html = '<title>HTTP商品</title>"priceMoney":"2080","images":["https://img.example.invalid/main.jpg"]' + ' ' * 10001
    response = SimpleNamespace(read=lambda: html.encode('utf-8'))
    monkeypatch.setattr('urllib.request.urlopen', Mock(return_value=response))
    return SimpleNamespace(ns=ns, page=page, url=url, complete=complete)


def test_http_price_and_images_do_not_skip_missing_skus(capture):
    result = capture.ns['_capture_taobao_tmall_product_for_store'](capture.page, capture.url, {})
    assert result['sku_info'] == capture.complete['sku_info']
    assert result['title'] == 'HTTP商品'
    assert result['price']['current'] == 20.8
    capture.ns['_extract_taobao_tmall_product_snapshot'].assert_called_once()
    capture.ns['_download_capture_product_images'].assert_called_once()


def test_missing_skus_are_not_reported_as_completed_capture(capture):
    capture.complete['sku_info'] = []
    with pytest.raises(ValueError, match='SKU规格'):
        capture.ns['_capture_taobao_tmall_product_for_store'](capture.page, capture.url, {})
    capture.ns['_download_capture_product_images'].assert_not_called()


def test_ice_price_does_not_skip_missing_skus(capture):
    incomplete = deepcopy(capture.complete)
    incomplete['sku_info'] = []
    capture.ns['_extract_taobao_ice_data'].return_value = incomplete
    result = capture.ns['_capture_taobao_tmall_product_for_store'](capture.page, capture.url, {})
    assert result['sku_info'] == capture.complete['sku_info']


def test_store_item_changes_page_before_reading_ice_data(capture):
    capture.page.url = 'https://example.invalid/item?id=99'
    def ice(page):
        assert page.url == capture.url
        return deepcopy(capture.complete)
    capture.ns['_extract_taobao_ice_data'].side_effect = ice
    result = capture.ns['_capture_taobao_tmall_product_for_store'](capture.page, capture.url, {})
    capture.page.get.assert_called_once_with(capture.url, timeout=30)
    assert result['sku_info'] == capture.complete['sku_info']


def test_download_disabled_is_respected(capture):
    capture.ns['_extract_taobao_ice_data'].return_value = deepcopy(capture.complete)
    result = capture.ns['_capture_taobao_tmall_product_for_store'](capture.page, capture.url, {'download_images': False})
    assert result['download_path'] is None
    capture.ns['_download_capture_product_images'].assert_not_called()


def test_http_partial_result_also_collects_missing_detail_images(capture):
    capture.complete['detail_images'] = []
    capture.ns['_collect_taobao_desc_images_via_browser'].return_value = ['https://img.example.invalid/detail-lazy.jpg']
    result = capture.ns['_capture_taobao_tmall_product_for_store'](capture.page, capture.url, {})
    assert result['detail_images'] == ['https://img.example.invalid/detail-lazy.jpg']
    capture.ns['_collect_taobao_desc_images_via_browser'].assert_called_once()


def test_ice_detail_url_is_used_only_after_the_visible_details_are_empty(capture):
    capture.complete['detail_images'] = []
    capture.complete['_pc_desc_url'] = 'https://example.invalid/description'
    capture.ns['_extract_taobao_ice_data'].return_value = deepcopy(capture.complete)
    capture.ns['_fetch_taobao_desc_images'].return_value = ['https://img.example.invalid/detail.jpg']
    result = capture.ns['_capture_taobao_tmall_product_for_store'](capture.page, capture.url, {})
    assert result['detail_images'] == ['https://img.example.invalid/detail.jpg']
    assert '_pc_desc_url' not in result
    capture.ns['_collect_taobao_desc_images_via_browser'].assert_called_once()
    capture.ns['_fetch_taobao_desc_images'].assert_called_once_with(capture.page, 'https://example.invalid/description')


@pytest.mark.parametrize('sku_base,expected_count', [(None, 0), ({'skus': [], 'props': []}, 1)])
def test_default_sku_requires_explicit_no_variants_evidence(sku_base, expected_count):
    tree = ast.parse(APP.read_text(encoding='utf-8'))
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                    and node.name == '_extract_taobao_ice_data')
    call = next(node for node in ast.walk(function) if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute) and node.func.attr == 'run_js')
    source = ast.literal_eval(call.args[0])
    data = {'item': {'title': '样例商品', 'images': ['https://img.example.invalid/main.jpg']},
            'skuCore': {'sku2info': {'0': {'price': {'priceMoney': '2080'}}}}}
    if sku_base is not None: data['skuBase'] = sku_base
    script = 'global.window={__ICE_APP_CONTEXT__:{loaderData:{home:{data:{res:' + json.dumps(data) + '}}}}};' \
        + 'process.stdout.write(new Function(' + json.dumps(source) + ')());'
    result = subprocess.run(['node', '-e', script], capture_output=True, text=True, encoding='utf-8', check=True)
    from src.taobao_capture import from_ice
    assert len(from_ice(json.loads(result.stdout))['sku_info']) == expected_count


def test_dom_cannot_infer_a_default_sku_just_from_a_main_picture(capture):
    tree = ast.parse(APP.read_text(encoding='utf-8'))
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                    and node.name == '_extract_taobao_tmall_product_snapshot')
    ns = dict(capture.ns, _extract_text_by_selectors=lambda *_: '样例商品')
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(APP), 'exec'), ns)
    capture.page.run_js.side_effect = [20.8, {'main': ['https://img.example.invalid/main.jpg'], 'detail': []}, {'groups': []}]
    result = ns['_extract_taobao_tmall_product_snapshot'](capture.page, capture.url)
    assert result['main_images'] and result['sku_info'] == []


def test_single_capture_reuses_the_already_downloaded_product_path(tmp_path):
    tree = ast.parse(APP.read_text(encoding='utf-8'))
    start = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'start_capture')
    worker = next(node for node in ast.walk(start) if isinstance(node, ast.FunctionDef) and node.name == 'run_capture_task')
    body = next(node for node in worker.body if isinstance(node, ast.Try)).body
    index = next(index for index, node in enumerate(body) if isinstance(node, ast.Assign)
                 and any(isinstance(target, ast.Name) and target.id == 'download_path' for target in node.targets))
    ns = {'product_data': {'download_path': str(tmp_path)}, 'options': {'download_images': True}}
    # 执行真实任务中的路径选择及下载分支；如果重复进入下载，未注入的网络依赖会使测试失败。
    exec(compile(ast.Module(body=body[index:index + 2], type_ignores=[]), str(APP), 'exec'), ns)
    assert ns['download_path'] == str(tmp_path)


@pytest.mark.parametrize('route', ['helper', 'single'])
def test_existing_main_images_and_missing_skus_have_a_specific_import_error(storage, route):
    product = storage.product
    sku = Path(product['download_path']) / 'SKU/模型袜子.jpg'
    # 测试自己的临时样本，移动到主图目录模拟用户现象。
    main = sku.parent.parent / '主图'
    main.mkdir()
    sku.rename(main / '主图_01.jpg')
    product['sku_info'] = []
    if route == 'helper':
        with pytest.raises(Exception, match='SKU规格'):
            storage.ns['_import_capture_product_record'](product)
    else:
        response = storage.client.post('/api/capture/import', json={'task_id': 'isolated', 'product_data': product})
        assert response.json['success'] is False
        assert 'SKU规格' in response.json['message']
        assert '未找到图片文件' not in response.json['message']
    assert storage.Record.select().count() == 0
    assert (main / '主图_01.jpg').exists()

"""规格身份、DOM 层级、素材对应和重复导入；浏览器/图片服务全部隔离。"""
from copy import deepcopy
import hashlib
from io import BytesIO
import json
from pathlib import Path
import sys
from types import SimpleNamespace

from PIL import Image
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'taobao-publisher'))
sys.path.insert(0, str(ROOT / 'taobao-publisher/tests'))
from test_candidate_form_adapters import browser
from test_capture_attribute_storage import storage
from src import taobao_capture as capture


def ice():
    return {'item': {'title': '测试袜子', 'images': ['https://img.example.invalid/main.jpg']},
            'skuBase': {'props': [
                {'pid': '1', 'name': '颜色分类', 'values': [
                    {'vid': '1', 'name': '白色', 'image': '//img.example.invalid/white.jpg'},
                    {'vid': '2', 'name': '黑色', 'image': '//img.example.invalid/black.jpg'}]},
                {'pid': '2', 'name': '尺码', 'values': [{'vid': '1', 'name': 'M'}, {'vid': '2', 'name': 'L'}]}],
                'skus': [{'skuId': sid, 'propPath': path} for sid, path in
                         [('101', '1:1;2:1'), ('102', '1:1;2:2'), ('103', '1:2;2:1')]]},
            'skuCore': {'sku2info': {'0': {'price': {'priceMoney': '100'}},
                                    '101': {'price': {'priceMoney': '450'}},
                                    '102': {'price': {'priceMoney': '650'}}, '103': {}}}}


def test_structured_skus_preserve_only_real_combinations_and_namespaced_images():
    rows = capture.from_ice(ice())['sku_info']
    assert [row['name'] for row in rows] == ['白色 / M', '白色 / L', '黑色 / M']
    assert [row['sku_id'] for row in rows] == ['101', '102', '103']
    assert [row['price'] for row in rows] == [4.5, 6.5, None]
    assert [row['image'] for row in rows] == ['https://img.example.invalid/white.jpg'] * 2 + ['https://img.example.invalid/black.jpg']
    assert len({row['sku_key'] for row in rows}) == 3


def test_duplicate_transport_row_uses_sku_identity_but_conflicting_identity_fails():
    value = ice()
    value['skuBase']['skus'].append(deepcopy(value['skuBase']['skus'][0]))
    assert len(capture.from_ice(value)['sku_info']) == 3
    value['skuBase']['skus'][-1]['propPath'] = '1:2;2:1'
    with pytest.raises(ValueError, match='冲突'): capture.from_ice(value)


@pytest.mark.parametrize('path', ['1:1', '1:1;2:unknown', '1:1;1:2;2:1'])
def test_incomplete_property_path_cannot_become_a_default_or_partial_sku(path):
    value = ice()
    value['skuBase']['skus'][0]['propPath'] = path
    with pytest.raises(ValueError, match='规格路径'): capture.from_ice(value)


def test_same_name_different_sku_ids_are_not_dropped():
    value = ice()
    value['skuBase']['skus'].append({'skuId': '104', 'propPath': '1:1;2:1'})
    with pytest.raises(ValueError, match='可区分'): capture.from_ice(value)


def test_no_variants_requires_explicit_structure_and_labels_main_image_provenance():
    value = ice()
    value['skuBase'] = None
    assert capture.from_ice(value)['sku_info'] == []
    value['skuBase'] = {'props': [], 'skus': []}
    result = capture.from_ice(value)['sku_info']
    assert len(result) == 1 and result[0]['image_source'] == 'explicit_no_variants'


COLORS = ['【浅灰】', '【白色】', '【米杏】', '【黑色】', '【深灰】']
DOM = r'''(() => {
  const colors=COLORS;
  const axis=(name,values,images)=>`<div class="skuItem--shell"><div class="skuItem--axis">
    <div class="ItemLabel"><span><span>${name}</span><button type="button">切换大图模式</button></span></div>
    ${values.map((value,index)=>`<div class="valueItem"><img src="${images?'https://img.example.invalid/color-'+index+'.webp':''}">
       <button type="button"><span title="${value}">${value}</span></button></div>`).join('')}
    </div></div>`;
  document.body.innerHTML='<div class="gallery"><img src="https://img.example.invalid/main.jpg"></div>'
    +'<div id="skuOptionsArea">'+axis('颜色分类',colors,true)+axis('尺码',['均码'],false)+'</div>';
})()'''.replace('COLORS', json.dumps(COLORS))


def dom_payload(browser):
    return browser.evaluate('(new Function(' + json.dumps(capture.DOM_GROUPS_JS) + '))()')


def test_nested_option_button_and_outer_wrappers_produce_five_skus_not_twenty_four(browser):
    browser.evaluate(DOM)
    # 旧“组 + valueItem/li/button”遍历可复现本次 24 条；此断言证明夹具覆盖根因。
    count = browser.evaluate("Array.from(document.querySelectorAll('#skuOptionsArea [class*=skuItem]')).reduce((sum,el)=>sum+el.querySelectorAll('[class*=valueItem],li,button').length-1,0)")
    assert count == 24
    groups = dom_payload(browser)
    assert [group['name'] for group in groups['groups']] == ['颜色分类', '尺码']
    rows = capture.from_dom_groups(groups)
    assert [row['name'] for row in rows] == [color + ' / 均码' for color in COLORS]
    assert [row['image'] for row in rows] == ['https://img.example.invalid/color-' + str(index) + '.webp' for index in range(5)]
    assert all(row['price'] is None for row in rows), '页面起价不等于所有规格的售价'


def test_hidden_duplicate_widgets_and_missing_sku_image_never_use_main_gallery(browser):
    browser.evaluate(DOM)
    browser.evaluate("const clone=document.querySelector('#skuOptionsArea').cloneNode(true);clone.style.display='none';document.body.append(clone);document.querySelector('.valueItem img').remove()")
    rows = capture.from_dom_groups(dom_payload(browser))
    assert len(rows) == 5 and rows[0]['image'] == ''
    assert all('main.jpg' not in row['image'] for row in rows)


def test_multiple_variable_dom_axes_need_actual_sellable_combinations():
    groups = {'groups': [{'name': name, 'values': [{'name': v} for v in values]}
                         for name, values in [('颜色', ['白', '黑']), ('尺码', ['M', 'L'])]]}
    with pytest.raises(ValueError, match='可售SKU组合'): capture.from_dom_groups(groups)


@pytest.fixture
def asset_case(tmp_path, monkeypatch):
    stream = BytesIO()
    Image.new('RGB', (80, 80), 'white').save(stream, format='PNG')
    binary = stream.getvalue()
    calls, errors = [], set()
    class Session:
        def __init__(self): self.headers = {}
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def get(self, url, **kwargs):
            calls.append(url)
            if url in errors: raise OSError('本地模型下载失败')
            return SimpleNamespace(content=binary, raise_for_status=lambda: None)
    monkeypatch.setattr('requests.Session', Session)
    product = {'product_id': '123', 'title': '商品', 'main_images': ['https://img.example.invalid/main.jpg'],
               'detail_images': [], 'sku_info': capture.from_ice(ice())['sku_info']}
    return SimpleNamespace(product=product, base=tmp_path/'products', calls=calls, errors=errors, binary=binary)


def test_same_image_used_by_two_real_skus_downloads_once_but_keeps_both_skus(asset_case):
    case = asset_case
    folder = capture.download_assets(case.product, 'https://example.invalid/item', case.base)
    case.product['download_path'] = folder
    rows = capture.bind_local_files(case.product)
    assert len(rows) == 3 and len({row['path'] for row in rows}) == 3
    assert case.calls.count('https://img.example.invalid/white.jpg') == 1
    assert [row['name'] for row in rows] == ['白色 / M', '白色 / L', '黑色 / M']
    assert [row['price'] for row in rows] == [4.5, 6.5, '']
    assert all(Path(row['path']).suffix == '.png' for row in rows), '扩展名来自真实图片格式'
    (Path(folder) / 'SKU/旧的多余图片.jpg').write_bytes(case.binary)
    assert len(capture.bind_local_files(case.product)) == 3


def test_missing_image_is_not_filled_from_main_and_does_not_touch_old_directory(asset_case):
    case = asset_case
    case.product['sku_info'][0]['image'] = ''
    original = case.base / 'ID-123/SKU/原图.jpg'
    original.parent.mkdir(parents=True)
    original.write_bytes(case.binary)
    with pytest.raises(ValueError, match='未用主图替代'):
        capture.download_assets(case.product, 'https://example.invalid/item', case.base)
    assert original.read_bytes() == case.binary and case.calls == []


def test_download_failure_preserves_original_files_and_success_archives_them(asset_case):
    case = asset_case
    original = case.base / 'ID-123/SKU/原图.jpg'
    original.parent.mkdir(parents=True)
    original.write_bytes(case.binary)
    case.errors.add('https://img.example.invalid/white.jpg')
    with pytest.raises(ValueError, match='原商品目录已保留'):
        capture.download_assets(case.product, 'https://example.invalid/item', case.base)
    assert original.read_bytes() == case.binary
    case.errors.clear()
    capture.download_assets(case.product, 'https://example.invalid/item', case.base)
    archived = list((case.base.parent/'.capture-backups').glob('ID-123-*/SKU/原图.jpg'))
    assert len(archived) == 1 and archived[0].read_bytes() == case.binary


def test_import_repeats_preserve_record_identity_and_ignore_unmapped_files(storage):
    first = storage.client.post('/api/capture/import', json={'task_id': 'sample', 'product_data': storage.product}).json
    assert first['success'], first
    Path(storage.product['download_path'], 'SKU', '其它.jpg').write_bytes(b'extra')
    second = storage.client.post('/api/capture/import', json={'task_id': 'sample', 'product_data': storage.product}).json
    assert second['success'] and second['record_id'] == first['record_id']
    assert storage.Record.select().count() == 1 and second['data']['sku_count'] == 1


def test_failed_import_does_not_copy_main_image_or_modify_existing_record(storage):
    before = storage.ns['_import_capture_product_record'](storage.product)
    original = storage.Record.get_by_id(before['record_id']).__data__.copy()
    storage.product['sku_info'][0]['name'] = '没有匹配文件的规格'
    main = Path(storage.product['download_path'])/'主图'
    main.mkdir()
    (main/'主图.jpg').write_bytes(b'main')
    with pytest.raises(ValueError, match='无法唯一对应'):
        storage.ns['_import_capture_product_record'](storage.product)
    assert storage.Record.get_by_id(before['record_id']).__data__ == original
    assert len(list(Path(storage.product['download_path'], 'SKU').iterdir())) == 1

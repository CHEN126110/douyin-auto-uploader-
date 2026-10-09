# -*- coding: utf-8 -*-
"""主图/SKU/详情统一卡片定位；仅独立本地模型，不访问用户浏览器。"""
from copy import deepcopy
import json
from unittest.mock import Mock

import pytest

from test_candidate_form_adapters import browser, item, fixture_contracts
from test_category_first_pipeline import install_model
from test_offline_pipeline_handoff import handoff, save_case, save_and_start
from taobao_publish import page, form_adapters, media_library
from taobao_publish.contracts import load_contracts


def test_production_media_flow_does_not_require_image_alt(handoff, monkeypatch):
    install_model(handoff, load_contracts(), monkeypatch)
    handoff.browser.evaluate('''
      const originalAddCard = window.addCard;
      window.addCard = (name, url) => {
        originalAddCard(name, url);
        const card = document.getElementById('gallery').lastElementChild;
        card.className = 'PicList_pic_background__fixture card';
        card.querySelector('img').removeAttribute('alt');
      };
    ''')
    _, task = save_and_start(handoff)
    assert len(handoff.uploads) == 5
    assert all(next(step for step in task['steps'] if step['name'] == name)['status'] == 'ok'
               for name in ('select_category', 'upload_images', 'fill_base'))
    assert page.read_main_image_slots(handoff.browser)['filled'] == 1
    assert task['result']['stage'] == 'fill_detail'
    assert '文本输入模式' in task['error']
    assert len(page.read_sku_row_numbers(handoff.browser)) == 2
    assert handoff.browser.evaluate('window.submitCalls + window.draftCalls') == 0
    assert handoff.browser.evaluate('location.protocol') == 'file:'


def test_read_and_select_share_name_and_url_without_alt(browser, item, monkeypatch):
    name, url = 'tb_7_sku_exact.jpg', 'https://img.example.invalid/exact.jpg'
    browser.evaluate('openGallery(null,null);addCard(%s,%s)' % (json.dumps(name), json.dumps(url)))
    browser.evaluate('''document.querySelector('#gallery img').removeAttribute('alt');
      window.lookupClicks=0;
      document.querySelector('#gallery label').addEventListener('click',()=>window.lookupClicks++);''')
    config = form_adapters.config_for(item, load_contracts(), purpose='media')
    receipt = form_adapters.gallery_find(browser, config, name, context_id=None)
    assert receipt['url'] == url
    assert browser.evaluate('window.lookupClicks') == 0
    # 断言基类 `PageError`：不同资源的拒绝可能来自 JS 表达式（`PageError`），
    # 也可能来自 Python 侧回读核对（`FieldMismatchError`，它是 `PageError` 的子类）。
    with pytest.raises(page.PageError):
        # 用**真正不同的资源**触发
        form_adapters.gallery_find(browser, config, name, context_id=None,
                                   select=True, expected_url='https://img.example.invalid/other.jpg')
    assert browser.evaluate('window.lookupClicks') == 0
    with pytest.raises(page.PageError):
        # `version=` 是**语义参数**，不同即不是同一张图（只有时间戳类参数才豁免）
        form_adapters.gallery_find(browser, config, name, context_id=None,
                                   select=True,
                                   expected_url='https://img.example.invalid/exact.jpg?version=2')
    assert browser.evaluate('window.lookupClicks') == 0
    # 只差**时间戳**参数 → 不算换图，允许选中（缓存击穿参数是平台自己加的）
    monkeypatch.setattr(page.time, 'sleep', lambda *_: None)
    form_adapters.gallery_find(browser, config, name, context_id=None, select=True,
                               expected_url=url + '?t=1791218506000')
    assert browser.evaluate('window.lookupClicks') == 1
    monkeypatch.setattr(page.time, 'sleep', lambda *_: None)
    form_adapters.gallery_find(browser, config, name, context_id=None, select=True, expected_url=url)
    assert browser.evaluate('window.lookupClicks') == 2


@pytest.mark.parametrize('kind', ['queue', 'hidden', 'prefix'])
def test_non_asset_name_mentions_cannot_be_reused(browser, kind):
    name = 'tb_7_main_exact.jpg'
    actual_name = name + '.backup' if kind == 'prefix' else name
    browser.evaluate('openGallery(null,null);addCard(%s,"https://img.example.invalid/other.jpg")' % json.dumps(actual_name))
    if kind == 'queue':
        browser.evaluate('''const wrapper=document.createElement('div');wrapper.className='UploadPanel_preview';
          const card=document.querySelector('#gallery .card');card.before(wrapper);wrapper.append(card);''')
    if kind == 'hidden':
        browser.evaluate("document.querySelector('#gallery .card').hidden=true")
    with pytest.raises(page.MediaImageMissing):
        page.find_media_image(browser, name, context_id=None)


@pytest.mark.parametrize('payload', [None, {'ok': False, 'reason': 'search_incomplete'},
                                    {'ok': False, 'reason': 'scroller_not_unique'}])
def test_unknown_lookup_never_becomes_permission_to_upload(item, monkeypatch, payload):
    client = Mock()
    client.evaluate.return_value = deepcopy(payload)
    monkeypatch.setattr(media_library, 'read_directory', lambda *_a, **_k: {'ok': True, 'supported': False, 'path': []})
    monkeypatch.setattr(page, 'read_media_gallery_state', lambda *_a, **_k: {'ok': True, 'supported': True, 'busy': False})
    upload = Mock(side_effect=AssertionError('未知查找结果不能当作素材不存在'))
    monkeypatch.setattr(page, 'upload_files_to_media', upload)
    with pytest.raises(page.PageError) as caught:
        form_adapters.prepare_media(client, item, load_contracts(), context_id=1)
    assert not isinstance(caught.value, page.MediaImageMissing)
    assert client.evaluate.call_count == 1, '必须走到实际查找响应检查，不能被目录模型缺失提前挡住'
    upload.assert_not_called()

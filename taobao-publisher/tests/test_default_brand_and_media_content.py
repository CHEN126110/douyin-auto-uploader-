# -*- coding: utf-8 -*-
"""用户默认品牌及素材内容身份；全部为隔离本地测试。"""
import hashlib
from pathlib import Path
from unittest.mock import Mock

import pytest

from test_category_first_pipeline import install_model, assert_no_platform_writes
from test_offline_pipeline_handoff import handoff, save_and_start, save_case, browser, fixture_contracts
from taobao_publish import page, form_adapters
from taobao_publish.contracts import load_contracts


@pytest.mark.parametrize('variant,props,expected', [
    ('ok', None, '无品牌'), ('brand_alias', None, '无品牌/无注册商标'),
    ('ok', [{'prop_name': '品牌', 'value_name': '模型注册品牌'}], '模型注册品牌'),
    ('ok', [{'prop_name': '品牌', 'value_name': '无品牌/无注册商标'}], '无品牌'),
])
def test_default_brand_or_explicit_brand_is_selected_before_next(handoff, monkeypatch, variant, props, expected):
    install_model(handoff, load_contracts(), monkeypatch, variant=variant)
    _, task = save_and_start(handoff, props=props)
    assert task['result']['stage'] == 'fill_detail', task['error']
    assert task['steps'][2]['status'] == 'ok'
    assert handoff.browser.evaluate('window.categoryModel.brand') == expected
    assert handoff.browser.evaluate('window.categoryModel.nextClicks') == 1
    assert ('品牌=' + expected) in task['steps'][2]['summary']
    assert 'item.props 里没有' not in task['error']
    assert len(handoff.uploads) == 5
    assert handoff.browser.evaluate('window.submitCalls + window.draftCalls') == 0


@pytest.mark.parametrize('variant,code', [('brand_missing', 'CANDIDATE_NOT_FOUND'),
    ('brand_duplicate', 'CANDIDATE_NOT_FOUND'), ('brand_disabled', 'CANDIDATE_NOT_FOUND'),
    ('brand_unconfirmed', 'BRAND_REQUIRED')])
def test_unavailable_or_unconfirmed_brand_does_not_click_next(handoff, monkeypatch, variant, code):
    install_model(handoff, load_contracts(), monkeypatch, variant=variant)
    _, task = save_and_start(handoff)
    assert task['result']['stage'] == 'select_category', task
    assert task['result']['error']['code'] == code
    assert handoff.browser.evaluate('window.categoryModel.nextClicks') == 0
    assert_no_platform_writes(handoff)


def test_default_brand_is_carried_into_final_property_readback(handoff, fixture_contracts, monkeypatch):
    install_model(handoff, fixture_contracts, monkeypatch, variant='brand_alias')
    _, task = save_and_start(handoff)
    assert task['status'] == 'succeeded', task['error']
    assert page.read_prop_value(handoff.browser, '品牌') == '无品牌/无注册商标'
    assert task['result']['data']['form_verification']['status'] == 'partial'
    assert handoff.browser.evaluate('window.submitCalls + window.draftCalls') == 0


def test_main_identity_keeps_source_name_and_tracks_content(tmp_path):
    """上传名=源文件名（2026-10-08 政策）：内容变 → sha 变 → 重新上传，但名字不变。"""
    path = tmp_path / '同名主图.jpg'
    path.write_bytes(b'first local synthetic image')
    first = form_adapters.media_file_identity(path, 7, 'main', slot=1)
    path.write_bytes(b'second local synthetic image')
    second = form_adapters.media_file_identity(path, 7, 'main', slot=1)
    assert first['name'] == second['name'] == '同名主图.jpg'
    assert first['sha256'] != second['sha256']
    assert second['sha256'] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert path.name == '同名主图.jpg'


def test_same_content_shares_one_identity_across_slots_and_products(tmp_path):
    """同名同内容 → 同一个上传身份（跨槽位/跨商品去重共用）；跨商品靠**目录**隔离。"""
    path = tmp_path / '主图.jpg'
    path.write_bytes(b'local synthetic bytes')
    identities = [form_adapters.media_file_identity(path, record, 'main', slot=slot)
                  for record, slot in [(7, 1), (7, 2), (8, 1)]]
    assert {entry['name'] for entry in identities} == {'主图.jpg'}
    assert len({entry['sha256'] for entry in identities}) == 1


def test_changed_second_file_rejects_whole_batch_before_browser_action(tmp_path, monkeypatch):
    first, second = tmp_path / 'first.jpg', tmp_path / 'second.jpg'
    first.write_bytes(b'one'); second.write_bytes(b'two')
    expected = [hashlib.sha256(path.read_bytes()).hexdigest() for path in (first, second)]
    second.write_bytes(b'changed after identity creation')
    client = Mock()
    entry = Mock(side_effect=AssertionError('摘要不匹配时不能点击上传入口'))
    monkeypatch.setattr(page, 'click_media_entry', entry)
    with pytest.raises(page.MediaSourceChangedError):
        page.upload_files_to_media(client, [str(first), str(second)], context_id=1,
            rename_to=['snapshot-one.jpg', 'snapshot-two.jpg'], expected_sha256=expected)
    entry.assert_not_called()
    client.set_file_input_files.assert_not_called()


@pytest.mark.parametrize('failure', [False, True, 'rejected'])
def test_snapshot_bytes_are_fixed_and_cleaned_on_success_or_error(tmp_path, monkeypatch, failure):
    original = tmp_path / '原图.jpg'; original.write_bytes(b'captured bytes')
    digest = hashlib.sha256(original.read_bytes()).hexdigest()
    observed = []
    def staged(client, files, targets, **kwargs):
        original.write_bytes(b'changed after snapshot')
        copy = Path(files[0]); observed.append(copy)
        assert copy.read_bytes() == b'captured bytes'
        assert targets == ['upload.jpg']
        if failure is True:
            raise page.PageError('synthetic upload failure')
        return {'ok': failure != 'rejected', 'rejectedByPlatform': failure == 'rejected'}
    monkeypatch.setattr(page, '_upload_staged_files_to_media', staged)
    if failure is True:
        with pytest.raises(page.PageError, match='synthetic upload failure'):
            page.upload_files_to_media(Mock(), [str(original)], context_id=1,
                rename_to=['upload.jpg'], expected_sha256=[digest])
    else:
        assert page.upload_files_to_media(Mock(), [str(original)], context_id=1,
            rename_to=['upload.jpg'], expected_sha256=[digest])['ok'] is (failure != 'rejected')
    assert observed and not observed[0].exists()
    assert original.read_bytes() == b'changed after snapshot'


@pytest.mark.parametrize('names,digests', [(['../outside.jpg'], None), (['x.jpg'], ['bad']),
    (['x.jpg', 'x.jpg'], None)])
def test_invalid_snapshot_arguments_never_touch_browser(tmp_path, names, digests):
    original = tmp_path / 'source.jpg'; original.write_bytes(b'synthetic bytes')
    client = Mock()
    with pytest.raises(page.PageError):
        page.upload_files_to_media(client, [str(original)] * len(names), context_id=1,
                                  rename_to=names, expected_sha256=digests)
    client.assert_not_called()
    client.set_file_input_files.assert_not_called()


def test_strict_filename_does_not_select_a_prefix_or_backup_file(browser):
    browser.evaluate('openGallery(null,null); addCard("tb_7_main_1_hash.jpg.backup", "https://img.example.invalid/backup.jpg")')
    result = browser.evaluate(page.build_select_media_image_expression('tb_7_main_1_hash.jpg'))
    assert not result['ok']


def test_media_selection_waits_for_virtual_scroll_rendering(browser):
    browser.evaluate('''openGallery(null,null);
      const gallery = document.getElementById('gallery');
      gallery.innerHTML = '<div style="height:2000px">MODEL_SPACER</div>';
      gallery.onscroll = () => { if (gallery.scrollTop > 150 && !window.modelTargetCreated) {
        window.modelTargetCreated = true;
        setTimeout(() => addCard('tb_7_main_1_hash.jpg', 'https://img.example.invalid/target.jpg'), 20);
      }};''')
    result = browser.evaluate(page.build_select_media_image_expression('tb_7_main_1_hash.jpg'))
    assert result['ok'] and result['url'] == 'https://img.example.invalid/target.jpg'
    assert result['scrolled'] > 0


@pytest.mark.parametrize('url', ['http://img.example.invalid/plain.jpg', 'https://user:secret@img.example.invalid/one.jpg'])
def test_invalid_selected_url_is_rejected_before_click(browser, url):
    import json
    browser.evaluate('openGallery(null,null); addCard("target.jpg", %s)' % json.dumps(url))
    browser.evaluate("document.querySelector('#gallery label').onclick=()=>{window.badMediaClicks=(window.badMediaClicks||0)+1}")
    result = browser.evaluate(page.build_select_media_image_expression('target.jpg'))
    assert not result['ok'] and result['reason'] == 'image_url_invalid'
    assert browser.evaluate('window.badMediaClicks || 0') == 0


def test_main_slot_waits_for_expected_url_after_slot_count_changes(monkeypatch):
    target = 'https://img.example.invalid/expected.jpg'
    reader = Mock(side_effect=[{'filled': 1, 'images': []}, {'filled': 1, 'images': [target]}])
    monkeypatch.setattr(page, 'read_main_image_slots', reader)
    monkeypatch.setattr(page.time, 'sleep', lambda *_: None)
    result = page.wait_for_main_image_slots(Mock(), 1, expected_urls=[target])
    assert result['images'] == [target] and reader.call_count == 2


def test_wrong_main_slot_url_is_not_confirmed_by_count_alone(monkeypatch):
    target = 'https://img.example.invalid/expected.jpg'
    monkeypatch.setattr(page, 'read_main_image_slots', Mock(return_value={'filled': 1, 'images': ['wrong']}))
    ticks = iter([0.0, 0.1, 0.5, 1.0, 2.1])
    monkeypatch.setattr(page.time, 'time', lambda: next(ticks))
    monkeypatch.setattr(page.time, 'sleep', lambda *_: None)
    result = page.wait_for_main_image_slots(Mock(), 1, timeout=2.0, expected_urls=[target])
    assert result['images'] != [target]

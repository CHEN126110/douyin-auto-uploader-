# -*- coding: utf-8 -*-
"""主图多选：平台原生配置、一次确认、身份与回退边界。"""
import json
from urllib.parse import parse_qs, urlsplit

import pytest

from taobao_publish import page
from taobao_publish import media_library


ORIGINAL = ('https://market.m.taobao.com/app/crs-qn/sucai-selector-ng/index?'
            'type=pic&realtime=true&max=1&realTimeSelect=true&singleSelect=false&handleId=abc123')
NATIVE_MULTI = ('https://market.m.taobao.com/app/crs-qn/sucai-selector-ng/index?'
                'type=pic&realtime=false&max=5&realTimeSelect=false&singleSelect=false&handleId=abc123')


class FakeClient:
    def __init__(self, ready=True):
        self.src = ORIGINAL
        self.ready = ready
        self.expressions = []

    def evaluate(self, expression, context_id=None, **kwargs):
        self.expressions.append(expression)
        if 'frame.src=' in expression:
            self.src = json.loads(expression.split('frame.src=', 1)[1].rstrip(';'))
            return None
        if 'return frame?frame.src:""' in expression:
            return self.src
        if 'Footer_selectOk' in expression:
            return self.ready
        raise AssertionError('未预期的页面求值：' + expression)


def test_configure_accepts_only_native_multi_select_without_rewriting_it(monkeypatch):
    client = FakeClient()
    client.src = NATIVE_MULTI
    monkeypatch.setattr(page, 'media_iframe_context', lambda _client: 42)
    result = page.configure_main_image_multi_select(client, 5)
    query = parse_qs(urlsplit(client.src).query)
    assert query['max'] == ['5']
    assert query['realtime'] == ['false']
    assert query['realTimeSelect'] == ['false']
    assert query['singleSelect'] == ['false']
    assert query['handleId'] == ['abc123']
    assert result['changed'] is False and result['context_id'] == 42
    assert client.src == NATIVE_MULTI


def test_single_slot_selector_falls_back_before_any_click_or_url_rewrite():
    client = FakeClient()
    with pytest.raises(page.MainBatchUnsupportedError, match='原生单槽位'):
        page.configure_main_image_multi_select(client, 5)
    assert client.src == ORIGINAL
    assert not any('frame.src=' in expression for expression in client.expressions)


def test_native_multi_selector_is_not_rewritten_when_confirmation_is_missing(monkeypatch):
    client = FakeClient(ready=False)
    client.src = NATIVE_MULTI
    monkeypatch.setattr(page, 'media_iframe_context', lambda _client: 42)
    monkeypatch.setattr(page.time, 'sleep', lambda _seconds: None)
    times = iter([10, 10, 17])
    monkeypatch.setattr(page.time, 'time', lambda: next(times))
    with pytest.raises(page.MainBatchUnsupportedError, match='批量确认入口'):
        page.configure_main_image_multi_select(client, 5)
    assert client.src == NATIVE_MULTI


def test_batch_requires_ids_and_one_directory_before_touching_browser(monkeypatch):
    client = FakeClient()
    monkeypatch.setattr(page, 'configure_main_image_multi_select',
                        lambda *_args, **_kwargs: pytest.fail('不应进入多选配置'))
    with pytest.raises(page.MainBatchUnsupportedError):
        page.select_main_images_batch(client, [{'name': 'a.jpg', 'url': 'https://img/a'}], context_id=1)
    with pytest.raises(page.MainBatchUnsupportedError):
        page.select_main_images_batch(client, [
            {'name': 'a.jpg', 'picture_id': '1', 'url': 'https://img/a', 'folder_path': ['全部图片', 'a']},
            {'name': 'b.jpg', 'picture_id': '2', 'url': 'https://img/b', 'folder_path': ['全部图片', 'b']},
        ], context_id=1)


def receipts():
    return [
        {'name': 'a.jpg', 'picture_id': '11', 'url': 'https://img/a', 'folder_path': ['全部图片', '商品', '主图']},
        {'name': 'b.jpg', 'picture_id': '22', 'url': 'https://img/b', 'folder_path': ['全部图片', '商品', '主图']},
    ]


def test_batch_selects_all_ids_and_confirms_once(monkeypatch):
    calls = []
    monkeypatch.setattr(page, 'configure_main_image_multi_select', lambda _client, _max: {'context_id': 42})
    monkeypatch.setattr(media_library, 'open_directory',
                        lambda _client, folder, **_kwargs: calls.append(('directory', folder)) or ['全部图片', '商品', '主图'])
    monkeypatch.setattr(media_library, 'pick_media_by_id_with_requery',
                        lambda _client, ids, **kwargs: calls.append(('picked', ids, kwargs)) or {
                            'selected': [
                                {'pictureId': '11', 'url': 'https://img/a', 'checked': True},
                                {'pictureId': '22', 'url': 'https://img/b', 'checked': True},
                            ]})
    monkeypatch.setattr(page, 'confirm_media_selection',
                        lambda _client, **kwargs: calls.append(('confirmed', kwargs)) or {'ok': True})
    result = page.select_main_images_batch(FakeClient(), receipts(), context_id=1)
    assert result['selected_urls'] == ['https://img/a', 'https://img/b']
    assert result['selected'] == ['a.jpg', 'b.jpg']
    assert result['context_id'] == 42
    assert [call[0] for call in calls] == ['directory', 'picked', 'confirmed']
    assert calls[1][1] == ['11', '22']


def test_batch_does_not_confirm_when_any_item_is_unchecked(monkeypatch):
    monkeypatch.setattr(page, 'configure_main_image_multi_select', lambda _client, _max: {'context_id': 42})
    monkeypatch.setattr(media_library, 'open_directory', lambda *_args, **_kwargs: ['全部图片', '商品', '主图'])
    monkeypatch.setattr(media_library, 'pick_media_by_id_with_requery', lambda *_args, **_kwargs: {
        'selected': [{'pictureId': '11', 'url': 'https://img/a', 'checked': True},
                     {'pictureId': '22', 'url': 'https://img/b', 'checked': False}]})
    monkeypatch.setattr(page, 'confirm_media_selection',
                        lambda *_args, **_kwargs: pytest.fail('未勾选完整不能确认'))
    with pytest.raises(page.FieldMismatchError, match='未勾选'):
        page.select_main_images_batch(FakeClient(), receipts(), context_id=1)


def test_stage_keeps_legacy_single_image_fallback():
    source = page.__loader__.get_source(page.__name__)
    stages = __import__('taobao_publish.stages', fromlist=['stage_upload_images']).__loader__.get_source('taobao_publish.stages')
    assert 'page.select_main_images_batch' in stages
    assert 'except page.MainBatchUnsupportedError' in stages
    assert 'pick_media_by_id_with_requery' in stages


def test_single_popup_legacy_loop_does_not_close_between_images():
    stages = __import__('taobao_publish.stages', fromlist=['stage_upload_images']).__loader__.get_source('taobao_publish.stages')
    tree = __import__('ast').parse(stages)
    loops = [node for node in __import__('ast').walk(tree)
             if isinstance(node, __import__('ast').For)
             and isinstance(node.target, __import__('ast').Name)
             and node.target.id == 'main_receipt']
    assert loops
    for loop in loops:
        between_images = [node for node in __import__('ast').walk(loop)
                          if isinstance(node, __import__('ast').If)
                          and isinstance(node.test, __import__('ast').Name)
                          and node.test.id == 'selected']
        for guard in between_images:
            closing_calls = [node for node in __import__('ast').walk(guard)
                             if isinstance(node, __import__('ast').Call)
                             and isinstance(node.func, __import__('ast').Attribute)
                             and node.func.attr == 'ensure_media_popup_closed']
            assert not closing_calls, '原生单选会推进主图位；不能在每张之间主动关闭选图器'

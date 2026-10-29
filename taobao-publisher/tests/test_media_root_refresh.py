# -*- coding: utf-8 -*-
"""选图器目录陈旧时，先有限刷新再考虑重开弹层。"""
from taobao_publish import media_library


def test_missing_root_is_refreshed_once_before_reopening(monkeypatch):
    calls = []
    monkeypatch.setattr(media_library, '_scroll_product_into_view',
                        lambda _client, name, **_kwargs: calls.append(('read', name)) or (None if len(calls) == 1 else ['test-product']))
    monkeypatch.setattr(media_library, 'refresh_gallery',
                        lambda _client, **_kwargs: calls.append(('refresh', _kwargs)) or True)
    root = media_library.ensure_product_root(object(), 'test-product', context_id=7,
        on_stale=lambda _name: (_ for _ in ()).throw(AssertionError('有效刷新后不应重开')))
    assert root == ['test-product']
    assert [call[0] for call in calls] == ['read', 'refresh', 'read']


def test_refresh_failure_still_uses_existing_stale_path(monkeypatch):
    calls = []
    monkeypatch.setattr(media_library, '_scroll_product_into_view',
                        lambda _client, name, **_kwargs: calls.append(('read', name)) or (None if len(calls) < 3 else ['test-product']))
    monkeypatch.setattr(media_library, 'refresh_gallery', lambda _client, **_kwargs: False)
    monkeypatch.setattr(media_library, '_remember_context',
                        lambda storage, context_id: calls.append(('renewed', context_id)))
    root = media_library.ensure_product_root(object(), 'test-product', context_id=7,
        on_stale=lambda _name: 99)
    assert root == ['test-product']
    assert [call[0] for call in calls] == ['read', 'read', 'renewed', 'read']

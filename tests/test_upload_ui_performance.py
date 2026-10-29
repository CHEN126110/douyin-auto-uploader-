# -*- coding: utf-8 -*-
"""发布页可选字段与浮层的批量状态探测回归。"""
import types

import pytest

from src.sidecar import upload_steps


class FieldTab:
    def __init__(self, js_result=None, existing=()):
        self.js_result = js_result
        self.existing = set(existing)
        self.run_js_calls = 0
        self.ele_calls = []

    def run_js(self, script, *args):
        self.run_js_calls += 1
        if isinstance(self.js_result, Exception):
            raise self.js_result
        return self.js_result

    def ele(self, selector, timeout=None):
        self.ele_calls.append(selector)
        for field_name in self.existing:
            if f'attr-field-id="{field_name}"' in selector:
                return object()
        return None


def test_category_field_presence_uses_one_js_probe_and_preserves_aliases():
    tab = FieldTab(js_result={'材质': True, '筒高': True})

    result = upload_steps._get_category_field_presence(tab)

    assert result == {
        'material_field_name': '材质',
        'has_audience_field': False,
        'has_gender_field': False,
        'has_sock_height_field': True,
    }
    assert tab.run_js_calls == 1
    assert tab.ele_calls == []


def test_category_field_presence_falls_back_to_legacy_element_queries():
    tab = FieldTab(js_result=RuntimeError('JS unavailable'), existing=('面料材质', '适用性别'))

    result = upload_steps._get_category_field_presence(tab)

    assert result == {
        'material_field_name': '面料材质',
        'has_audience_field': False,
        'has_gender_field': True,
        'has_sock_height_field': False,
    }
    # 面料材质已命中，不再查询别名「材质」；随后三个可选字段各查一次。
    assert len(tab.ele_calls) == 4


class OverlayTab:
    def __init__(self, drag_present=False):
        self.drag_present = drag_present
        self.drag = types.SimpleNamespace(states=types.SimpleNamespace(is_displayed=True))
        self.removed = []
        self.ele_calls = []

    def run_js(self, script, *args):
        return 0 if self.drag_present else -1

    def ele(self, selector, timeout=None):
        self.ele_calls.append(selector)
        return self.drag if self.drag_present else None

    def eles(self, selector, timeout=None):
        return []

    def remove_ele(self, element):
        self.removed.append(element)


def test_missing_drag_controller_does_not_make_a_serial_element_query():
    tab = OverlayTab(drag_present=False)

    assert upload_steps._dismiss_interfering_overlays(tab) == 0
    assert tab.ele_calls == []


def test_existing_drag_controller_is_still_removed():
    tab = OverlayTab(drag_present=True)

    assert upload_steps._dismiss_interfering_overlays(tab) == 1
    assert tab.removed == [tab.drag]

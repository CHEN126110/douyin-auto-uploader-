# -*- coding: utf-8 -*-
"""AI/历史规格预填的确定性初始化：只保留颜色与码数，再按商品填写。"""
from types import SimpleNamespace

import pytest

from src.sidecar import upload_steps


class _Button:
    def __init__(self, tab, action, axis):
        self.tab = tab
        self.action = action
        self.axis = axis
        self.states = SimpleNamespace(is_displayed=True, is_enabled=True)
        self.scroll = SimpleNamespace(to_center=lambda: None)

    def click(self, by_js=False):
        self.tab.clicks.append((self.action, self.axis))
        if self.action == 'delete-axis':
            self.tab.axes.remove(self.axis)
        else:
            self.tab.value_buttons[self.axis].remove(self)
            self.tab.selected[self.axis] = bool(self.tab.value_buttons[self.axis])


class FakeSkuTab:
    def __init__(self, axes=None, values=None, allow_axis_delete=True):
        self.axes = list(axes or ['颜色分类', '码数'])
        self.allow_axis_delete = allow_axis_delete
        self.value_buttons = {axis: [] for axis in self.axes}
        self.selected = {axis: False for axis in self.axes}
        for axis, count in (values or {}).items():
            self.selected[axis] = count > 0
            self.value_buttons[axis] = [_Button(self, 'delete-value', axis) for _ in range(count)]
        self.clicks = []

    def run_js(self, script, *args):
        if 'const specs = arguments[0]' in script:
            return None  # 让测试走 DrissionPage 元素回退路径。
        if 'document.getElementById(arguments[0])' in script:
            return self.selected.get(args[0][len('skuValue-'):], False)
        if 'div[id^="skuValue-"]' in script:
            return list(self.axes)
        return -1

    @staticmethod
    def _axis_from_selector(selector):
        if 'skuValue-' not in selector:
            return None
        tail = selector.split('skuValue-', 1)[1]
        return tail.split("'", 1)[0].split('"', 1)[0].split(']', 1)[0]

    def ele(self, selector, timeout=None):
        axis = self._axis_from_selector(selector)
        if axis in self.axes:
            return SimpleNamespace(states=SimpleNamespace(is_displayed=True))
        return None

    def eles(self, selector, timeout=None):
        axis = self._axis_from_selector(selector)
        if 'style_specOperations__' in selector:
            if axis in self.axes and self.allow_axis_delete:
                return [_Button(self, 'delete-axis', axis)]
            return []
        if 'data-kora="删除规格值"' in selector:
            return list(self.value_buttons.get(axis, []))
        return []


def test_ai_extra_dimensions_are_removed_and_legacy_axes_are_untouched():
    tab = FakeSkuTab(['颜色分类', '码数', '筒高长度', '规格'])
    assert upload_steps._reset_unexpected_sku_dimensions(tab) == ['筒高长度', '规格']
    assert tab.axes == ['颜色分类', '码数']
    assert tab.clicks == [('delete-axis', '筒高长度'), ('delete-axis', '规格')]

    legacy = FakeSkuTab(['颜色分类', '码数'])
    assert upload_steps._reset_unexpected_sku_dimensions(legacy) == []
    assert legacy.clicks == []


def test_missing_dimension_delete_control_is_an_explicit_failure():
    tab = FakeSkuTab(['颜色分类', '码数', '筒高长度'], allow_axis_delete=False)
    with pytest.raises(Exception, match='删除按钮'):
        upload_steps._reset_unexpected_sku_dimensions(tab)
    assert '筒高长度' in tab.axes


def test_color_and_size_values_are_cleared_before_product_values():
    tab = FakeSkuTab(values={'颜色分类': 2, '码数': 1})
    upload_steps._clear_sku_axis_values(tab, '颜色分类')
    upload_steps._clear_sku_axis_values(tab, '码数')
    assert tab.value_buttons == {'颜色分类': [], '码数': []}
    assert tab.selected == {'颜色分类': False, '码数': False}
    assert len(tab.clicks) == 3


def test_selected_values_without_a_delete_control_cannot_be_ignored():
    tab = FakeSkuTab()
    tab.selected['码数'] = True
    with pytest.raises(Exception, match='无法清理'):
        upload_steps._clear_sku_axis_values(tab, '码数')


def test_sku_entry_initializes_before_writing_product_skus(monkeypatch):
    calls = []
    monkeypatch.setattr(upload_steps, '_dismiss_interfering_overlays', lambda *args, **kwargs: None)
    monkeypatch.setattr(upload_steps, '_scroll_to_price_stock_area', lambda *args, **kwargs: None)
    monkeypatch.setattr(upload_steps, '_ensure_manual_sku_entry_mode', lambda tab: calls.append('manual'))
    monkeypatch.setattr(upload_steps, '_reset_unexpected_sku_dimensions', lambda tab: calls.append('reset') or ['筒高长度'])
    monkeypatch.setattr(upload_steps, '_ensure_color_sku_type', lambda tab: calls.append('color-axis'))
    monkeypatch.setattr(upload_steps, '_clear_sku_axis_values', lambda tab, axis: calls.append('clear-' + axis))
    monkeypatch.setattr(upload_steps, 'set_sku_info', lambda tab, index, sku, remark: calls.append('write-sku'))

    class Tab:
        def ele(self, selector, timeout=None):
            return SimpleNamespace(click=lambda by_js=False: None)

    upload_steps._configure_sku_entries(Tab(), [{'name': '奶白'}], '')
    assert calls == ['manual', 'reset', 'color-axis', 'clear-颜色分类', 'clear-码数', 'write-sku']

# -*- coding: utf-8 -*-
"""类目选择「下一步」不得重复点击的回归测试（2026-08-28）。

`_click_next_step` 会依次尝试 4 种点击方式（普通 / JS / 模拟 / 强制JS），
每次点击后用 `_wait_for_second_page` 验证是否跳转。

风险：`_wait_for_second_page` 要求**连续两轮**命中第二页特征元素，
而它原先每轮要逐个探测 7 个 XPath（DrissionPage 未命中时阻塞满 timeout，
一轮落空约 1.4s），5s 预算内跑不了几轮——
于是「点击其实已经成功」也可能被判失败，进而继续点第 2、3、4 次。

修复后：每种点击方式之前先用一次 JS 判定是否已在第二页，已跳转就直接返回成功。
"""

import os
import sys
import types

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from src.enhanced_category_selector import (  # noqa: E402
    _PROBE_UNAVAILABLE,
    EnhancedCategorySelector,
)


class FakeElement:
    def __init__(self, on_click=None):
        self.states = types.SimpleNamespace(is_displayed=True)
        self.scroll = types.SimpleNamespace(to_center=lambda: None)
        self._on_click = on_click

    def click(self, by_js=False):
        if self._on_click:
            self._on_click()


class CountingTab:
    """记录「下一步」被点了几次；第一次点击后即进入第二页。"""

    def __init__(self, probe_available=True):
        self.next_clicks = 0
        self.on_second_page = False
        self.probe_available = probe_available
        self.actions = types.SimpleNamespace(click=lambda el: el.click())

    def _click_next(self):
        self.next_clicks += 1
        self.on_second_page = True

    def ele(self, selector, timeout=None):
        if '下一步' in selector or 'nextStep' in selector:
            return FakeElement(on_click=self._click_next)
        if self.on_second_page and ('formBlockNewUI' in selector or '主图3:4' in selector
                                    or '基础信息' in selector or '主图视频' in selector
                                    or '类目属性' in selector):
            return FakeElement()
        return None

    def eles(self, selector, timeout=None):
        return []

    def run_js(self, script, *args):
        if not self.probe_available:
            raise RuntimeError('run_js unavailable')
        xpaths = args[0] if args else []
        if not self.on_second_page:
            return -1
        for index, xpath in enumerate(xpaths):
            if any(k in xpath for k in ('formBlockNewUI', '主图3:4', '基础信息', '主图视频', '类目属性')):
                return index
        return -1


def test_second_page_probe_reports_state():
    tab = CountingTab()
    selector = EnhancedCategorySelector(tab)
    assert selector._is_on_second_page() is False
    tab.on_second_page = True
    assert selector._is_on_second_page() is True


def test_probe_falls_back_when_js_unavailable():
    """JS 不可用时必须回退逐个探测，而不是误判为「不在第二页」。"""
    tab = CountingTab(probe_available=False)
    selector = EnhancedCategorySelector(tab)
    assert selector._probe_visible_xpath(['xpath://div[contains(@class,"formBlockNewUI")]']) is _PROBE_UNAVAILABLE
    tab.on_second_page = True
    assert selector._is_on_second_page() is True


def test_next_step_not_clicked_again_once_on_second_page():
    """核心回归：已经进入第二页后，不能再点「下一步」。"""
    tab = CountingTab()
    tab.on_second_page = True
    selector = EnhancedCategorySelector(tab)

    assert selector._click_next_step() is True
    assert tab.next_clicks == 0, '已在第二页时不应再点击「下一步」'


def test_source_guards_every_click_attempt():
    """源码层面确认每种点击方式之前都有「是否已在第二页」的守卫。"""
    import io

    path = os.path.join(REPO_ROOT, 'src', 'enhanced_category_selector.py')
    source = io.open(path, encoding='utf-8').read()
    body = source.split('def _click_next_step', 1)[1].split('def _check_and_handle_error', 1)[0]
    assert body.count('_is_on_second_page()') >= 2, \
        '循环内与强制JS点击之前都必须先判断是否已跳转，避免重复点击'

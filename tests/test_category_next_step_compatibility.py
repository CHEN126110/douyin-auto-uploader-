# -*- coding: utf-8 -*-
"""抖店第一页翻页按钮的新旧兼容性回归（2026-10-26）。

旧版按钮是「下一步」/ nextStep；2026-10 实测新版按钮是
「确认信息，继续生成」/ aiPublishButton。两种页面都必须能进入第二页；
找不到按钮或点击后没有进入第二页时，不得继续执行第二页的字段填写。
"""
import ast
import io
import os
import types

import pytest

from src.enhanced_category_selector import EnhancedCategorySelector

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class FakeElement:
    def __init__(self, on_click, text='', class_name=''):
        self.states = types.SimpleNamespace(is_displayed=True)
        self.scroll = types.SimpleNamespace(to_center=lambda: None)
        self._on_click = on_click
        self.text = text
        self._class_name = class_name

    def click(self, by_js=False):
        self._on_click(by_js=by_js)

    def attr(self, name):
        return self._class_name if name == 'class' else None


class CompatibleTab:
    def __init__(self, button_kind, probe_available=True):
        self.button_kind = button_kind
        self.on_second_page = False
        self.probe_available = probe_available
        self.click_count = 0
        self.click_methods = []
        self.ele_calls = []
        self.actions = types.SimpleNamespace(click=self._actions_click)

    def _click(self, method='native', **_kwargs):
        self.click_count += 1
        self.click_methods.append(method)
        self.on_second_page = True

    def _actions_click(self, _element):
        self._click('actions')

    def _matches_button(self, selector):
        legacy_match = '下一步' in selector or 'nextStep' in selector
        ai_match = '确认信息，继续生成' in selector or 'aiPublishButton' in selector
        return (self.button_kind == 'legacy' and legacy_match) or (self.button_kind == 'ai' and ai_match)

    def ele(self, selector, timeout=None):
        self.ele_calls.append(selector)
        if self._matches_button(selector):
            text = '确认信息，继续生成' if self.button_kind == 'ai' else '下一步'
            class_name = 'style_aiPublishButton__x' if self.button_kind == 'ai' else 'nextStep'
            return FakeElement(self._click, text=text, class_name=class_name)
        if self.on_second_page and any(
                marker in selector for marker in ('formBlockNewUI', '主图3:4', '基础信息', '主图视频', '类目属性')):
            return FakeElement(lambda: None)
        return None

    def run_js(self, script, *args):
        if not self.probe_available:
            raise RuntimeError('run_js unavailable')
        xpaths = args[0] if args else []
        for index, xpath in enumerate(xpaths):
            selector = 'xpath:' + xpath
            if self.on_second_page and any(
                    marker in selector for marker in ('formBlockNewUI', '主图3:4', '基础信息', '主图视频', '类目属性')):
                return index
            if not self.on_second_page and self._matches_button(selector):
                return index
        return -1


@pytest.mark.parametrize('button_kind', ['legacy', 'ai'])
def test_next_step_supports_legacy_and_ai_buttons(button_kind):
    tab = CompatibleTab(button_kind)
    selector = EnhancedCategorySelector(tab)

    assert selector._click_next_step() is True
    assert tab.click_count == 1
    assert tab.on_second_page is True
    assert len(tab.ele_calls) == 1, '批量探针命中后只应取一次元素句柄'
    assert tab.click_methods == ['native'], '两种页面都保留普通点击优先，其它方式仅作回退'


@pytest.mark.parametrize('button_kind,expected_wait', [('legacy', 5.0), ('ai', 15.0)])
def test_first_click_wait_budget_matches_page_family(monkeypatch, button_kind, expected_wait):
    tab = CompatibleTab(button_kind)
    selector = EnhancedCategorySelector(tab)
    waits = []
    original_wait = selector._wait_for_second_page

    def tracked_wait(max_wait):
        waits.append(max_wait)
        return original_wait(max_wait)

    monkeypatch.setattr(selector, '_wait_for_second_page', tracked_wait)
    assert selector._click_next_step() is True
    assert waits == [expected_wait]


@pytest.mark.parametrize('button_kind', ['legacy', 'ai'])
def test_next_step_serial_fallback_survives_without_js(button_kind):
    tab = CompatibleTab(button_kind, probe_available=False)
    selector = EnhancedCategorySelector(tab)

    assert selector._click_next_step() is True
    assert tab.click_count == 1


def test_missing_next_step_button_is_not_success():
    tab = CompatibleTab(button_kind=None)
    selector = EnhancedCategorySelector(tab)

    assert selector._click_next_step() is False
    assert tab.click_count == 0
    assert tab.ele_calls == [], 'JS 已确认无命中时不应再串行空等'


@pytest.mark.parametrize('selection_path', ['default', 'recommendation', 'more_once', 'more_twice'])
def test_category_selection_stops_when_advance_fails(monkeypatch, selection_path):
    """四条快速路径都不得把「类目已选、翻页失败」误报为成功。"""
    selector = EnhancedCategorySelector(CompatibleTab(button_kind=None))
    monkeypatch.setattr(selector, '_is_current_category', lambda _name: selection_path == 'default')
    recommendation_results = {
        'default': [],
        'recommendation': [True],
        'more_once': [False, True],
        'more_twice': [False, False, True],
    }[selection_path]
    monkeypatch.setattr(selector, '_select_from_recommendations', lambda _name: recommendation_results.pop(0))
    monkeypatch.setattr(selector, '_click_more_recommend', lambda _times: None)
    monkeypatch.setattr(selector, '_click_next_step', lambda: False)

    assert selector.select_category('2', max_retries=1) is False


def test_publish_step1_probe_keeps_legacy_and_adds_ai_button():
    path = os.path.join(REPO_ROOT, 'src', 'sidecar', 'upload_steps.py')
    source = io.open(path, encoding='utf-8').read()
    tree = ast.parse(source)
    assignment = next(
        node for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == '_PUBLISH_STEP1_SELECTORS' for target in node.targets)
    )
    selectors = ast.literal_eval(assignment.value)

    assert any('下一步' in selector for selector in selectors)
    assert any('确认信息，继续生成' in selector for selector in selectors)
    assert any('aiPublishButton' in selector for selector in selectors)


def test_forced_js_fallback_covers_both_button_families():
    path = os.path.join(REPO_ROOT, 'src', 'enhanced_category_selector.py')
    source = io.open(path, encoding='utf-8').read()
    body = source.split('def _click_next_step', 1)[1].split('def _check_and_handle_error', 1)[0]

    assert 'nextStep' in body
    assert 'aiPublishButton' in body


def test_combined_next_button_selector_is_first_for_js_fallback():
    path = os.path.join(REPO_ROOT, 'src', 'enhanced_category_selector.py')
    source = io.open(path, encoding='utf-8').read()
    tree = ast.parse(source)
    function = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == '_click_next_step')
    assignment = next(
        node for node in ast.walk(function)
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == 'all_selectors' for target in node.targets)
    )
    selectors = ast.literal_eval(assignment.value)
    combined = selectors[0]

    for marker in ('nextStep', 'aiPublishButton', '下一步', '确认信息，继续生成'):
        assert marker in combined
    assert ' or ' in combined


def test_post_click_popup_fallback_uses_short_timeouts():
    class PopupTab:
        def __init__(self):
            self.timeouts = []

        def run_js(self, script, *args):
            raise RuntimeError('navigation context unavailable')

        def ele(self, selector, timeout=None):
            self.timeouts.append(timeout)
            return None

    tab = PopupTab()
    selector = EnhancedCategorySelector(tab)
    selector._handle_post_click_popup()

    assert tab.timeouts == [0.05, 0.05, 0.05]

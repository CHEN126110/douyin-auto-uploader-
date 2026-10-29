# -*- coding: utf-8 -*-
"""类目候选元素的批量探测：消除串行 timeout，保留 JS 不可用回退。"""
import types

from src.enhanced_category_selector import EnhancedCategorySelector


class ProbeElement:
    def __init__(self, text='', class_name=''):
        self.text = text
        self.class_name = class_name
        self.states = types.SimpleNamespace(is_displayed=True)
        self.scroll = types.SimpleNamespace(to_see=lambda: None, to_center=lambda: None)
        self.click_count = 0

    def attr(self, name):
        return self.class_name if name == 'class' else None

    def click(self, by_js=False):
        self.click_count += 1


class ProbeTab:
    def __init__(self, visible=(), js_available=True):
        self.visible = set(visible)
        self.js_available = js_available
        self.elements = {}
        self.ele_calls = []
        self.probe_calls = []

    def element_for(self, selector, text='', class_name=''):
        element = ProbeElement(text=text, class_name=class_name)
        self.elements[selector] = element
        self.visible.add(selector)
        return element

    def run_js(self, script, *args):
        if not self.js_available:
            raise RuntimeError('JS unavailable')
        xpaths = list(args[0]) if args else []
        self.probe_calls.append(xpaths)
        for index, xpath in enumerate(xpaths):
            if 'xpath:' + xpath in self.visible:
                return index
        return -1

    def ele(self, selector, timeout=None):
        self.ele_calls.append(selector)
        return self.elements.get(selector)


def test_more_recommend_only_fetches_the_element_hit_by_batch_probe(monkeypatch):
    monkeypatch.setattr('src.enhanced_category_selector.time.sleep', lambda _seconds: None)
    selector = 'xpath://span[text()="更多推荐"]'
    tab = ProbeTab()
    element = tab.element_for(selector)
    category = EnhancedCategorySelector(tab)

    category._click_more_recommend()

    assert tab.ele_calls == [selector]
    assert element.click_count == 1


def test_recommendation_match_only_fetches_the_hit_and_keeps_old_click_behavior(monkeypatch):
    monkeypatch.setattr('src.enhanced_category_selector.time.sleep', lambda _seconds: None)
    selector = 'xpath://div[contains(@class,"categorySelectorV2")]//div[contains(text(),"中筒袜") and not(contains(@class,"disable"))]'
    tab = ProbeTab()
    element = tab.element_for(selector, text='中筒袜', class_name='styles_normal')
    category = EnhancedCategorySelector(tab)

    assert category._select_from_recommendations('中筒袜') is True
    assert tab.ele_calls == [selector]
    assert element.click_count == 1


def test_current_category_uses_one_probe_but_still_checks_selected_text():
    selector = 'xpath://div[contains(@class,"recommendContainer")]//div[contains(@class,"itemSelected")]'
    tab = ProbeTab()
    tab.element_for(selector, text='服装 > 内衣裤袜 > 袜子 > 中筒袜', class_name='itemSelected')
    category = EnhancedCategorySelector(tab)

    assert category._is_current_category('中筒袜') is True
    assert category._is_current_category('长筒袜') is False
    assert tab.ele_calls == [selector, selector]


def test_manual_entry_absence_does_not_serial_wait_every_xpath():
    tab = ProbeTab()
    category = EnhancedCategorySelector(tab)

    assert category._is_manual_select_visible() is False
    assert tab.ele_calls == []


def test_manual_entry_falls_back_to_serial_lookup_when_js_is_unavailable():
    selector = 'xpath://span[text()="手动选择"]/..'
    tab = ProbeTab(js_available=False)
    tab.element_for(selector)
    category = EnhancedCategorySelector(tab)

    assert category._is_manual_select_visible() is True
    assert len(tab.ele_calls) == 2

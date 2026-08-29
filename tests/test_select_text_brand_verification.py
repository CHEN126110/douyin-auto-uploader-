# -*- coding: utf-8 -*-
"""下拉属性（品牌等）选择结果校验的回归测试（2026-08-27 实盘故障）。

实盘现象：商品发布后「品牌 / 无品牌」没有填上，但流程一路跑完没有任何报错。

根因（已在真实页面用 CDP 实证）：
抖店的品牌字段是 `ecom-g-select-show-search` 组件，
`//div[@attr-field-id="品牌"]//input` 命中的是**搜索框**，其 `value` 恒为空串；
真正的选中值存放在 `.ecom-g-select-selection-item` 上。

旧实现的成功判据是「input.value 命中目标 **或** 下拉菜单消失」——
前半永远为假，于是只剩「菜单消失就算成功」，点空/点错/组件回滚都会被判成功，
最终品牌漏填却报成功。
"""

import os
import sys
import types

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from src.utils import get_select_field_value, select_text  # noqa: E402


class FakeElement:
    def __init__(self, text='', title='', displayed=True):
        self._text = text
        self._title = title
        self.states = types.SimpleNamespace(is_displayed=displayed)
        self.clicked = 0

    @property
    def text(self):
        return self._text

    def attr(self, name):
        if name == 'title':
            return self._title
        if name == 'value':
            # 搜索型 select 的输入框 value 恒为空——这正是旧判据失效的原因
            return ''
        return None

    def click(self, by_js=False):
        self.clicked += 1

    def input(self, value, clear=False):
        return self

    def ele(self, selector, timeout=None):
        return None


class BrandSelectTab:
    """模拟 ecom-g Select：选中值只体现在 selection-item 上。"""

    def __init__(self, selected='', option_clickable=True, dropdown_open=True):
        self.selected = selected
        self.option_clickable = option_clickable
        self.dropdown_open = dropdown_open
        self.search_input = FakeElement()
        self.option = FakeElement(text='无品牌', title='无品牌')

    def _selection_item(self):
        if not self.selected:
            return None
        return FakeElement(text=self.selected, title='')

    def ele(self, selector, timeout=None):
        if 'select-selection-item' in selector:
            return self._selection_item()
        if 'auto-dropdown-id-' in selector or 'ecom-g-select-dropdown' in selector:
            return _FakeDropdown(self) if self.dropdown_open else None
        if '//input' in selector:
            return self.search_input
        return None

    def eles(self, selector, timeout=None):
        return []


class _FakeDropdown:
    def __init__(self, tab):
        self.tab = tab
        self.states = types.SimpleNamespace(is_displayed=True)

    def ele(self, selector, timeout=None):
        if '无品牌' in selector:
            option = self.tab.option
            if self.tab.option_clickable:
                # 点击后组件真的把值写入 selection-item
                original_click = option.click

                def click(by_js=False):
                    original_click(by_js)
                    self.tab.selected = '无品牌'

                option.click = click
            return option
        return None


def test_reads_selected_value_from_selection_item_not_input():
    """选中值必须从 selection-item 读取——输入框 value 恒为空。"""
    tab = BrandSelectTab(selected='无品牌')
    assert get_select_field_value(tab, '品牌') == '无品牌'
    # 证明不能依赖 input.value
    assert tab.search_input.attr('value') == ''


def test_returns_true_when_option_click_actually_sets_value():
    tab = BrandSelectTab(selected='')
    assert select_text(tab, '品牌', '无品牌') is True
    assert tab.selected == '无品牌'


def test_skips_work_when_already_set():
    """已是目标值时直接返回成功，不再点开下拉（同时也是性能优化）。"""
    tab = BrandSelectTab(selected='无品牌')
    assert select_text(tab, '品牌', '无品牌') is True
    assert tab.option.clicked == 0


def test_returns_false_when_dropdown_closes_without_setting_value():
    """核心回归：菜单关闭但值没写入时必须判失败，不能再当成功。"""
    tab = BrandSelectTab(selected='', option_clickable=False)
    assert select_text(tab, '品牌', '无品牌') is False
    assert tab.selected == ''


def test_returns_false_when_field_missing():
    class EmptyTab:
        def ele(self, selector, timeout=None):
            return None

        def eles(self, selector, timeout=None):
            return []

    assert select_text(EmptyTab(), '品牌', '无品牌') is False


def test_brand_failure_raises_in_publish_flow():
    """发布流程必须在品牌设置失败时中断——无品牌是合规硬约束，不能静默漏填。"""
    import io

    app_py = os.path.join(REPO_ROOT, 'tauri-app', 'python-sidecar', 'app.py')
    source = io.open(app_py, encoding='utf-8').read()

    # 品牌统一走 ensure_no_brand()：它会先收起会遮挡品牌字段的材质浮层，
    # 再优先点「可选无品牌」快捷链接，失败才回退通用下拉选择。
    assert source.count('ensure_no_brand(main_tab)') == 3, \
        '品牌调用点数量变化，请同步检查失败处理'
    assert source.count("raise Exception('品牌未能设置为「无品牌」')") == 3, \
        '每个品牌调用点都必须在失败时抛错，不能静默继续'
    assert "select_text(main_tab, '品牌'" not in source, \
        '品牌不得绕过 ensure_no_brand 直接调用 select_text'

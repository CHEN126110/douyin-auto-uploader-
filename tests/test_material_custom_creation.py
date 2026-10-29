# -*- coding: utf-8 -*-
"""平台等价材质、内联新建和按名称填写比例的回归测试。"""
from src import utils


def test_official_jinlun_alias_is_accepted_without_creating_a_duplicate():
    actual = ['聚酰胺纤维（锦纶/尼龙）']
    targets = [('聚酰胺纤维（锦纶）', '25')]
    assert utils._material_indexes_for_targets(actual, targets) == [0]
    area = type('Area', (), {'run_js': lambda self, script: ['聚酰胺纤维（锦纶/尼龙） 25%']})()
    assert utils._aurora_material_selection_matches(area, targets) is True


def test_alias_search_retries_the_base_material_name():
    terms = utils._material_search_terms('聚酰胺纤维（锦纶）')
    assert terms[0] == '聚酰胺纤维（锦纶）'
    assert '聚酰胺纤维' in terms


def test_missing_or_ambiguous_material_cannot_proceed_to_ratio_fill():
    assert utils._material_indexes_for_targets(['棉', '聚酯纤维'], [('棉', '75'), ('氨纶', '25')]) is None
    ambiguous = ['聚酰胺纤维（锦纶）', '聚酰胺纤维（尼龙）']
    assert utils._material_indexes_for_targets(
        ambiguous, [('聚酰胺纤维（锦纶/尼龙）', '100')]) is None


def test_selected_order_does_not_change_target_identity():
    assert utils._material_indexes_for_targets(
        ['聚酯纤维', '棉'], [('棉', '75'), ('聚酯纤维', '25')]) == [1, 0]


class _Button:
    def __init__(self, action):
        self.action = action

    def click(self, by_js=False):
        self.action()


class _Input:
    def __init__(self):
        self.value = ''

    def click(self):
        return None

    def input(self, value):
        self.value = value

    def clear(self):
        self.value = ''

    def attr(self, name):
        return self.value if name == 'value' else None


class _CustomTab:
    def __init__(self, name):
        self.name = name
        self.create_open = False
        self.created = False
        self.name_input = _Input()
        self.create_clicks = 0
        self.confirm_clicks = 0

    def ele(self, selector, timeout=None):
        if '请输入材质' in selector:
            return self.name_input if self.create_open else None
        if '新建材质' in selector:
            def open_create():
                self.create_clicks += 1
                self.create_open = True
            return _Button(open_create)
        if '@alt="确认"' in selector:
            def confirm():
                self.confirm_clicks += 1
                self.created = True
            return _Button(confirm)
        raise AssertionError('不应定位其它控件：' + selector)

    def run_js(self, script, *args):
        if 'selected-label[title]' in script:
            return [self.name] if self.created else []
        return []


def test_inline_custom_material_is_created_and_read_back():
    tab = _CustomTab('测试自定义纤维')
    assert utils._create_aurora_material(tab, '测试自定义纤维') is True
    assert (tab.create_clicks, tab.confirm_clicks) == (1, 1)
    assert tab.name_input.value == '测试自定义纤维'


def test_ratio_is_located_by_material_row_title_not_configuration_index():
    tab = _CustomTab('聚酰胺纤维（锦纶/尼龙）')
    ratio_input = tab.name_input
    selectors = []

    def locate(selector, timeout=None):
        selectors.append(selector)
        return ratio_input

    tab.ele = locate
    assert utils._fill_aurora_material_ratio(tab, '聚酰胺纤维（锦纶/尼龙）', '25') is True
    assert ratio_input.value == '25'
    assert 'selected-row' in selectors[0]
    assert '聚酰胺纤维（锦纶/尼龙）' in selectors[0]


def test_final_verification_reads_complete_selected_rows():
    class Area:
        def __init__(self):
            self.script = ''

        def run_js(self, script):
            self.script = script
            return ['桑蚕丝 3%', '绵羊毛 3%', '聚酯纤维 44%',
                    '聚酰胺纤维（锦纶/尼龙） 25%', '聚丙烯腈纤维（腈纶） 24%',
                    '聚氨酯弹性纤维（氨纶） 1%']

    area = Area()
    materials = [('桑蚕丝', '3'), ('绵羊毛', '3'), ('聚酯纤维', '44'),
                 ('聚酰胺纤维（锦纶）', '25'), ('聚丙烯腈纤维（腈纶）', '24'),
                 ('聚氨酯弹性纤维（氨纶）', '1')]
    assert utils._aurora_material_selection_matches(area, materials) is True
    assert 'selected-row' in area.script
    assert 'doc.querySelectorAll' in area.script


def test_selected_titles_read_page_level_rows_not_only_wrapper_tags():
    class Tab:
        def run_js(self, script):
            self.script = script
            return ['棉']

    tab = Tab()
    assert utils._material_selected_titles(tab) == ['棉']
    assert "document.querySelectorAll(\n    '.aurora-dorami-composition-select-selected-row" in tab.script
    assert "wrapper.querySelectorAll(\n    '.aurora-dorami-composition-select-selected-row" not in tab.script


def test_platform_clear_button_is_used_and_read_back():
    state = {'cleared': False}

    class Area:
        def eles(self, selector, timeout=None):
            if state['cleared']:
                return []
            icon = type('Icon', (), {})()
            icon.states = type('States', (), {'is_displayed': True})()
            return [icon]

    class Tab:
        def __init__(self):
            self.clicks = 0

        def eles(self, selector, timeout=None):
            def clear():
                self.clicks += 1
                state['cleared'] = True
            button = _Button(clear)
            button.states = type('States', (), {'is_displayed': True})()
            return [button]

        def run_js(self, script):
            return '' if state['cleared'] else '已选 (6)'

    tab = Tab()
    assert utils._clear_aurora_composition_selection(tab, Area()) is True
    assert tab.clicks == 1 and state['cleared'] is True


def test_unrelated_aurora_dropdown_does_not_count_as_material_panel_open():
    assert "document.querySelectorAll('.aurora-dorami-composition-select-option-pane')" in utils._AURORA_PANEL_OPEN_JS
    assert '品牌、SKU 下拉和残留的 open 类名都不算' in utils._AURORA_PANEL_OPEN_JS
    assert 'openInWrapper' not in utils._AURORA_PANEL_OPEN_JS

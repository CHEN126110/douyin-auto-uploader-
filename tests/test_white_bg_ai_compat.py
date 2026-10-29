# -*- coding: utf-8 -*-
"""白底图 AI 面板的新旧效果图与底部动作兼容。"""
import ast
import io
import types

from src import utils

SOURCE = io.open(utils.__file__, encoding='utf-8').read()


def test_effect_probe_supports_legacy_compare_and_new_preview_confirm():
    tree = ast.parse(SOURCE)
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == '_get_ai_white_bg_effect_state')
    body = ast.get_source_segment(SOURCE, function)

    assert 'compareWrapper' in body
    assert 'imgPreviewWrapper' in body
    assert '上传' in body
    assert '确认' in body


class Button:
    def __init__(self):
        self.states = types.SimpleNamespace(is_displayed=True, is_enabled=True)
        self.click_count = 0

    def attr(self, name):
        return 'ecom-g-btn-primary' if name == 'class' else None

    def click(self, by_js=False):
        self.click_count += 1


class Panel:
    def __init__(self):
        self.button = Button()

    def eles(self, selector, timeout=None):
        return [self.button] if '确认' in selector else []


def test_footer_action_accepts_new_confirm_button():
    panel = Panel()

    assert utils._click_ai_material_footer_upload(panel) == '确认'
    assert panel.button.click_count == 1


def test_effect_ready_still_requires_a_new_effect():
    class Tab:
        def __init__(self, effect):
            self.effect = effect

        def run_js(self, script, *args):
            return {'ready': True, 'effect_src': self.effect}

    assert utils._ai_white_bg_effect_ready(Tab('new'), 'old') is True
    assert utils._ai_white_bg_effect_ready(Tab('same'), 'same') is False

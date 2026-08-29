# -*- coding: utf-8 -*-
"""材质面板遮挡品牌字段的回归测试（2026-08-28 实盘故障）。

现象：填完面料材质后报「品牌未能设置为「无品牌」」。

根因：aurora 材质多选面板（.aurora-dorami-composition-select-wrapper 的下拉）
是覆盖面很大的浮层，`_fill_aurora_composition_select` 填完占比后**直接 return，
从不收起它**。该浮层压住同屏的品牌字段，使随后的点击落在面板上而非目标字段。

修复：
1. 材质填写路径结束时调用 close_aurora_composition_panel() 收起浮层；
2. 品牌统一走 ensure_no_brand()：幂等 → 先收浮层 → 优先点「可选无品牌」快捷链接
   → 失败才回退 select_text。
"""

import io
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import src.utils as utils  # noqa: E402

UTILS_PY = os.path.join(REPO_ROOT, 'src', 'utils.py')


class FakeTab:
    """按脚本返回面板状态；记录收到的每一段 JS。"""

    def __init__(self, open_states):
        self.open_states = list(open_states)
        self.dismiss_calls = 0
        self.brand_value = ''
        self.shortcut_clicked = False

    def run_js(self, script, *args):
        if 'aurora' in script and 'select-open' in script:
            return self.open_states.pop(0) if self.open_states else False
        if 'Escape' in script and 'mousedown' in script:
            self.dismiss_calls += 1
            if self.open_states:
                self.open_states = [False] * len(self.open_states)
            return True
        if 'attr-field-id="品牌"' in script and 'hasShortcut' in script:
            return {'present': True, 'current': self.brand_value, 'hasShortcut': True, 'x': 10, 'y': 20}
        if 'attr-field-id="品牌"' in script:
            self.shortcut_clicked = True
            self.brand_value = '无品牌'
            return True
        return None

    def ele(self, selector, timeout=None):
        return None

    def eles(self, selector, timeout=None):
        return []


def test_close_panel_is_noop_when_already_closed():
    tab = FakeTab([False])
    assert utils.close_aurora_composition_panel(tab) is True
    assert tab.dismiss_calls == 0, '面板本就关闭时不应做多余操作'


def test_close_panel_dismisses_open_panel():
    tab = FakeTab([True, False, False])
    assert utils.close_aurora_composition_panel(tab) is True
    assert tab.dismiss_calls >= 1, '面板展开时必须主动收起'


def test_material_fill_path_closes_panel_before_returning():
    """核心回归：aurora 材质填写路径结束前必须收起浮层，否则会遮挡品牌字段。"""
    source = io.open(UTILS_PY, encoding='utf-8').read()
    body = source.split('def _fill_aurora_composition_select', 1)[1].split('\ndef ', 1)[0]
    assert 'close_aurora_composition_panel' in body, \
        '材质填写路径必须在结束前收起下拉面板，否则会遮挡品牌等相邻字段'


def test_ensure_no_brand_is_idempotent():
    """已经是「无品牌」时直接返回，不再打开下拉、不再点击。"""
    tab = FakeTab([False])
    tab.brand_value = '无品牌'
    assert utils.ensure_no_brand(tab) is True
    assert tab.shortcut_clicked is False, '已是无品牌时不应再点击'


def test_ensure_no_brand_uses_shortcut_link():
    """未设置时优先走「可选无品牌」快捷链接，并读回真实值确认。"""
    tab = FakeTab([False, False])
    assert utils.ensure_no_brand(tab) is True
    assert tab.shortcut_clicked is True
    assert tab.brand_value == '无品牌'


def test_ensure_no_brand_closes_panel_first():
    """设置品牌前必须先收起材质浮层——这正是实盘失败的根因。"""
    source = io.open(UTILS_PY, encoding='utf-8').read()
    body = source.split('def ensure_no_brand', 1)[1].split('\ndef ', 1)[0]
    close_pos = body.find('close_aurora_composition_panel')
    click_pos = body.find('_CLICK_NO_BRAND_SHORTCUT_JS')
    fallback_pos = body.find("select_text(new_tab, '品牌'")
    assert close_pos != -1, '必须先收起材质浮层'
    assert click_pos == -1 or close_pos < click_pos, '收浮层必须早于点击快捷链接'
    assert fallback_pos == -1 or close_pos < fallback_pos, '收浮层必须早于回退的下拉选择'

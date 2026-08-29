# -*- coding: utf-8 -*-
"""类目展开状态跨商品复位的回归测试（2026-08-28）。

`src/utils.py` 用模块级全局变量 `_category_expanded` 缓存「类目属性区是否已展开」，
一旦置 True 就不会再复位。它的复位函数 `reset_category_expanded_state()`
docstring 写明「在新商品上传开始时调用」，但此前**全仓库没有任何调用方**。

后果：批量发布时第 2 个商品起 `_expand_category_more()` 直接短路返回，
类目属性区不展开，品牌 / 适用人群 / 适用性别 / 筒高等字段全部定位不到。
品牌失败现在会中断发布（无品牌是合规硬约束），所以这个缺陷会让第 2 个商品直接失败。
"""

import io
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import src.utils as utils  # noqa: E402

APP_PY = os.path.join(REPO_ROOT, 'tauri-app', 'python-sidecar', 'app.py')


def test_reset_function_actually_clears_the_flag():
    utils._category_expanded = True
    utils.reset_category_expanded_state()
    assert utils._category_expanded is False


def test_expand_short_circuits_while_flag_is_set():
    """确认缺陷机制真实存在：flag 为 True 时 _expand_category_more 不做任何页面操作。"""
    calls = []

    class TrackingTab:
        def eles(self, selector, timeout=None):
            calls.append(selector)
            return []

        def ele(self, selector, timeout=None):
            calls.append(selector)
            return None

    utils._category_expanded = True
    utils._expand_category_more(TrackingTab())
    assert calls == [], 'flag 为 True 时应当短路，不触碰页面'

    utils.reset_category_expanded_state()
    utils._expand_category_more(TrackingTab())
    assert calls, '复位后应当重新尝试展开'


def test_upload_flow_resets_state_for_every_record():
    """发布流程必须在每条记录开始时复位，否则第 2 个商品起类目属性区不展开。"""
    source = io.open(APP_PY, encoding='utf-8').read()

    assert 'reset_category_expanded_state()' in source, \
        '发布流程必须调用 reset_category_expanded_state()，否则跨商品缓存不复位'

    # 必须位于「逐条记录」的循环体内，而不是循环外只调一次
    loop_marker = 'for record in record_list:'
    assert loop_marker in source, '未找到发布流程的记录循环，请同步更新本测试'
    loop_body = source.split(loop_marker, 1)[1]
    # 截到该循环结束（下一个顶层 def）为止，避免误判到别处
    loop_body = loop_body.split('\ndef ', 1)[0]
    assert 'reset_category_expanded_state()' in loop_body, \
        'reset_category_expanded_state() 必须在每条记录的循环体内调用'

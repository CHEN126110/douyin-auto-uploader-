# -*- coding: utf-8 -*-
"""SKU 文件选择入口必须先使用可触发原生文件对话框的点击方式。"""
from src.utils import _click_sku_upload_button


class Button:
    def __init__(self, native_error=False):
        self.native_error = native_error
        self.calls = []

    def click(self, by_js=False):
        self.calls.append(by_js)
        if self.native_error and not by_js:
            raise RuntimeError('native click blocked')


def test_sku_file_input_prefers_native_click():
    button = Button()

    _click_sku_upload_button(button)

    assert button.calls == [False]


def test_sku_file_input_keeps_js_fallback():
    button = Button(native_error=True)

    _click_sku_upload_button(button)

    assert button.calls == [False, True]

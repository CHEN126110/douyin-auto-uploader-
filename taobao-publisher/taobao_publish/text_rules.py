# -*- coding: utf-8 -*-
"""发布文本计数。上限来自契约，不能把样本上限推成所有类目的实时规则。"""


def count_title_units(text: str) -> int:
    """归档样本的汉字计 2、ASCII 计 1；统一原资料准备路径的计算方式。

    证据：captures/tb_publish_form_top_20261003.png。其它 Unicode 字符沿用
    一码点计数，属于尚未验证的部分，不能用此值证明平台计数已通过；
    实际写入仍需原值回读，并以目标类目的运行时规则为准。
    """
    return sum(2 if (
        '\u3400' <= char <= '\u9fff' or '\uf900' <= char <= '\ufaff'
        or '\U00020000' <= char <= '\U000323af'
    ) else 1 for char in text)

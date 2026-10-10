# -*- coding: utf-8 -*-
"""小红书千帆：本地可判定的业务规则（纯函数，不碰真机）。

目前只有一条，但它是**平台自己的错误文案 + 真机计数器实测**双重确定的硬规则：

    错误：请输入商品标题，16-60个字符（8-30个字）

实测把 28 个汉字写进标题框，页面计数器显示 `56/60` → **计数器对汉字按 2 计**。
所以"看着没超 60、实际已超"是真实存在的误判风险，必须在本地先算。
"""

from __future__ import annotations

from dataclasses import dataclass

#: 平台规则（来自页面错误文案 `请输入商品标题，16-60个字符（8-30个字）`，`verified`）
TITLE_MIN_UNITS = 16
TITLE_MAX_UNITS = 60
TITLE_MIN_WORDS = 8
TITLE_MAX_WORDS = 30


def title_units(text: str) -> int:
    """按平台计数器的口径算长度。

    证据：28 个汉字 → 页面显示 `56/60`（`verified`）。
    因此非 ASCII 字符按 2 计。ASCII 按 1 计属于**合理推断但未实测**（`candidate`）——
    发布前的安全做法是只用 `title_words()` 的汉字口径判断上限。
    """
    return sum(2 if ord(char) > 127 else 1 for char in text)


def title_words(text: str) -> int:
    """按"个字"口径数长度（平台文案里的 8-30 个字）。"""
    return len(text)


@dataclass(frozen=True)
class TitleCheck:
    """标题校验结果。`ok` 为 False 时 `reasons` 给出平台会报错的项。"""

    ok: bool
    units: int
    words: int
    reasons: tuple[str, ...]

    def describe(self) -> str:
        if self.ok:
            return "标题可用：{} 个字符 / {} 个字".format(self.units, self.words)
        return "标题不可用：{}（{} 个字符 / {} 个字）".format(
            "；".join(self.reasons), self.units, self.words)


def check_title(text: str) -> TitleCheck:
    """校验商品标题是否符合平台规则。

    平台会自动在标题前拼接品牌名称，所以标题本身**不应再带品牌**；
    本函数不判断品牌（那属于无品牌策略，另有约定），只判长度。
    """
    stripped = (text or "").strip()
    reasons: list[str] = []
    if not stripped:
        reasons.append("标题为空")
    units = title_units(stripped)
    words = title_words(stripped)
    if stripped and words < TITLE_MIN_WORDS:
        reasons.append("少于 {} 个字".format(TITLE_MIN_WORDS))
    if words > TITLE_MAX_WORDS:
        reasons.append("超过 {} 个字".format(TITLE_MAX_WORDS))
    if stripped and units < TITLE_MIN_UNITS:
        reasons.append("少于 {} 个字符".format(TITLE_MIN_UNITS))
    if units > TITLE_MAX_UNITS:
        reasons.append("超过 {} 个字符".format(TITLE_MAX_UNITS))
    return TitleCheck(ok=not reasons, units=units, words=words, reasons=tuple(reasons))

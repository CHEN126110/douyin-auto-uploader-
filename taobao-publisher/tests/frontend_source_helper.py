# -*- coding: utf-8 -*-
"""前端源码的注释剥离助手 —— **共享一份**，别再各写各的。

## 为什么要有这个文件

针对前端源码的断言反复被「注释」骗到（至少六次）。每次都得记得先剥注释，
而各写各的实现就会各踩各的坑。

## 这一版踩的坑（2026-10-03）

原来写的是对整份文件跑 `re.sub(r"/\\*.*?\\*/", "", text, flags=re.S)`。
而 `TaobaoPublishPanel.vue` 第 469 行有一句**行注释**：

```ts
// 与抖店的 /api/upload/* 同一套交互：启动 → 轮询 status → 展示进度与阶段。
```

`/api/upload/*` 里的 `/*` **不是注释开头**。正则从那里开始匹配，
一直吃到第 903 行 `<style>` 里的 `*/` —— **吃掉了 17097 个字符**，
把 `startPublish` 和整个 `<template>` 都删没了。

后果是两个用例**假失败**（说找不到 `realPublish,`）。

**正则分不清「注释开头」和「路径里的 `/*`」**，所以改成**按行**判断：

* 整行以 `//` 或 `*` 开头 → 置空；
* 整行以 `/*` 开头 → 进入块注释，直到某行含 `*/`；
* 其余行原样保留（行尾注释也保留——宁可多留，不要误删）。
"""

from __future__ import annotations

__all__ = ["code_only", "script_section"]


def code_only(text: str) -> str:
    """去掉**整行**注释，只留代码；行号一一对应（注释行置空而不是删掉）。

    ⚠️ **不对整份文件跑块注释正则**——理由见模块文档字符串。
    """

    result = []
    in_block = False
    for line in text.splitlines():
        stripped = line.lstrip()
        if in_block:
            result.append("")
            if "*/" in line:
                in_block = False
            continue
        if stripped.startswith("/*"):
            result.append("")
            if "*/" not in stripped:
                in_block = True
            continue
        if stripped.startswith(("//", "*")):
            result.append("")
            continue
        result.append(line)
    return "\n".join(result)


def script_section(text: str) -> str:
    """只取 ``<script setup>`` 那一段。模板与样式里的同名串不该参与断言。"""

    start = text.find("<script")
    if start < 0:
        return text
    start = text.find(">", start) + 1
    end = text.find("</script>", start)
    return text[start:end] if end > 0 else text[start:]

# -*- coding: utf-8 -*-
"""pytest 会话级修复：让临时目录在本机可写。

本会话的沙箱会给 `tempfile.mkdtemp()` 造出来的目录带上「拒绝访问」的 ACL：
`os.listdir()` 直接抛 `PermissionError: [WinError 5]`，于是
`tempfile.NamedTemporaryFile` 在 `_mkstemp_inner` 的 `while True` 里无限自旋
（100% CPU、永远不返回）。仓库里所有店铺会话测试都用临时目录做隔离，
结果整个套件都卡在 `src/shop_session.py` 的 `save_registry` 上。

修复方式：把 `mkdtemp` 换成「自己用 `os.makedirs` 建目录」——实测这样建出来的
目录读写都正常，而 `mkdtemp` 建出来的不行。

**只影响测试隔离目录，不碰任何生产代码路径。** 权限正常的机器上
`os.makedirs` 与 `mkdtemp` 行为一致，所以这个替换对结果没有影响。
"""

from __future__ import annotations

import itertools
import os
import tempfile

_counter = itertools.count(1)


def _mkdtemp_writable(suffix=None, prefix=None, dir=None):
    """建一个可写的唯一临时目录。

    刻意不用 `tempfile.mkdtemp`：它在这个环境下会给出拒绝访问的目录。
    候选名带 pid 与自增序号，保证同进程内唯一（不依赖 `tempfile` 内部那个
    非线程安全的生成器）。
    """
    base = dir if dir is not None else tempfile.gettempdir()
    os.makedirs(base, exist_ok=True)
    head = prefix if prefix is not None else "tmp"
    tail = suffix if suffix is not None else ""
    for _ in range(10000):
        candidate = os.path.join(base, "{}{}_{}{}".format(head, os.getpid(), next(_counter), tail))
        try:
            os.makedirs(candidate)
        except FileExistsError:
            continue
        return candidate
    raise FileExistsError("无法创建唯一的临时目录：{}".format(base))


tempfile.mkdtemp = _mkdtemp_writable
# TemporaryDirectory 内部走的是这个类属性，替换后它建出来的目录同样可写。
tempfile.TemporaryDirectory._mkdtemp = staticmethod(_mkdtemp_writable)

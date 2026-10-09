# -*- coding: utf-8 -*-
"""把 page.py 里**每一个** build_* 构造器都真的调用一次，抓出花括号错误。

``unexpected '{' in field name`` 只在 ``.format()`` **被调用时**才抛，
所以「读了源码没看到单花括号」不等于「不会炸」——必须真的调一遍。

⚠️ **逻辑已经收进 ``taobao_publish/selfcheck.py``**，本脚本只是薄壳。
两处各存一份 ``ARG_CASES`` 迟早会漂移——本轮就踩过一次：
旧脚本里同一个键写了两次，Python 字典取后者，**前一行是死代码**。

统一入口是::

    python -m taobao_publish check
"""

from __future__ import annotations

import sys
from pathlib import Path

SUBPROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SUBPROJECT))

from taobao_publish.selfcheck import check_builders  # noqa: E402


def main() -> int:
    result = check_builders()
    print(result.detail)
    if result.ok:
        print("全部通过：没有花括号错误，也没有残留双花括号")
        return 0
    print()
    print("**失败 {} 处**".format(len(result.failures)))
    for failure in result.failures:
        print("  {}".format(failure))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

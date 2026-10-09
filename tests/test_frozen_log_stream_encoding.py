# -*- coding: utf-8 -*-
"""打包运行时的日志流必须是 utf-8。

`src/constants.py` 在 frozen 模式下会把 `sys.stdout` / `sys.stderr` 换成文件流，
这会覆盖掉 `app.py` 里装的 `_SafeConsoleStream`。如果 open() 不显式指定编码，
就会用系统 ANSI（中文 Windows 上是 GBK）且严格报错——代码里有几十处
`print('⚠ ...')`，任何一处执行到都会抛 UnicodeEncodeError 并被上层当成业务失败。

2026-09-06 实测：真实发布走到「填写规格与 SKU 信息」时因此中断，
报错是 `'gbk' codec can't encode character '\\u26a0'`。
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONSTANTS_PATH = PROJECT_ROOT / "src" / "constants.py"


class FrozenLogStreamEncodingTest(unittest.TestCase):
    def test_frozen_log_streams_declare_utf8(self) -> None:
        source = CONSTANTS_PATH.read_text(encoding="utf-8")
        redirects = re.findall(r"sys\.(?:stdout|stderr)\s*=\s*open\((.*?)\)\n", source)
        self.assertEqual(len(redirects), 2, "constants.py 里的日志重定向数量变了，请同步本用例")
        for args in redirects:
            self.assertIn("encoding='utf-8'", args.replace('"', "'"))
            self.assertIn("errors='replace'", args.replace('"', "'"))

    def test_warning_prints_still_exist_so_the_guard_matters(self) -> None:
        # 这个用例是为了说明上一个用例在防什么：代码里确实有非 GBK 字符的输出。
        utils_source = (PROJECT_ROOT / "src" / "utils.py").read_text(encoding="utf-8")
        self.assertIn("⚠", utils_source)


if __name__ == "__main__":
    unittest.main()

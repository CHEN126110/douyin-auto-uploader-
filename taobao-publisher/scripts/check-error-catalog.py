# -*- coding: utf-8 -*-
"""检查：**每个被抛出的错误码都在错误目录里**。

错误目录（``errors.ERROR_CATALOG``）是界面能说清「这是什么错、该怎么办」的唯一来源。
码不在目录里，界面上就只能显示一个光秃秃的英文标识符——**而这条以前真出过问题**：
一轮里 39 处页面异常抛的都是 ``PageError('msg')``，``.code`` 全是消息本身。

本脚本：
1. 静态扫 ``taobao_publish/*.py``，收集所有**像错误码**的字符串字面量
   （全大写下划线，且出现在 ``StageOutcome.failed`` / ``Blocker(code=`` / ``_spec`` 附近）；
2. 与 ``ERROR_CATALOG`` 比对，报出缺失的；
3. 反向也报一次：目录里有、但代码里从没用过的（不一定是错，只是提示）。

**只读。**

用法::

    python taobao-publisher/scripts/check-error-catalog.py
"""

from __future__ import annotations

import ast
import pathlib
import re
import sys

SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
SUBPROJECT = SCRIPT_DIR.parent
if str(SUBPROJECT) not in sys.path:
    sys.path.insert(0, str(SUBPROJECT))

from taobao_publish.errors import ERROR_CATALOG  # noqa: E402

PACKAGE = SUBPROJECT / "taobao_publish"

#: 错误码的形状：全大写 + 下划线，至少两段，长度 >= 6。
CODE_PATTERN = re.compile(r"^[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+$")

#: 这些全大写串不是错误码，是别的东西。
NOT_CODES = {
    "UTF_8", "ISO_8859_1", "TAOBAO_UPLOAD_ALLOW_WRITE", "TAOBAO_UPLOAD_ALLOW_SUBMIT",
    "DOUYIN_DATA_DIR", "SIDECAR_MODE", "SIDECAR_PORT", "PARENT_PID",
}


def collect_string_literals(path: pathlib.Path) -> set:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            text = node.value.strip()
            if CODE_PATTERN.match(text) and text not in NOT_CODES:
                found.add(text)
    return found


def main() -> int:
    files = sorted(PACKAGE.glob("*.py"))
    print("扫描 {} 个模块…".format(len(files)))

    used = {}
    for path in files:
        for code in collect_string_literals(path):
            used.setdefault(code, []).append(path.name)

    catalog = set(ERROR_CATALOG)

    # 只关心「像错误码且被当成错误码用」的：目录里的 + 出现在 failed()/Blocker 附近的。
    # 单纯的全大写串也可能是别的常量，所以用「目录 ∩ 用到」与「用到但不在目录」两向看。
    suspicious = {}
    for path in files:
        source = path.read_text(encoding="utf-8")
        # 三处会声明错误码的地方：
        #   1. ``StageOutcome.failed("CODE"``     —— 阶段失败
        #   2. ``Blocker(code="CODE"``            —— 阻塞项
        #   3. ``super().__init__("CODE"``        —— 异常类
        # 第 3 条原先漏了，于是 ``CandidateNotFound`` 这类被误报成
        # 「目录里有但代码里没用过」。
        patterns = (
            # 阶段失败
            r"StageOutcome\.failed\(\s*['\"]([A-Z][A-Z0-9_]+)['\"]",
            # 阻塞项
            r"Blocker\(\s*code=\s*['\"]([A-Z][A-Z0-9_]+)['\"]",
            # 异常类（旧写法：直接传给基类）
            r"super\(\)\.__init__\(\s*['\"]([A-Z][A-Z0-9_]+)['\"]",
            # 异常类的**类属性**——主流写法，原先漏了
            r"^\s*code\s*=\s*['\"]([A-Z][A-Z0-9_]+)['\"]",
        )
        for pattern in patterns:
            for match in re.finditer(pattern, source, re.M if pattern.startswith("^") else 0):
                suspicious.setdefault(match.group(1), []).append(path.name)

    print()
    print("==== 被当作错误码用的（StageOutcome.failed / Blocker(code=)）====")
    print("  共 {} 个".format(len(suspicious)))
    missing = sorted(code for code in suspicious if code not in catalog)
    if missing:
        print()
        print("  ❌ **不在错误目录里的 {} 个**：".format(len(missing)))
        for code in missing:
            print("     {:<32} 出现于 {}".format(code, "、".join(sorted(set(suspicious[code])))))
    else:
        print("  ✅ 全部都在错误目录里")

    print()
    print("==== 目录里有、但代码里没被当错误码用过的 ====")
    unused = sorted(code for code in catalog if code not in suspicious)
    if unused:
        for code in unused:
            print("     {}".format(code))
    else:
        print("     （无）")

    print()
    print("==== 汇总 ====")
    print("  目录条目: {}".format(len(catalog)))
    print("  代码里用到: {}".format(len(suspicious)))
    print("  缺失: {}".format(len(missing)))
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())

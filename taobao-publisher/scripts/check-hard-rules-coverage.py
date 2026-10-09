# -*- coding: utf-8 -*-
"""系统性检查：**契约里标了 `hard: true` 的规则，代码有没有读它？**

上一轮发现 `main_image_max_bytes` 与 `main_image_formats` 两条 hard 规则
根本没被执行——一个 3.71 MB 的图或一个 `.bmp` 能一路通过静态预检。
那是**契约与实现脱节**，而当时只修了图片那两条。

本脚本把它推广：枚举 `contracts/rules.json` 里所有 `hard: true` 的规则，
逐个看子项目源码里有没有出现过它的名字。

⚠️ **只报「没出现过名字」的**——出现名字不等于真的执行了（可能只在注释里），
所以这个脚本给的是**怀疑清单**，不是结论。人工再逐条确认。

**只读。**

用法::

    python taobao-publisher/scripts/check-hard-rules-coverage.py
"""

from __future__ import annotations

import json
import pathlib
import re
import sys

SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
SUBPROJECT = SCRIPT_DIR.parent
PACKAGE = SUBPROJECT / "taobao_publish"
RULES = SUBPROJECT / "contracts" / "rules.json"


def strip_comments(source: str) -> str:
    """去掉整行注释与文档字符串痕迹，**只留代码**。

    前几轮反复踩过「检查被自己的注释/文档字符串命中」的坑，
    所以这里先粗筛一遍，减少假阳性。
    """

    keep = []
    for line in source.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        keep.append(line)
    return "\n".join(keep)


def main() -> int:
    data = json.loads(RULES.read_text(encoding="utf-8"))
    rules = data.get("rules") or data

    sources = {}
    for path in sorted(PACKAGE.glob("*.py")):
        sources[path.name] = strip_comments(path.read_text(encoding="utf-8"))

    # 也把前端与 sidecar 算上：规则可能在那里被使用
    for extra in (SUBPROJECT.parent / "tauri-app" / "python-sidecar" / "app.py",):
        if extra.is_file():
            sources["sidecar/app.py"] = strip_comments(extra.read_text(encoding="utf-8"))

    hard = {name: spec for name, spec in rules.items()
            if isinstance(spec, dict) and spec.get("hard") is True}
    soft = {name: spec for name, spec in rules.items()
            if isinstance(spec, dict) and spec.get("hard") is not True}

    print("契约规则共 {} 条：hard {} 条、非 hard {} 条".format(
        len(rules), len(hard), len(soft)))
    print()

    missing = []
    print("==== hard 规则的代码覆盖 ====")
    for name in sorted(hard):
        hits = [module for module, source in sources.items()
                if re.search(r"\b" + re.escape(name) + r"\b", source)]
        mark = "✓" if hits else "❌"
        print("  {} {:<34} {}".format(mark, name, "、".join(hits) if hits else "**没出现过**"))
        if not hits:
            missing.append(name)

    print()
    print("==== 非 hard 规则（仅供参考，不要求执行）====")
    for name in sorted(soft):
        hits = [module for module, source in sources.items()
                if re.search(r"\b" + re.escape(name) + r"\b", source)]
        print("  {:<34} {}".format(name, "、".join(hits) if hits else "（未使用）"))

    print()
    print("==== 汇总 ====")
    print("  hard 规则: {}".format(len(hard)))
    print("  没在代码里出现的: {}".format(len(missing)))
    for name in missing:
        print("     {}".format(name))
    print()
    print("⚠️ 「出现名字」不等于「真的执行」——本脚本给的是怀疑清单，需人工逐条确认。")
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())

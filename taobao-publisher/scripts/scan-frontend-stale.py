# -*- coding: utf-8 -*-
"""把「陈旧说法」扫描扩到**淘宝相关的前端代码**。

第 43 轮的扫描器只扫 `taobao_publish/` 这个 Python 包。
但最近三轮发现的矛盾**全在前端**：

| 轮次 | 前端说的 | 实际 |
|---|---|---|
| 42 | 前端守卫要求 `automatic_publish_ready === false` | 后端已如实报告 |
| 42 | `types` 里写死 `: false` | 同上 |
| 53 | 按钮写「开始校对（dry-run）」 | 已支持真实发布 |

所以把扫描扩到前端。⚠️ **只报告，不下结论**——有些说法是对的。

用法::

    python taobao-publisher/scripts/scan-frontend-stale.py
"""

from __future__ import annotations

import pathlib
import re
import sys

SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
SUBPROJECT = SCRIPT_DIR.parent
REPO_ROOT = SUBPROJECT.parent
TAURI_SRC = REPO_ROOT / "tauri-app" / "src"

#: 与淘宝相关的文件（按内容匹配，不按文件名）
TAOBAO_MARKERS = ("taobao", "Taobao", "淘宝")

#: 看起来像「还没做 / 不提供 / 固定」的说法。
STALE_PHRASES = (
    "尚未实现", "暂未实现", "未启用", "不支持", "尚未支持", "还没实现",
    "界面不提供", "不提供开关", "当前固定为", "固定为", "尚未接通",
    "尚未落地", "待实现",
)

#: 数值上的断言：写死的布尔
HARDCODED = (
    r":\s*false;",     # 类型里写死 false
    r":\s*true;",
)


def strip_line_comments(text: str) -> str:
    """按行去掉注释——**不能对整份前端文件跑块注释正则**
    （路径里的 `/api/upload/*` 会被当成注释开头，实测吃掉 17097 字符）。"""

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


def main() -> int:
    if not TAURI_SRC.is_dir():
        print("找不到前端源码目录：{}".format(TAURI_SRC))
        return 1

    findings = []
    scanned = []
    for path in sorted(TAURI_SRC.rglob("*")):
        if not path.is_file() or path.suffix not in (".ts", ".vue"):
            continue
        raw = path.read_text(encoding="utf-8", errors="replace")
        # 只扫与淘宝相关的文件
        if not any(marker in raw for marker in TAOBAO_MARKERS):
            continue
        scanned.append(path.name)
        code = strip_line_comments(raw)

        for phrase in STALE_PHRASES:
            for match in re.finditer(re.escape(phrase), code):
                line = code[:match.start()].count("\n") + 1
                text = code.splitlines()[line - 1].strip()
                findings.append((path.name, line, phrase, text[:96]))

    print("扫了 {} 个与淘宝相关的前端文件：".format(len(scanned)))
    for name in scanned:
        print("  - {}".format(name))
    print()

    if not findings:
        print("没有发现可疑的陈旧说法")
        return 0

    print("==== 可疑说法（{} 处）====".format(len(findings)))
    for name, line, phrase, text in findings:
        print("  {}:{}".format(name, line))
        print("      [{}] {}".format(phrase, text))

    print()
    print("⚠️ **这只是清单**——有些说法是对的（例如对抖店/协议模块的描述）。逐条人工确认。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# -*- coding: utf-8 -*-
"""扫一遍「陈旧说法」：还有哪些地方在说「尚未实现 / 未启用 / 不支持」。

上一轮发现**同一个陈旧值被复制到了两条独立的链**——修一处看起来完成了，
另一半还在。这个脚本把「还有别处吗」变成可枚举的。

扫三类：

1. **陈旧文案** —— 「尚未实现 / 未启用 / 不支持自动 / 暂未实现」等；
2. **硬编码布尔** —— 淘宝响应里写死的 ``True`` / ``False``；
3. **旧模式名** —— ``manual_preparation`` 之类。

⚠️ 只报告，不下结论——有些说法是**正确**的（例如资料包 manifest 的
``mode: manual_preparation`` 描述的是产物本身，不是应用能力）。
**只读。**

用法::

    python taobao-publisher/scripts/scan-stale-claims.py
"""

from __future__ import annotations

import pathlib
import re
import sys

SUBPROJECT = pathlib.Path(__file__).resolve().parent.parent
REPO_ROOT = SUBPROJECT.parent

#: 看起来像「还没做」的说法。
STALE_PHRASES = (
    "尚未实现", "暂未实现", "未启用", "不支持自动", "尚未支持",
    "未开发", "还没实现", "尚未接通",
)

#: 旧的模式名 / 状态值。
STALE_TOKENS = ("manual_preparation",)

#: 只看这些后缀。
SUFFIXES = (".py", ".ts", ".vue", ".md")

#: 跳过历史记录与临时目录——那里的「尚未实现」是当时的真实记录。
SKIP_DIRS = {
    "tmp", "node_modules", "dist", "build", "target", "__pycache__",
    "docs",  # 证据日志里的历史说法是有意保留的
    "项目备份 禁止改动使用 只参考", "app3.0版本",
}


def iter_files(base: pathlib.Path):
    for path in base.rglob("*"):
        if not path.is_file() or path.suffix not in SUFFIXES:
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        yield path


def blank_comments(text: str) -> str:
    """把注释**替换成空行**——既躲开「被自己的注释骗」，又保住行号。

    ⚠️ 第一版是 `strip_comments()`：直接**删掉**注释行再拼接，于是后续
    ``code[:start].count("\n")`` 算出来的是**去注释后的行号**，
    报出去的位置与真实文件对不上。**报告里给错行号比不给更糟**——
    看的人会去错的地方找。

    块注释同理：逐行替换成空行，不改变总行数。
    """

    # 先处理块注释：按行判断是否落在 /* ... */ 里
    lines = text.splitlines()
    result = []
    in_block = False
    for line in lines:
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
        if stripped.startswith(("#", "//", "*")):
            result.append("")
            continue
        # 行尾注释：一并去掉，避免 «"字符串里的旧说法" // 说明» 这种被误判
        result.append(re.sub(r"\s+(#|//).*$", "", line))
    return "\n".join(result)


def main() -> int:
    bases = [SUBPROJECT / "taobao_publish", REPO_ROOT / "tauri-app" / "src",
             REPO_ROOT / "tauri-app" / "python-sidecar"]

    print("=" * 74)
    print("扫描陈旧说法（行号按**原文件**计）")
    print("=" * 74)

    findings = []
    for base in bases:
        if not base.is_dir():
            continue
        for path in iter_files(base):
            raw = path.read_text(encoding="utf-8", errors="replace")
            code = blank_comments(raw)
            relative = path.relative_to(REPO_ROOT).as_posix()

            # 1) 陈旧文案：字符串字面量里才算（注释已去掉）
            for phrase in STALE_PHRASES:
                for match in re.finditer(r'["\'`][^"\'`]*' + re.escape(phrase), code):
                    line = code[:match.start()].count("\n") + 1
                    findings.append(("文案", relative, line, phrase,
                                     match.group(0)[:78]))

            # 2) 硬编码布尔（只在看起来像淘宝响应的地方）
            if "taobao" in relative.lower() or "desktop" in relative:
                for match in re.finditer(
                        r'["\'](\w*ready\w*|\w*publish\w*)["\']\s*:\s*(True|False)\b', code):
                    line = code[:match.start()].count("\n") + 1
                    findings.append(("硬编码布尔", relative, line,
                                     match.group(1), match.group(0)[:70]))

            # 3) 旧模式名（字符串字面量）
            for token in STALE_TOKENS:
                for match in re.finditer(r'["\'`]' + re.escape(token) + r'["\'`]', code):
                    line = code[:match.start()].count("\n") + 1
                    findings.append(("旧模式名", relative, line, token,
                                     match.group(0)[:70]))

    if not findings:
        print("没有发现可疑的陈旧说法")
        return 0

    for kind in ("文案", "硬编码布尔", "旧模式名"):
        group = [f for f in findings if f[0] == kind]
        if not group:
            continue
        print()
        print("==== {}（{} 处）====".format(kind, len(group)))
        for _, relative, line, token, text in group:
            print("  {}:{}".format(relative, line))
            print("      {} → {}".format(token, text))

    print()
    print("=" * 74)
    print("共 {} 处。**这只是清单，不是结论**——".format(len(findings)))
    print("有些说法是正确的（例如资料包 manifest 描述产物本身）。逐条人工确认。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# -*- coding: utf-8 -*-
"""离线粗查：`模块.属性` 里用了、但整个文件从未绑定过的名字。

## 为什么要它（真机 2026-10-10）

`tauri-app/python-sidecar/app.py` 在发布流水线跑完之后记录本地图片目录索引时调用了
``product_media.save_receipts(...)``，而 ``app.py`` **从未导入** ``product_media``：

* 这是个 ``NameError``，而包住它的 ``except (ValueError, OSError)`` 接不住；
* 异常穿透到任务层 → **阶段明细里 11 个阶段全部 ok 的任务被报成「淘宝发布失败」**；
* 用户看到的是「发布被截停」，实际平台侧全做完了（填写、回读都通过）。

这个类型的特点：**源码读起来完全正常，只有在真正执行到那一行时才炸**，
而它偏偏在最不容易被离线测试覆盖的收尾路径上。所以加一条廉价的自查。

⚠️ 它是**粗查**，不是 pyflakes：只报「作为属性访问根、且文件里没有任何绑定」的名字，
不查局部作用域、不查未使用变量。**不等于**可以拿它替代真正的静态检查。

跑法：

    python taobao-publisher/scripts/audit-undefined-modules.py tauri-app/python-sidecar/app.py
    python taobao-publisher/scripts/audit-undefined-modules.py taobao-publisher/taobao_publish/*.py
"""
from __future__ import annotations

import ast
import builtins
import sys
from pathlib import Path


def bound_names(tree: ast.AST) -> set:
    """文件里所有可能的绑定：导入、赋值、函数/类名、各种参数、异常名、with/for 目标。"""

    bound = set(dir(builtins))
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                bound.add((alias.asname or alias.name).split(".")[0])
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound.add(node.name)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                arguments = node.args
                for arg in (*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs):
                    bound.add(arg.arg)
                if arguments.vararg:
                    bound.add(arguments.vararg.arg)
                if arguments.kwarg:
                    bound.add(arguments.kwarg.arg)
        elif isinstance(node, ast.Lambda):
            arguments = node.args
            for arg in (*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs):
                bound.add(arg.arg)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            bound.add(node.id)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            bound.add(node.name)
        elif isinstance(node, ast.withitem) and isinstance(node.optional_vars, ast.Name):
            bound.add(node.optional_vars.id)
        elif isinstance(node, ast.comprehension):
            for target in ast.walk(node.target):
                if isinstance(target, ast.Name):
                    bound.add(target.id)
    return bound


def audit(path: Path) -> dict:
    """返回 ``{未绑定名: {用到的属性}}``；空字典表示没查出问题。"""

    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    bound = bound_names(tree)
    suspects: dict = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            if node.value.id not in bound:
                suspects.setdefault(node.value.id, set()).add(node.attr)
    return suspects


def main(argv: list) -> int:
    targets = [Path(item) for item in argv[1:]]
    if not targets:
        print("用法：python audit-undefined-modules.py <文件> [文件...]")
        return 2
    failed = 0
    for path in targets:
        suspects = audit(path)
        if not suspects:
            print("{}：粗查通过".format(path))
            continue
        failed += 1
        for name in sorted(suspects):
            print("{}：未绑定却当模块用 → {}（属性：{}）".format(
                path, name, "、".join(sorted(suspects[name])[:8])))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

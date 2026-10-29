# -*- coding: utf-8 -*-
"""Sidecar / 前端源码的统一读取入口（2026-10-20）。

``tauri-app/python-sidecar/app.py`` 已经按业务域拆进 ``src/sidecar/``（Blueprint + 服务类），
设置页、主页面也拆成了 ``components/settings/``、``composables/``。检查脚本和测试如果还只读 ``app.py`` /
``SettingsPanel.vue`` / ``ProductManager.vue``，就会因为「函数不在原来的文件里」而假失败，
或者更糟——静默少统计（比如路由清单里漏掉搬走的 ``/api/shop/*``）。

这里统一提供三件事：

* ``text()``：``app.py`` 与 ``src/sidecar/**/*.py`` 的全部源码（用于「某个字符串 / 路由是否存在」这类断言）；
* ``function_source(name, ...)``：按函数名取源码——AST 定位，不依赖装饰器写法 / 缩进（路由现在是 Blueprint 工厂里的闭包，
  不再是顶层的 ``@app.get``），也不靠「下一个 ``\\n@app.`` 之前」这类文本切片；
* ``routes()``：从装饰器里取出所有路由（``@app.xxx`` 和 ``@routes.xxx`` 都认）。

前端：``frontend_text(*parts)`` 按相对 ``tauri-app/src`` 的目录 / 文件取源码并拼起来。
"""
from __future__ import annotations

import ast
import pathlib
import re
from typing import Iterable, List, Optional, Tuple

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
APP = REPO_ROOT / "tauri-app" / "python-sidecar" / "app.py"
SIDECAR_DIR = REPO_ROOT / "src" / "sidecar"
FRONTEND_SRC = REPO_ROOT / "tauri-app" / "src"

HTTP_DECORATORS = ("route", "get", "post", "put", "delete", "patch")


def files() -> List[pathlib.Path]:
    return [APP] + sorted(SIDECAR_DIR.rglob("*.py"))


def text() -> str:
    """app.py 加上 src/sidecar 下全部模块的源码，用换行拼接。"""
    return "\n".join(path.read_text(encoding="utf-8") for path in files())


def trees() -> List[ast.Module]:
    """每个文件单独解析的 AST（不能把源码拼起来再 parse：模块里的 ``from __future__`` 不在文件开头会报错）。"""
    return [tree for _path, _source, tree in _parsed()]


def _parsed() -> List[Tuple[pathlib.Path, str, ast.Module]]:
    out = []
    for path in files():
        source = path.read_text(encoding="utf-8")
        out.append((path, source, ast.parse(source)))
    return out


def function_node(*names: str) -> Tuple[pathlib.Path, str, ast.AST]:
    """按函数名（可给多个候选名，取第一个找到的）在 sidecar 源码里找函数 / 方法，闭包里的也算。"""
    parsed = _parsed()
    for name in names:
        for path, source, tree in parsed:
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
                    return path, source, node
    raise LookupError("sidecar 源码里找不到函数: " + " / ".join(names))


def function_source(*names: str, include_decorators: bool = False) -> str:
    """函数（或方法）的完整源码，从 ``def`` 行到末尾；``include_decorators`` 时包含装饰器行。"""
    path, source, node = function_node(*names)
    lines = source.splitlines()
    start = node.lineno
    if include_decorators and node.decorator_list:
        start = min(start, min(d.lineno for d in node.decorator_list))
    return "\n".join(lines[start - 1:node.end_lineno])


def route_handler(route: str) -> Tuple[str, str, int, int, pathlib.Path]:
    """路由对应的 (函数名, 函数源码, 起始行, 结束行, 文件)；行号是文件内的 1 基行号。"""
    for found_route, _method, name, path in routes():
        if found_route == route:
            _path, source, node = function_node(name)
            body = "\n".join(source.splitlines()[node.lineno - 1:node.end_lineno])
            return name, body, node.lineno, node.end_lineno, path
    raise LookupError("找不到路由: " + route)


def routes(pattern: str = "") -> List[Tuple[str, str, str, pathlib.Path]]:
    """[(路径, 方法 / 装饰器名, 函数名, 文件)]；``pattern`` 是对路径的正则（缺省全部）。"""
    found = []
    regex = re.compile(pattern) if pattern else None
    for path, _source, tree in _parsed():
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                if (isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute)
                        and decorator.func.attr in HTTP_DECORATORS and decorator.args
                        and isinstance(decorator.args[0], ast.Constant) and isinstance(decorator.args[0].value, str)):
                    route = decorator.args[0].value
                    if regex is None or regex.search(route):
                        found.append((route, decorator.func.attr, node.name, path))
    return found


def route_paths(pattern: str = "") -> List[str]:
    return sorted({route for route, _method, _name, _path in routes(pattern)})


# ---------------------------------------------------------------------------------------------- 前端
def frontend_text(*parts: str, suffixes: Iterable[str] = (".vue", ".ts")) -> str:
    """相对 ``tauri-app/src`` 的文件或目录（目录递归，按文件名排序）；多个部分按给定顺序拼接。"""
    chunks = []
    for part in parts:
        target = FRONTEND_SRC / part
        if target.is_dir():
            paths = sorted(p for p in target.rglob("*") if p.is_file() and p.suffix in tuple(suffixes))
        else:
            paths = [target]
        for path in paths:
            chunks.append(path.read_text(encoding="utf-8"))
    return "\n".join(chunks)


def js_function_source(text: str, signature_prefix: str) -> str:
    """JS / TS 函数的源码：从 ``signature_prefix`` 起，到与函数体首个 ``{`` 配对的 ``}`` 止（含）。

    按花括号配对，跳过字符串、模板字符串和注释里的括号。比「到下一个顶格的 ``}`` 为止」可靠——
    函数被抽进 composable 之后是缩进的嵌套函数，收尾的 ``}`` 不在行首。
    """
    start = text.index(signature_prefix)
    brace = text.index("{", start + len(signature_prefix))
    depth, index, length = 0, brace, len(text)
    while index < length:
        char = text[index]
        if char in "'\"`":
            quote = char
            index += 1
            while index < length and text[index] != quote:
                index += 2 if text[index] == "\\" else 1
        elif text.startswith("//", index):
            index = text.find("\n", index)
            if index < 0:
                break
        elif text.startswith("/*", index):
            index = text.find("*/", index) + 1
            if index == 0:
                break
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start:index + 1]
        index += 1
    raise ValueError("花括号没有配对: " + signature_prefix)


def settings_panel_text() -> str:
    """设置页：外壳 + 各 Tab / 区块 + 表单状态（2026-10-19 起分散在三处）。"""
    return frontend_text("components/SettingsPanel.vue", "components/settings", "composables/settings")


def product_manager_text() -> str:
    """主页面：``ProductManager.vue`` + 它抽出去的流程 composable（2026-10-19 起）。"""
    return frontend_text("views/ProductManager.vue", "composables")

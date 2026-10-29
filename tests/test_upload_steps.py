# -*- coding: utf-8 -*-
"""``src/sidecar/upload_steps.py`` 的边界契约和几个能直接导入测的纯函数（2026-10-21 从 app.py 搬出）。

这个模块是「怎么在抖店发布页上点 / 填 / 等」的无状态页面操作：只靠入参里的标签页对象、标准库、``src.utils`` 里的
浏览器工具和本模块常量工作。搬出之前那 62 个函数 + 1 个异常类混在 ``app.py`` 里，和任务字典、账户锁、``gui`` 缠在一起；
搬出之后它们的优势是**能脱离服务状态单独测**——前提是这条边界不被悄悄打破。所以这里钉三件事：

1. 不导入 flask / app / 数据库模型 / 店铺会话 / 设置管理器（也不导入别的 ``src.sidecar`` 模块）；
2. 函数里不引用任务字典、锁、``gui``、账户别名、请求对象这类服务状态名（用 symtable 按编译器的作用域规则算，不是文本搜索）；
3. 顶层只有 import、函数、一个异常类和常量赋值——**导入本模块不产生副作用**
   （交互恢复钩子之类的注册由应用入口 app.py 做，``test_sidecar_app_smoke.py`` 的接线探针守着）。
"""
from __future__ import annotations

import ast
import symtable
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

MODULE_PATH = REPO / "src" / "sidecar" / "upload_steps.py"

#: 页面操作绝不该依赖的模块（前缀匹配）。``src.utils`` 是它的工作工具，允许。
FORBIDDEN_IMPORTS = (
    "flask", "flask_cors", "app", "sidecar_app_under_test",
    "src.orm", "src.shop_session", "src.config", "src.sidecar",
)

#: 这些全是服务 / 入口层的状态或能力：页面操作里出现任何一个，说明服务状态被带进了无状态层。
FORBIDDEN_NAMES = {
    "app", "gui", "request", "jsonify", "current_app", "Record",
    "_upload_tasks", "_upload_tasks_lock", "settings_manager", "shop_session", "repo_root",
    "_active_shop_profile", "_active_shop_account", "_require_publish_platform", "_with_shop_account_lock",
    "_get_current_browser_tab", "_record_browser_automation_error", "_latest_browser_debug_error_after",
}


@pytest.fixture(scope="module")
def tree():
    return ast.parse(MODULE_PATH.read_text(encoding="utf-8"))


def test_module_imports_nothing_from_the_service_layer(tree):
    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.append(("." * node.level) + (node.module or ""))
    bad = sorted(name for name in imported
                 if name.startswith(".") or any(name == bad or name.startswith(bad + ".") for bad in FORBIDDEN_IMPORTS))
    assert bad == [], "页面操作不应依赖服务 / 入口层: %s" % bad


def test_no_function_touches_service_state():
    top = symtable.symtable(MODULE_PATH.read_text(encoding="utf-8"), str(MODULE_PATH), "exec")
    touched = {}

    def walk(table, owner):
        for child in table.get_children():
            for sym in child.get_symbols():
                if sym.is_referenced() and sym.is_global() and sym.get_name() in FORBIDDEN_NAMES:
                    touched.setdefault(sym.get_name(), set()).add(owner + "." + child.get_name() if owner else child.get_name())
            walk(child, child.get_name())

    walk(top, "")
    assert touched == {}, "页面操作里不能出现服务状态名: %s" % {k: sorted(v) for k, v in touched.items()}


def test_importing_the_module_has_no_side_effects(tree):
    """顶层只有 import / 函数 / 类 / 常量赋值（外加开头的文档字符串）；没有函数调用之类的语句。"""
    allowed = (ast.Import, ast.ImportFrom, ast.FunctionDef, ast.ClassDef, ast.Assign)
    offenders = []
    for index, node in enumerate(tree.body):
        if isinstance(node, allowed):
            continue
        is_docstring = (index == 0 and isinstance(node, ast.Expr)
                        and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str))
        if not is_docstring:
            offenders.append("L%d %s" % (node.lineno, type(node).__name__))
    assert offenders == [], offenders
    # 常量赋值只能是 NAME = <字面量 / 简单表达式>，不能是调用（调用可能带副作用，比如读文件 / 注册钩子）
    calls = [node.lineno for node in tree.body
             if isinstance(node, ast.Assign) and any(isinstance(sub, ast.Call) for sub in ast.walk(node.value))]
    assert calls == [], "模块级常量的右值里不应有函数调用: L%s" % calls


# ----------------------------------------------------------------------------------------- 能直接导入测的纯函数
@pytest.fixture(scope="module")
def steps():
    from src.sidecar import upload_steps
    return upload_steps


@pytest.mark.parametrize("raw, expected", [
    (None, ""),
    ("", ""),
    ("   ", ""),
    ("8", "8"),
    ("8.00", "8"),
    ("0.0", "0"),
    ("￥1,299.50", "1299.5"),
    (12.5, "12.5"),
    ("abc", "abc"),                  # 不是数字就原样（去掉千分位 / 货币符号后）返回，不吞
])
def test_normalize_upload_numeric_text(steps, raw, expected):
    assert steps._normalize_upload_numeric_text(raw) == expected


class _Named(Exception):
    pass


@pytest.mark.parametrize("class_name, message, expected", [
    ("ElementLostError", "", True),
    ("NoRectError", "", True),
    ("ContextLostError", "", True),
    ("RuntimeError", "Could not find node with given id", True),
    ("RuntimeError", "元素对象已失效", True),
    ("RuntimeError", "别的错误", False),
])
def test_element_lost_error_is_decided_by_class_name_and_message(steps, class_name, message, expected):
    exc = type(class_name, (Exception,), {})(message)
    assert steps._is_element_lost_error(exc) is expected


def test_overlay_button_selector_covers_every_overlay_text(steps):
    selector = steps._build_overlay_button_selector()
    assert selector.startswith("xpath:")
    for text in steps._INTERFERING_OVERLAY_TEXTS:
        assert 'normalize-space(.)="%s"' % text in selector
    scoped = steps._build_overlay_button_selector("@id='x'")
    assert "//*[@id='x']//*[self::button" in scoped and scoped != selector


def test_current_tab_url_never_raises(steps):
    class Broken:
        @property
        def url(self):
            raise RuntimeError("tab closed")

    class Fine:
        url = "https://fxg.jinritemai.com/ffa/g/create"

    assert steps._get_current_tab_url(Broken()) == ""
    assert steps._get_current_tab_url(Fine()) == Fine.url


def test_press_enter_sends_key_down_then_key_up(steps):
    calls = []

    class Tab:
        def run_cdp(self, method, **params):
            calls.append((method, params["type"], params["key"]))

    steps._press_enter(Tab())
    assert calls == [("Input.dispatchKeyEvent", "keyDown", "Enter"), ("Input.dispatchKeyEvent", "keyUp", "Enter")]


def test_publish_unconfirmed_error_is_an_exception_with_the_expensive_warning(steps):
    """已点「发布商品」但没读到结果——绝不能当成「没发布」处理（判成失败就会被重跑，重跑即重复铺货）。"""
    assert issubclass(steps.PublishUnconfirmedError, Exception)
    assert "重复铺货" in (steps.PublishUnconfirmedError.__doc__ or "")

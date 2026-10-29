# -*- coding: utf-8 -*-
"""按函数名从 Sidecar 源码（``app.py`` + ``src/sidecar/**``）里取函数源码，给「读源码断言不变量」类的测试用。

Sidecar 按业务域拆成了 Blueprint 工厂（路由是工厂里的闭包函数）和服务类（方法），搬家以后不能再靠
「``app.py`` 里从 ``def xxx():`` 切到下一个 ``@app.`` 为止」的文本切片：用 AST 按名字定位，不依赖装饰器写法 / 缩进 / 所在文件。
找不到会直接报错（``LookupError``），不会返回空串让断言空转。
"""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / 'tauri-app' / 'python-sidecar' / 'app.py'
SIDECAR_DIR = ROOT / 'src' / 'sidecar'
UPLOAD_STEPS = SIDECAR_DIR / 'upload_steps.py'


def source_files():
    return [APP] + sorted(SIDECAR_DIR.rglob('*.py'))


def upload_text():
    """抖店上传域的全部源码：``app.py`` 加上 ``src/sidecar/upload_*.py``（用文件名通配，之后上传域再拆出新模块也不用改这里）。

    给「整个发布流程里某字符串出现几次 / 不应出现」这类文本断言用：流程分散在几个文件里，只读其中一个会让「不应出现」空转。
    ``upload_steps.py`` 必须存在，缺了直接报错，不会悄悄少读。
    """
    assert UPLOAD_STEPS.is_file(), UPLOAD_STEPS
    paths = [APP] + sorted(SIDECAR_DIR.glob('upload_*.py'))
    return '\n'.join(path.read_text(encoding='utf-8') for path in paths)


def module_text(name):
    """``src/sidecar/<name>`` 的全文，``name`` 形如 ``'taobao_service.py'``。"""
    return (SIDECAR_DIR / name).read_text(encoding='utf-8')


def function_source(*names, within=None):
    """第一个找到的函数 / 方法的源码（从 ``def`` 行到结尾，不含装饰器）；给多个名字时按顺序找。

    ``within`` 是 ``src/sidecar`` 下的文件名（如 ``'taobao_routes.py'``），给了就只在那一个文件里找。
    """
    paths = [SIDECAR_DIR / within] if within else source_files()
    for name in names:
        for path in paths:
            text = path.read_text(encoding='utf-8')
            for node in ast.walk(ast.parse(text)):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
                    return '\n'.join(text.splitlines()[node.lineno - 1:node.end_lineno])
    raise LookupError('Sidecar 源码里找不到函数: ' + ' / '.join(names))

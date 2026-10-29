# -*- coding: utf-8 -*-
"""给新旧对打用的行覆盖记录器：看场景有没有真的跑到被搬函数的每一条语句。

用 sys.settrace 记录执行过的行，不依赖 coverage 库。slice_diff.py 在环境变量 SLICE_COVER 非空时启用：
  old 模式：SLICE_COVER=<app.py 顶层函数名，逗号分隔>（取自搬迁前的 app.py）
  new 模式：SLICE_COVER=<src/sidecar 下的模块文件名，逗号分隔>（报告其中所有函数 / 方法）
报告列出每个函数里**从未执行过**的语句，场景脚本据此补请求，直到剩下的都是有理由跑不到的（例如 ``pass`` 兜底）。
"""
import ast
import sys
import threading


class Recorder:
    def __init__(self, wanted_files):
        self.wanted = {f for f in wanted_files}
        self.hits = set()

    def _local(self, frame, event, arg):
        if event == 'line':
            self.hits.add((frame.f_code.co_filename, frame.f_lineno))
        return self._local

    def _tracer(self, frame, event, arg):
        if event == 'call' and frame.f_code.co_filename in self.wanted:
            self.hits.add((frame.f_code.co_filename, frame.f_lineno))
            return self._local
        return None

    def start(self):
        sys.settrace(self._tracer)
        threading.settrace(self._tracer)

    def stop(self):
        sys.settrace(None)
        threading.settrace(None)


def _statements(func):
    """函数体里的语句（不含函数自己的 def 行与文档字符串；嵌套函数的语句也算在内）。"""
    out = []
    for node in ast.walk(func):
        if not isinstance(node, ast.stmt) or node is func:
            continue
        if (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)):
            continue
        out.append(node)
    return out


def report(filename, text, hits, only_names=None, show_source=True):
    """打印 filename 里每个函数从未执行过的语句；返回 {函数名: 未执行行号列表}。"""
    tree = ast.parse(text)
    lines = text.split('\n')
    executed = {ln for fn, ln in hits if fn == filename}
    result = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if only_names is not None and node.name not in only_names:
            continue
        missing = [s for s in _statements(node)
                   if s.lineno not in executed and not isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef))]
        total = [s for s in _statements(node) if not isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef))]
        key = '%s (L%d)' % (node.name, node.lineno)
        result[key] = (len(total), [s.lineno for s in missing])
    print('---- 行覆盖：%s' % filename)
    for key, (total, missing) in sorted(result.items(), key=lambda kv: int(kv[0].rsplit('L', 1)[1].rstrip(')'))):
        if not total:
            continue
        print('  %-52s %3d/%3d 条语句已执行' % (key, total - len(missing), total))
        if show_source:
            for ln in missing:
                print('        未执行 L%-5d %s' % (ln, lines[ln - 1].strip()[:110]))
    return result

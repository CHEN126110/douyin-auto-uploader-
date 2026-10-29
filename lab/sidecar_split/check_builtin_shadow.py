# -*- coding: utf-8 -*-
"""新模块里按「内置名」解析的全局名，在搬迁前的 app.py 里是不是被模块级重新绑定过（比如 app.py 自己定义的 print）。

用法: python check_builtin_shadow.py <before_app.py> <new_module.py>
有重名就列出来（不一定是问题——要看两者行为是否等价，由人判断），没有则输出“无”。
"""
import ast
import builtins
import symtable
import sys

before_path, module_path = sys.argv[1:3]
before = ast.parse(open(before_path, encoding='utf-8').read())
text = open(module_path, encoding='utf-8').read()

# app.py 模块级（含 try / if 里）定义或赋值的名字
bound = {}


def walk(body):
    for node in body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef)):
            bound.setdefault(node.name, 'def/class line %d' % node.lineno)
        elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in targets:
                for x in ast.walk(t):
                    if isinstance(x, ast.Name) and isinstance(x.ctx, ast.Store):
                        bound.setdefault(x.id, 'assign line %d' % node.lineno)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for a in node.names:
                bound.setdefault((a.asname or a.name).split('.')[0], 'import line %d' % node.lineno)
        elif isinstance(node, (ast.Try, ast.If, ast.For, ast.While, ast.With)):
            walk(node.body)
            for h in getattr(node, 'handlers', []):
                walk(h.body)
            walk(getattr(node, 'orelse', []))
            walk(getattr(node, 'finalbody', []))


walk(before.body)

top = symtable.symtable(text, '<module>', 'exec')
defined_here = {s.get_name() for s in top.get_symbols() if s.is_assigned() or s.is_imported() or s.is_namespace()}
found = set()


def scan(tab):
    for child in tab.get_children():
        for sym in child.get_symbols():
            if sym.is_referenced() and sym.is_global():
                found.add(sym.get_name())
        scan(child)


scan(top)
rows = []
for name in sorted(found):
    if name in defined_here:
        continue
    if hasattr(builtins, name) and name in bound:
        rows.append((name, bound[name]))
if not rows:
    print('无：新模块里没有任何内置名在 app.py 模块级被重新绑定')
else:
    for name, where in rows:
        print('内置名 %s 在 app.py 里被重新绑定（%s）' % (name, where))

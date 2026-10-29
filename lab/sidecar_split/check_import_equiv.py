# -*- coding: utf-8 -*-
"""新模块里每个导入的名字，必须和 app.py（搬迁前）模块级对该名字的绑定一致。

用法: python check_import_equiv.py <before_app.py> <new_module.py>
只看「名字 -> 来源」：app.py 的模块级（含 try / if 里的）导入与赋值；新模块的模块级导入。
任何一个名字来源不同，或者新模块里有 app.py 里根本没有绑定的名字，都报错退出。
"""
import ast
import sys

before_path, module_path = sys.argv[1:3]
before = ast.parse(open(before_path, encoding='utf-8').read())
module = ast.parse(open(module_path, encoding='utf-8').read())


def module_level_bindings(tree):
    """名字 -> 来源描述；同一名字多次绑定时保留全部（列表），便于发现冲突。"""
    out = {}

    def add(name, src):
        out.setdefault(name, []).append(src)

    def walk(body):
        for node in body:
            if isinstance(node, ast.Import):
                for a in node.names:
                    add((a.asname or a.name).split('.')[0], 'import %s' % (a.name if not a.asname else '%s as %s' % (a.name, a.asname)))
            elif isinstance(node, ast.ImportFrom):
                for a in node.names:
                    add(a.asname or a.name, 'from %s%s import %s' % ('.' * node.level, node.module or '', a.name))
            elif isinstance(node, (ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef)):
                add(node.name, 'def/class line %d' % node.lineno)
            elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for t in targets:
                    for x in ast.walk(t):
                        # 只有 Store 才是绑定；``os.environ[k] = v`` 里的 ``os`` 是 Load
                        if isinstance(x, ast.Name) and isinstance(x.ctx, ast.Store):
                            add(x.id, 'assign line %d' % node.lineno)
            elif isinstance(node, (ast.Try, ast.If)):
                walk(node.body)
                for h in getattr(node, 'handlers', []):
                    walk(h.body)
                walk(node.orelse)
                if isinstance(node, ast.Try):
                    walk(node.finalbody)
    walk(tree.body)
    return out


old = module_level_bindings(before)
new = module_level_bindings(module)
problems = []
rows = []
for name, srcs in sorted(new.items()):
    for s in srcs:
        if not s.startswith(('import ', 'from ')):
            continue
        # 相对导入还原成绝对形式再比
        s_norm = s.replace('from .', 'from src.sidecar.')
        olds = old.get(name)
        if not olds:
            problems.append('%s: 新模块里 %r，但 app.py 模块级没有这个名字的绑定' % (name, s))
            continue
        olds_norm = [o.replace('from .', 'from src.sidecar.') for o in olds]
        if s_norm not in olds_norm:
            problems.append('%s: 新模块 %r 不在 app.py 的绑定 %r 里' % (name, s, olds))
        elif len(set(o for o in olds_norm if o.startswith(('import ', 'from ')))) > 1 or any(not o.startswith(('import ', 'from ')) for o in olds_norm):
            problems.append('%s: app.py 里这个名字有多个不同的绑定 %r（可能被覆盖），新模块取了 %r' % (name, olds, s))
        rows.append((name, s))
print('新模块共 %d 个导入名字' % len(rows))
for p in problems:
    print('!!', p)
print('问题 %d 个' % len(problems))
sys.exit(1 if problems else 0)

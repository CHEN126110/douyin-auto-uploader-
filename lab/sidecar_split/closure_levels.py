# -*- coding: utf-8 -*-
"""只读：一个业务域的函数闭包，按「是否碰服务状态」分成纯的一侧和服务侧（2026-10-21，上传域侦察用）。

用法:
  python closure_levels.py <app.py> --routes /api/upload,/api/protocol,/start --state gui,_upload_tasks,... [--json out.json]

做法：
  1. 从匹配 --routes 前缀的路由函数出发，求 app.py 顶层函数 / 类的调用闭包；
  2. 直接引用 --state 里任一名字（任务字典 / 锁 / ``gui`` / 账户别名 / ``__file__`` / ``Record`` / ``request`` …）的函数 = 「直接依赖状态」；
  3. 调用了它们的函数也算（传递闭包）= 服务侧；剩下的 = 纯的一侧；
  4. 打印两侧的函数表，以及纯的一侧引用的 app.py 顶层变量（要一起搬走的常量）和服务侧被「纯的一侧」调用的函数。
纯的一侧不会调用服务侧（按定义），所以可以先搬纯的，服务侧留在原地调用它们。

注意 ``--state`` 要自己列全：漏列一个状态名，依赖它的函数会被误判成纯的。
列法：``python recon.py`` 的「引用的顶层状态」里除了常量以外的都是；``__file__`` / ``sys`` 这类“路径依赖入口文件位置”的也要列。
"""
import argparse
import ast
import builtins
import collections
import json
import sys

parser = argparse.ArgumentParser()
parser.add_argument('app_path')
parser.add_argument('--routes', required=True, help='逗号分隔的路由前缀（精确路由也行，如 /start）')
parser.add_argument('--state', required=True, help='逗号分隔的“服务状态名”')
parser.add_argument('--json', help='把结果写成 json（pure / service / routes / const_pure / const_service）')
args = parser.parse_args()

src = open(args.app_path, encoding='utf-8').read()
tree = ast.parse(src)
funcs, assigns = {}, {}
for node in tree.body:
    if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
        funcs[node.name] = node
    elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for t in targets:
            for x in ast.walk(t):
                if isinstance(x, ast.Name) and isinstance(x.ctx, ast.Store):
                    assigns.setdefault(x.id, node)


def route_of(fn):
    for d in getattr(fn, 'decorator_list', []):
        if isinstance(d, ast.Call) and d.args and isinstance(d.args[0], ast.Constant):
            return d.args[0].value
    return None


def local_names(fn):
    names = {a.arg for a in ast.walk(fn) if isinstance(a, ast.arg)}
    for x in ast.walk(fn):
        if isinstance(x, ast.Name) and isinstance(x.ctx, (ast.Store, ast.Del)):
            names.add(x.id)
        elif isinstance(x, (ast.Import, ast.ImportFrom)):
            for a in x.names:
                names.add((a.asname or a.name).split('.')[0])
        elif isinstance(x, ast.ExceptHandler) and x.name:
            names.add(x.name)
        elif isinstance(x, (ast.FunctionDef, ast.ClassDef)) and x is not fn:
            names.add(x.name)
    return names


def refs(fn):
    local = local_names(fn)
    out = set()
    for x in ast.walk(fn):
        if isinstance(x, ast.Name) and isinstance(x.ctx, ast.Load) and x.id not in local and not hasattr(builtins, x.id):
            out.add(x.id)
        elif isinstance(x, ast.Global):
            out.update(x.names)
    return out


call_graph = {name: {r for r in refs(fn) if r in funcs and r != name} for name, fn in funcs.items()}
prefixes = [p.strip() for p in args.routes.split(',') if p.strip()]
state = {s.strip() for s in args.state.split(',') if s.strip()}

seeds = [n for n, fn in funcs.items() if route_of(fn) and any(route_of(fn).startswith(p) for p in prefixes)]
closure, stack = set(), list(seeds)
while stack:
    n = stack.pop()
    if n in closure:
        continue
    closure.add(n)
    stack.extend(call_graph[n] - closure)

direct = {n for n in closure if state & refs(funcs[n])}
dep = set(direct)
changed = True
while changed:
    changed = False
    for n in closure:
        if n not in dep and call_graph[n] & dep:
            dep.add(n)
            changed = True
pure = closure - dep


def size(names):
    return sum(funcs[n].end_lineno - funcs[n].lineno + 1 for n in names)


def line(n):
    return funcs[n].lineno


print('闭包 %d 个定义 / %d 行；直接依赖状态 %d；服务侧（含传递）%d / %d 行；纯的一侧 %d / %d 行' % (
    len(closure), size(closure), len(direct), len(dep), size(dep), len(pure), size(pure)))
print()
print('--- 服务侧（* = 直接引用状态名）---')
for n in sorted(dep, key=line):
    print('%5d %4d %s %-45s state=%s%s' % (line(n), size([n]), '*' if n in direct else ' ', n, sorted(state & refs(funcs[n])),
                                           '  [route %s]' % route_of(funcs[n]) if route_of(funcs[n]) else ''))
print()
print('--- 纯的一侧（可原样搬）---')
for n in sorted(pure, key=line):
    print('%5d %4d   %s' % (line(n), size([n]), n))
called = collections.Counter(c for n in dep for c in call_graph[n] & pure)
print()
print('--- 服务侧直接调用的纯函数（搬走后要从新模块导入 / 经端口注入）---')
print(', '.join(sorted(called, key=line)))
const_pure = sorted({r for n in pure for r in refs(funcs[n]) if r in assigns and r not in funcs}, key=lambda r: assigns[r].lineno)
print()
print('--- 纯的一侧引用的 app.py 顶层变量（要一起搬走的常量）---')
print(', '.join(const_pure))
if args.json:
    json.dump({'pure': sorted(pure, key=line), 'service': sorted(dep, key=line),
               'routes': [n for n in sorted(dep, key=line) if route_of(funcs[n])],
               'const_pure': const_pure}, open(args.json, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)

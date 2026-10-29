# -*- coding: utf-8 -*-
"""只读侦察：app.py 里各业务域的函数闭包、共享状态、被谁引用、哪些测试在读它们。

用法: python recon.py <app.py 路径> <tests 目录>
不写仓库任何文件。
"""
import ast
import builtins
import collections
import os
import re
import sys

app_path, tests_dir = sys.argv[1], sys.argv[2]
src = open(app_path, encoding='utf-8').read()
tree = ast.parse(src)

funcs, assigns, imports = {}, {}, set()
for node in tree.body:
    if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
        funcs[node.name] = node
    elif isinstance(node, (ast.Assign, ast.AnnAssign)):
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for t in targets:
            for x in ast.walk(t):
                if isinstance(x, ast.Name):
                    assigns.setdefault(x.id, node)
    elif isinstance(node, (ast.Import, ast.ImportFrom)):
        for a in node.names:
            imports.add((a.asname or a.name).split('.')[0])


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
    return out


call_graph = {name: {r for r in refs(fn) if r in funcs and r != name} for name, fn in funcs.items()}
state_refs = {name: {r for r in refs(fn) if r in assigns and r not in funcs} for name, fn in funcs.items()}

DOMAINS = collections.OrderedDict([
    ('shop', lambda r: r.startswith('/api/shop')),
    ('debug', lambda r: r.startswith('/api/debug')),
    ('taobao', lambda r: r.startswith('/api/taobao')),
    ('upload+protocol', lambda r: r.startswith('/api/upload') or r.startswith('/api/protocol')),
    ('capture', lambda r: r.startswith('/api/capture')),
    ('xhs-batch', lambda r: r.startswith('/api/xhs')),
    ('import', lambda r: r.startswith('/api/import')),
])
seeds = collections.defaultdict(list)
other_routes = []
for name, fn in funcs.items():
    r = route_of(fn)
    if not r:
        continue
    for dname, pred in DOMAINS.items():
        if pred(r):
            seeds[dname].append(name)
            break
    else:
        other_routes.append((r, name))


def closure(roots):
    seen, stack = set(), list(roots)
    while stack:
        n = stack.pop()
        if n in seen:
            continue
        seen.add(n)
        stack.extend(call_graph.get(n, ()))
    return seen


reach = {d: closure(s) for d, s in seeds.items()}
other_roots = [n for _, n in other_routes]
reach['(其余路由/启动/产品CRUD)'] = closure(other_roots)

size = {n: f.end_lineno - f.lineno + 1 for n, f in funcs.items()}
owners = collections.defaultdict(set)
for d, names in reach.items():
    for n in names:
        owners[n].add(d)

# 被「非路由代码里的别处」引用的函数（例如被 Blueprint 注册处引用）
module_level_users = collections.defaultdict(set)
for node in tree.body:
    if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
        continue
    for x in ast.walk(node):
        if isinstance(x, ast.Name) and x.id in funcs:
            module_level_users[x.id].add('<模块级代码 L%d>' % node.lineno)

# 测试里谁在读 app.py 文本 / 抽函数
test_texts = {}
for fn in sorted(os.listdir(tests_dir)):
    if fn.endswith('.py'):
        t = open(os.path.join(tests_dir, fn), encoding='utf-8', errors='replace').read()
        if re.search(r'app\.py|APP_PATH|APP_PY|python-sidecar', t):
            test_texts[fn] = t

print('app.py: %d 行, 顶层函数 %d, 顶层状态/常量 %d' % (len(src.splitlines()), len(funcs), len(assigns)))
print()
for d in list(DOMAINS) + ['(其余路由/启动/产品CRUD)']:
    names = reach.get(d, set())
    if not names:
        continue
    exclusive = sorted(n for n in names if owners[n] == {d})
    shared = sorted(n for n in names if len(owners[n]) > 1)
    states = collections.Counter()
    for n in names:
        for s in state_refs.get(n, ()):
            states[s] += 1
    print('=' * 100)
    print('域 %-22s 路由 %2d | 闭包函数 %3d (%5d 行) | 独占 %3d (%5d 行) | 与其它域共享 %3d (%5d 行)' % (
        d, len(seeds.get(d, other_routes if d.startswith('(') else [])), len(names), sum(size[n] for n in names),
        len(exclusive), sum(size[n] for n in exclusive), len(shared), sum(size[n] for n in shared)))
    big = sorted(exclusive, key=lambda n: -size[n])[:6]
    print('   最大的独占函数:', ', '.join('%s(%d)' % (n, size[n]) for n in big))
    if shared:
        print('   共享函数(被多个域用，搬走要注入/放共享模块):')
        for n in sorted(shared, key=lambda n: -size[n])[:14]:
            print('      %-40s %4d 行  被: %s' % (n, size[n], ', '.join(sorted(owners[n]))))
    if states:
        print('   引用的顶层状态/常量:', ', '.join('%s×%d' % kv for kv in states.most_common(12)))
    pinned = [n for n in exclusive if module_level_users.get(n)]
    if pinned:
        print('   被模块级代码(如 Blueprint 注册)直接引用:', ', '.join(sorted(pinned)))
    # 测试耦合
    hits = collections.Counter()
    for tfile, text in test_texts.items():
        found = [n for n in names if re.search(r'(?<![A-Za-z0-9_])%s(?![A-Za-z0-9_])' % re.escape(n), text)]
        if found:
            hits[tfile] = len(found)
    if hits:
        print('   读取/引用这些函数名的测试文件:', ', '.join('%s(%d个名字)' % kv for kv in hits.most_common()))
print()
print('其余路由（不属于上面任何域）:')
for r, n in sorted(other_routes):
    print('   %-45s %s (%d 行)' % (r, n, size[n]))

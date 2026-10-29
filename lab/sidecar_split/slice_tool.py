# -*- coding: utf-8 -*-
"""通用「从 app.py 抽一个业务域成 Blueprint 模块 / 服务类」工具。

流程：
  1. gen(slice, src)          -> 生成 src/sidecar/<module>.py 的文本（函数体逐字搬迁，只做声明过的改写；
                                 Slice.class_name 非空时 funcs 搬成服务类的方法，否则搬进 Blueprint 工厂的闭包）
  2. patch_app(slice, before) -> 生成搬迁后的 app.py（删函数 / 常量 / 状态变量、清理变得无用的导入、
                                 插入装配代码、别名和 Blueprint 注册）
  3. verify(slice, ...)       -> 独立 AST 校验：新函数 == 原函数 + 声明的改写
全部基于 AST，函数体里的字符串 / 注释 / 空行原样保留（函数自己的文档字符串随缩进，verify 按 inspect.cleandoc 归一后比较）。
手写部分（prelude / init_lines / class_extra / manual_methods / app_replacements）不参与 AST 重放，
要靠测试和新旧对打守住——越少越好。
"""
import ast
import builtins
import copy
import inspect
import os
import symtable
import sys
import types
from dataclasses import dataclass, field

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mover import Rules, Source, extract  # noqa: E402

STDLIB = set(sys.stdlib_module_names)
NL = '\n'


@dataclass
class Slice:
    key: str
    module_file: str                      # 相对 src/sidecar/，如 'ai_routes.py'
    doc: str                              # 模块 docstring（不含引号）
    factory: str = ''                     # 工厂函数名；为空表示这个模块只有服务类，没有 Blueprint
    blueprint_name: str = ''
    funcs: list = field(default_factory=list)          # 搬进工厂闭包（或服务类）的 app.py 顶层函数名
    module_funcs: list = field(default_factory=list)   # 搬成模块级纯函数的 app.py 顶层函数名
    consts: list = field(default_factory=list)         # 一起搬走的模块级常量名（单目标赋值）
    params: list = field(default_factory=list)         # 工厂的关键字参数名
    factory_doc: str = ''
    aliases: list = field(default_factory=list)        # 工厂体内开头的赋值行，如 "Record = record_model"
    name_map: dict = field(default_factory=dict)
    decorator_name_map: dict = field(default_factory=lambda: {'app': 'routes'})
    insert_first: dict = field(default_factory=dict)
    per_func: dict = field(default_factory=dict)       # name -> dict(name_map=, insert_first=, new_name=)
    import_overrides: dict = field(default_factory=dict)  # 名字 -> 完整 import 语句（覆盖默认推断）
    registration: str = ''                # 插入 app.py 的注册代码
    app_import: str = ''                  # 插入 app.py 的 import 行
    drop_extra_imports: list = field(default_factory=list)  # 搬迁后 app.py 里额外要清掉的导入名
    allow_src_utils: bool = False         # True：允许模块直接导入 src.utils 的名字（浏览器自动化步骤本来就依赖它；其余模块仍应注入）
    interleave: bool = False              # True：consts 按 app.py 里的原位置夹在 module_funcs 之间，而不是全部放在模块开头

    # ---- 服务类形态：class_name 非空时，funcs 搬成该类的方法（def 行自动补 self） ----
    class_name: str = ''
    class_doc: str = ''
    class_params: list = field(default_factory=list)   # __init__ 的关键字形参文本，如 'lock=None'
    wrap_init: bool = False                            # True：__init__ 签名一行一个形参（形参多的类用，默认保持单行）
    init_lines: list = field(default_factory=list)     # __init__ 体里手写的行（不含缩进）
    state_assigns: list = field(default_factory=list)  # [(app.py 里的变量名, 'self._lock')]：右值逐字取自 app.py
    class_extra: str = ''                              # __init__ 之后、方法之前的手写成员（含缩进）
    manual_methods: str = ''                           # 类体末尾的手写方法（含缩进，不参与 AST 校验）
    prelude: str = ''                                  # 模块级手写文本（端口 dataclass 等），放在函数 / 类之前

    # ---- app.py 的额外改写 ----
    app_replacements: dict = field(default_factory=dict)  # 函数名 -> 替换文本：原函数删除，文本落在同一位置
    insert_after: list = field(default_factory=list)      # [(锚点顶层名, 文本)]：在 app.py 该语句之后插入

    # ---- 搬迁后必须修正的说明文字（原文已经失真，例如提到「被某某测试抽取」）----
    doc_edits: dict = field(default_factory=dict)         # 函数名 -> [(旧子串, 新子串)]：改文档字符串，verify 会按同样规则重放
    comment_edits: list = field(default_factory=list)     # [(旧文本, 新文本)]：改模块里的注释（AST 看不见，只做精确替换并断言唯一）
    app_edits: list = field(default_factory=list)         # [(旧文本, 新文本)]：搬迁后对 app.py 做的文本级收尾（如删掉变成孤立的区块注释）


def rules_for(sl: Slice, fname: str) -> Rules:
    extra = sl.per_func.get(fname, {})
    name_map = dict(sl.name_map)
    name_map.update(extra.get('name_map', {}))
    for key in extra.get('name_map_exclude', ()):   # 这个函数里该名字是局部名（比如函数内自己 ``from x import y``），不能被改写
        name_map.pop(key, None)
    insert_first = dict(sl.insert_first)
    insert_first.update(extra.get('insert_first', {}))
    first = 'self' if (sl.class_name and fname in sl.funcs) else None
    return Rules(name_map=name_map, insert_first=insert_first, new_name=extra.get('new_name'),
                 def_first_param=first, decorator_name_map=dict(sl.decorator_name_map))


def _import_table(src: Source):
    """app.py 里（含 if / try 里）的 import：名字 -> ('import'|'from', module, original_or_asname)。"""
    table = {}
    for node in ast.walk(src.tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                table.setdefault((a.asname or a.name).split('.')[0], ('import', a.name, a.asname))
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            for a in node.names:
                table.setdefault(a.asname or a.name, ('from', node.module, a.name))
    return table


def _toplevel_defs(src: Source):
    defs = set()
    for node in src.tree.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef)):
            defs.add(node.name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in targets:
                for x in ast.walk(t):
                    if isinstance(x, ast.Name):
                        defs.add(x.id)
    return defs


def _global_refs(text: str):
    """函数作用域里按编译器规则被解析为「全局」的名字；再加上模块级代码直接引用的名字。"""
    top = symtable.symtable(text, '<gen>', 'exec')
    found = set()

    def walk(tab):
        for child in tab.get_children():
            for sym in child.get_symbols():
                if sym.is_referenced() and sym.is_global():
                    found.add(sym.get_name())
            walk(child)

    walk(top)
    for sym in top.get_symbols():
        if sym.is_referenced() and not (sym.is_assigned() or sym.is_imported() or sym.is_namespace()):
            found.add(sym.get_name())
    defined_here = {s.get_name() for s in top.get_symbols()
                    if s.is_assigned() or s.is_imported() or s.is_namespace()}
    return found, defined_here


def _render_import(name, entry):
    kind = entry[0]
    if kind == 'import':
        _, mod, asname = entry
        return f'import {mod} as {asname}' if asname else f'import {mod}'
    _, mod, orig = entry
    if mod.startswith('src.sidecar.'):
        mod = '.' + mod[len('src.sidecar.'):]
    return f'from {mod} import {orig}' if name == orig else f'from {mod} import {orig} as {name}'


def _group_imports(lines):
    """合并同一模块的 from-import，再按 stdlib / 第三方 / 本项目分组、组内排序。"""
    plain, merged = [], {}
    for line in lines:
        parts = line.split()
        if parts[0] == 'from' and parts[2] == 'import':
            merged.setdefault(parts[1], []).append(line.split(' import ', 1)[1])
        else:
            plain.append(line)
    rendered = list(plain)
    for mod, names in merged.items():
        uniq = sorted(set(names))
        one = f"from {mod} import {', '.join(uniq)}"
        if len(one) <= 100:
            rendered.append(one)
        else:
            body = ''.join(f'    {n},{NL}' for n in uniq)
            rendered.append(f'from {mod} import ({NL}{body})')
    std, third, local = [], [], []
    for line in rendered:
        mod = line.split()[1].lstrip('.')
        root = mod.split('.')[0]
        if line.startswith('from .') or root == 'src':
            local.append(line)
        elif root in STDLIB:
            std.append(line)
        else:
            third.append(line)

    def key(l):
        return (0 if l.startswith('import ') else 1, l.replace('from .', 'from zz.'))
    groups = [sorted(set(g), key=key) for g in (std, third, local) if g]
    return (NL + NL).join(NL.join(g) for g in groups)


def _single_assign(tree, name):
    """app.py 顶层 ``name = ...`` 或 ``name: 类型 = ...`` 单目标赋值语句；找不到返回 None。"""
    for node in tree.body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name) and node.targets[0].id == name):
            return node
        if (isinstance(node, ast.AnnAssign) and node.value is not None
                and isinstance(node.target, ast.Name) and node.target.id == name):
            return node
    return None


def _assign_target_name(node):
    """赋值语句（Assign / AnnAssign）的目标变量名。"""
    return node.target.id if isinstance(node, ast.AnnAssign) else node.targets[0].id


def _leading_comment_start(lines, lineno):
    """语句（1-based 行号 lineno）正上方紧挨着的连续注释行的起始行号（没有则返回 lineno）。"""
    start = lineno
    while start >= 2 and lines[start - 2].lstrip().startswith('#'):
        start -= 1
    return start


def _const_text(src: Source, name: str) -> str:
    node = _single_assign(src.tree, name)
    if node is None:
        raise KeyError(name)
    # 紧挨着赋值语句上方的注释说明的就是这个常量，跟着一起走，不然会在 app.py 里变成孤立注释。
    start = _leading_comment_start(src.lines, node.lineno)
    return NL.join(src.lines[start - 1:node.end_lineno])


def _join_consts(blocks):
    """相邻的常量块拼在一起：单行的紧挨着，只要有一块是多行（含带注释的）就空一行隔开。"""
    out = blocks[0]
    for prev, cur in zip(blocks, blocks[1:]):
        out += (NL + NL if (NL in prev or NL in cur) else NL) + cur
    return out


def _rhs_text(src: Source, node: ast.Assign, indent: int) -> str:
    """赋值语句右值的源码，续行整体右移 indent 列（多行字符串不支持，会直接报错）。"""
    for sub in ast.walk(node.value):
        if isinstance(sub, ast.Constant) and isinstance(sub.value, str) and sub.end_lineno > sub.lineno:
            raise AssertionError(f'{_assign_target_name(node)}: 右值含多行字符串，不能自动缩进')
    seg = ast.get_source_segment(src.text, node.value)
    first, *rest = seg.split(NL)
    pad = ' ' * indent
    return first + ''.join(NL + (pad + ln if ln.strip() else ln) for ln in rest)


def _local_names(fn):
    """函数里被赋值 / 导入 / 作为形参的名字（用于检查改写后的替换文本会不会被局部变量遮住）。"""
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


def _shadowing_problems(sl: Slice, src: Source, fname: str):
    """替换文本里的根名字（如 ``self`` / ``accounts``）不能和原函数里的局部名冲突。"""
    node = src.top[fname]
    rules = rules_for(sl, fname)
    local = _local_names(node)
    problems = []
    for x in ast.walk(node):
        if isinstance(x, ast.Name) and x.id in rules.name_map:
            for sub in ast.walk(ast.parse(rules.name_map[x.id], mode='eval')):
                if isinstance(sub, ast.Name) and sub.id in local:
                    problems.append(f'{fname}: {x.id} 的替换文本用了 {sub.id}，但函数里有同名局部变量')
    return problems


def _replace_once(text, old, new, where):
    assert text.count(old) == 1, f'{where}: 要替换的文本出现 {text.count(old)} 次（必须恰好 1 次）: {old[:60]!r}'
    return text.replace(old, new)


def _class_text(sl: Slice, src: Source, blocks):
    parts = [f'class {sl.class_name}:', f'    """{sl.class_doc}"""', '']
    params = ', '.join(sl.class_params)
    if params and sl.wrap_init:
        parts.append('    def __init__(' + NL + '            self, *,' + NL
                     + NL.join(f'            {p},' for p in sl.class_params) + NL + '    ):')
    else:
        parts.append(f'    def __init__(self, *, {params}):' if params else '    def __init__(self):')
    body = [('        ' + ln) if ln else '' for ln in sl.init_lines]
    for name, target in sl.state_assigns:
        node = _single_assign(src.tree, name)
        assert node is not None, f'app.py 里没找到状态变量 {name}'
        start = _leading_comment_start(src.lines, node.lineno)
        body.extend('        ' + ln.lstrip() for ln in src.lines[start - 1:node.lineno - 1])
        annotation = ''
        if isinstance(node, ast.AnnAssign):      # `x: dict = {}` 的类型标注原样保留到 self.x 上
            annotation = ': ' + ast.get_source_segment(src.text, node.annotation)
        body.append(f'        {target}{annotation} = {_rhs_text(src, node, 8)}')
    parts.extend(body or ['        pass'])
    if sl.class_extra:
        parts.extend(['', sl.class_extra.rstrip(NL)])
    for block in blocks:
        parts.extend(['', block.rstrip(NL)])
    if sl.manual_methods:
        parts.extend(['', sl.manual_methods.rstrip(NL)])
    return NL.join(parts)


def gen(sl: Slice, src: Source):
    """返回 (模块文本, 问题列表)。"""
    def block_of(name, indent):
        block = extract(src, name, rules_for(sl, name), indent=indent)
        for old, new in sl.doc_edits.get(name, ()):
            block = _replace_once(block, old, new, f'doc_edits[{name}]')
        return block

    blocks = [block_of(name, 4) for name in sorted(sl.funcs, key=lambda n: src.top[n].lineno)]
    module_blocks = [block_of(name, 0) for name in sorted(sl.module_funcs, key=lambda n: src.top[n].lineno)]
    const_blocks = [_const_text(src, n) for n in sl.consts]
    problems = []
    for fname in list(sl.funcs) + list(sl.module_funcs):
        problems.extend(_shadowing_problems(sl, src, fname))

    pieces = []
    if sl.interleave:
        # 常量按它在 app.py 里的位置夹在函数 / 类之间（每个常量紧挨着用它的函数），而不是全部堆在模块开头
        module_names = sorted(sl.module_funcs, key=lambda n: src.top[n].lineno)
        entries = [(src.top[n].lineno, False, b.rstrip(NL)) for n, b in zip(module_names, module_blocks)]
        entries += [(_single_assign(src.tree, n).lineno, True, t) for n, t in zip(sl.consts, const_blocks)]
        entries.sort(key=lambda e: e[0])
        if sl.prelude:
            pieces.append(sl.prelude.rstrip(NL))
        run = []
        for _, is_const, text in entries:
            if is_const:
                run.append(text)
                continue
            if run:
                pieces.append(_join_consts(run))
                run = []
            pieces.append(text)
        if run:
            pieces.append(_join_consts(run))
    else:
        if const_blocks:
            pieces.append(NL.join(const_blocks))
        if sl.prelude:
            pieces.append(sl.prelude.rstrip(NL))
        pieces.extend(b.rstrip(NL) for b in module_blocks)
    if sl.class_name:
        pieces.append(_class_text(sl, src, blocks))
    if sl.factory:
        assert not sl.class_name, '同一个模块里不同时生成类和工厂'
        sig_params = ', '.join(sl.params)
        header_sig = f'def {sl.factory}(*, {sig_params}):' if sl.params else f'def {sl.factory}():'
        if len(header_sig) > 100 and sl.params:
            header_sig = f'def {sl.factory}({NL}        *, ' + (',' + NL + '        ').join(sl.params) + f'{NL}):'
        doc = sl.factory_doc or '依赖都由应用入口显式传入；本模块不导入 app.py。'
        body = [f'    """{doc}"""', f"    routes = Blueprint('{sl.blueprint_name}', __name__)"]
        body.extend(f'    {alias}' for alias in sl.aliases)
        body.append('')
        body.append((NL + NL).join(b.rstrip(NL) for b in blocks))
        body.append('')
        body.append('    return routes')
        pieces.append((header_sig + NL + NL.join(body) + NL).rstrip(NL))
    else:
        assert sl.class_name or not sl.funcs, 'funcs 非空时必须给 factory 或 class_name'
    code_text = (NL + NL + NL).join(pieces) + NL

    prefix = ('from flask import Blueprint' + NL) if sl.factory else ''
    used, defined_here = _global_refs(prefix + code_text)
    if sl.prelude:   # 注解里的名字 symtable 不一定报告，这里按 AST 补上
        used |= {n.id for n in ast.walk(ast.parse(sl.prelude))
                 if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
    table = _import_table(src)
    defs = _toplevel_defs(src)
    moved = set(sl.funcs) | set(sl.module_funcs) | set(sl.consts)
    imports = ['from flask import Blueprint'] if sl.factory else []
    for name in sorted(used):
        if name == 'Blueprint' or hasattr(builtins, name) or name in defined_here:
            continue
        if name in sl.import_overrides:
            imports.append(sl.import_overrides[name])
            continue
        if name in table:
            entry = table[name]
            if entry[0] == 'from' and entry[1] == 'src.utils' and not sl.allow_src_utils:
                problems.append(f'{name} 来自 src.utils（会拖进浏览器库），请在 import_overrides 里指定替代')
                continue
            imports.append(_render_import(name, entry))
        elif name in defs and name not in moved:
            problems.append(f'{name} 是 app.py 里留下的顶层定义，需要注入（params）或一起搬走')
        else:
            problems.append(f'无法解析名字 {name}')
    text = f'# -*- coding: utf-8 -*-{NL}"""{sl.doc}"""{NL}' + _group_imports(imports) + NL + NL + NL + code_text
    for old, new in sl.comment_edits:
        text = _replace_once(text, old, new, 'comment_edits')
    ast.parse(text)
    return text, problems


# ---------------------------------------------------------------------------------------------
def _used_names(tree):
    return {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}


def _stmt_names(node):
    if isinstance(node, (ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef)):
        return {node.name}
    if isinstance(node, ast.Assign):
        return {t.id for t in node.targets if isinstance(t, ast.Name)}
    return set()


def patch_app(sl: Slice, before_text: str):
    """返回搬迁后的 app.py 文本。"""
    assert '\r' not in before_text
    tree = ast.parse(before_text)
    lines = before_text.split(NL)
    moved = set(sl.funcs) | set(sl.module_funcs) | set(sl.app_replacements)
    state_names = {n for n, _ in sl.state_assigns}
    dropped_assigns = set(sl.consts) | state_names
    drop = []
    found = set()
    replace_at = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in moved:
            start = min([node.lineno] + [d.lineno for d in node.decorator_list])
            start = _leading_comment_start(lines, start)   # 紧挨着函数上方的注释跟着一起走
            drop.append((start, node.end_lineno))
            if node.name in sl.app_replacements:
                replace_at[start] = sl.app_replacements[node.name]
            found.add(node.name)
        elif (isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
              and node.targets[0].id in dropped_assigns):
            drop.append((_leading_comment_start(lines, node.lineno), node.end_lineno))
            found.add(node.targets[0].id)
        elif (isinstance(node, ast.AnnAssign) and node.value is not None and isinstance(node.target, ast.Name)
              and node.target.id in dropped_assigns):
            drop.append((_leading_comment_start(lines, node.lineno), node.end_lineno))
            found.add(node.target.id)
    expected = moved | dropped_assigns
    assert found == expected, f'app.py 里没找到: {expected - found}'
    keep = [True] * len(lines)
    for s, e in drop:
        for i in range(s - 1, e):
            keep[i] = False
    new_lines = []
    for i, ln in enumerate(lines):
        if (i + 1) in replace_at:
            new_lines.extend(replace_at[i + 1].rstrip(NL).split(NL))
        if keep[i]:
            new_lines.append(ln)
    collapsed, blank = [], 0
    for ln in new_lines:
        if ln.strip() == '':
            blank += 1
            if blank <= 2:
                collapsed.append(ln)
        else:
            blank = 0
            collapsed.append(ln)
    text = NL.join(collapsed)

    for anchor, block in sl.insert_after:
        hit = next((n for n in ast.parse(text).body if anchor in _stmt_names(n)), None)
        assert hit is not None, f'insert_after 锚点 {anchor} 不存在'
        ls = text.split(NL)
        ls[hit.end_lineno:hit.end_lineno] = ['', ''] + block.rstrip(NL).split(NL)
        text = NL.join(ls)

    if sl.app_import:
        anchor_tree = ast.parse(text)
        last = None
        for node in anchor_tree.body:
            if isinstance(node, ast.ImportFrom) and (node.module or '').startswith('src.sidecar.'):
                last = node
        assert last is not None, '找不到 src.sidecar 的 import 锚点'
        ls = text.split(NL)
        ls[last.end_lineno:last.end_lineno] = sl.app_import.rstrip(NL).split(NL)
        text = NL.join(ls)
    if sl.registration:
        reg_tree = ast.parse(text)
        last_reg = None
        for node in reg_tree.body:
            if (isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
                    and isinstance(node.value.func, ast.Attribute)
                    and node.value.func.attr == 'register_blueprint'
                    and isinstance(node.value.func.value, ast.Name) and node.value.func.value.id == 'app'):
                last_reg = node
        assert last_reg is not None, '找不到 register_blueprint 锚点'
        ls = text.split(NL)
        ls[last_reg.end_lineno:last_reg.end_lineno] = sl.registration.rstrip(NL).split(NL)
        text = NL.join(ls)

    # 清理「因搬迁而不再使用」的模块级导入（原本就没用的不动）
    before_used = _used_names(tree)
    now_tree = ast.parse(text)
    now_used = _used_names(now_tree)
    newly_unused = (before_used - now_used) | set(sl.drop_extra_imports)
    ls = text.split(NL)
    edits = []
    for node in now_tree.body:
        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        removable = [a for a in node.names
                     if (a.asname or a.name).split('.')[0] in newly_unused
                     and (a.asname or a.name).split('.')[0] not in now_used]
        if not removable:
            continue
        remain = [a for a in node.names if a not in removable]
        if not remain:
            edits.append((node.lineno, node.end_lineno, []))
            continue

        def fmt(a):
            return f'{a.name} as {a.asname}' if a.asname else a.name
        if isinstance(node, ast.ImportFrom):
            head = f"from {'.' * node.level}{node.module or ''} import "
        else:
            head = 'import '
        if node.end_lineno > node.lineno:
            body = [head + '('] + [f'    {fmt(a)},' for a in remain] + [')']
        else:
            body = [head + ', '.join(fmt(a) for a in remain)]
        edits.append((node.lineno, node.end_lineno, body))
    for start, end, body in sorted(edits, reverse=True):
        ls[start - 1:end] = body
    text = NL.join(ls)
    for old, new in sl.app_edits:
        text = _replace_once(text, old, new, 'app_edits')
    ast.parse(text)
    return text


# ---------------------------------------------------------------------------------------------
class _Rewrite(ast.NodeTransformer):
    def __init__(self, rules):
        self.rules = rules

    def visit_Name(self, node):
        if node.id in self.rules.name_map:
            new = ast.parse(self.rules.name_map[node.id], mode='eval').body
            # 只有最外层节点继承原来的读写上下文：``service.x = 1`` 里 ``service`` 本身仍是读取（Load）
            if hasattr(new, 'ctx'):
                new.ctx = node.ctx
            return ast.copy_location(new, node)
        return node

    def visit_Global(self, node):
        # 与 mover.extract 对应：``global X`` 声明整句删除（X 已经变成属性读写）
        missing = [n for n in node.names if n not in self.rules.name_map]
        assert not missing, f'global 声明里的名字不在 name_map 中: {missing}'
        return None

    def visit_Call(self, node):
        func_id = node.func.id if isinstance(node.func, ast.Name) else None
        node = self.generic_visit(node)
        if func_id in self.rules.insert_first:
            node.args.insert(0, ast.parse(self.rules.insert_first[func_id], mode='eval').body)
        return node


def _apply_doc_edits(fn, edits):
    if not edits:
        return
    first = fn.body[0] if fn.body else None
    assert (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)), f'{fn.name}: 声明了 doc_edits 但函数没有文档字符串'
    for old, new in edits:
        first.value.value = _replace_once(first.value.value, old, new, f'doc_edits[{fn.name}]')


def _normalize_docstring(fn):
    """函数自己的文档字符串搬进类 / 工厂后会跟着缩进；比较时按 inspect.cleandoc 归一，只忽略统一缩进的差异。"""
    first = fn.body[0] if fn.body else None
    if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)):
        first.value.value = inspect.cleandoc(first.value.value)


def verify(sl: Slice, before_text: str, module_text: str, after_text: str):
    problems = []
    before = ast.parse(before_text)
    fns = {n.name: n for n in before.body if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
    mod = ast.parse(module_text)
    decorator_rules = types.SimpleNamespace(name_map=dict(sl.decorator_name_map), insert_first={})
    for name in list(sl.funcs) + list(sl.module_funcs):
        rules = rules_for(sl, name)
        want = copy.deepcopy(fns[name])
        decorators = want.decorator_list
        want.decorator_list = []
        want = _Rewrite(rules).visit(want)
        want.name = rules.new_name or want.name
        if rules.def_first_param:
            want.args.args.insert(0, ast.arg(arg=rules.def_first_param, annotation=None, type_comment=None))
        hits = [n for n in ast.walk(mod) if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name == want.name]
        if len(hits) != 1:
            problems.append(f'{name}: 新模块里找到 {len(hits)} 个 {want.name}')
            continue
        got = copy.deepcopy(hits[0])
        new_decorators = got.decorator_list
        got.decorator_list = []
        _apply_doc_edits(want, sl.doc_edits.get(name, ()))
        _normalize_docstring(want)
        _normalize_docstring(got)
        if ast.dump(want) != ast.dump(got):
            problems.append(f'{name}: 函数体与「原函数+声明改写」不一致')
            wl, gl = ast.unparse(want).splitlines(), ast.unparse(got).splitlines()
            for i, (a, b) in enumerate(zip(wl, gl)):
                if a != b:
                    problems.append(f'    首处差异 L{i}: want={a!r} got={b!r}')
                    break
        od = [ast.unparse(_Rewrite(decorator_rules).visit(copy.deepcopy(d))) for d in decorators]
        nd = [ast.unparse(d) for d in new_decorators]
        if od != nd:
            problems.append(f'{name}: 装饰器不一致 {od} vs {nd}')

    for const in sl.consts:
        old_c = [n for n in before.body if isinstance(n, ast.Assign) and len(n.targets) == 1
                 and isinstance(n.targets[0], ast.Name) and n.targets[0].id == const]
        new_c = [n for n in mod.body if isinstance(n, ast.Assign) and len(n.targets) == 1
                 and isinstance(n.targets[0], ast.Name) and n.targets[0].id == const]
        if len(old_c) != 1 or len(new_c) != 1 or ast.dump(old_c[0]) != ast.dump(new_c[0]):
            problems.append(f'常量 {const} 搬迁后不一致')

    # 状态变量的初始化只在 __init__ 的顶层语句里找：方法体里对同一属性的后续赋值（原来的 `global X; X = ...`）不算
    init_body = []
    for cls in (n for n in ast.walk(mod) if isinstance(n, ast.ClassDef) and n.name == sl.class_name):
        for item in cls.body:
            if isinstance(item, ast.FunctionDef) and item.name == '__init__':
                init_body = item.body
    for name, target in sl.state_assigns:
        old_n = _single_assign(before, name)
        hits = [n for n in init_body
                if (isinstance(n, ast.Assign) and len(n.targets) == 1 and ast.unparse(n.targets[0]) == target)
                or (isinstance(n, ast.AnnAssign) and ast.unparse(n.target) == target)]
        if old_n is None or len(hits) != 1 or ast.dump(old_n.value) != ast.dump(hits[0].value):
            problems.append(f'状态变量 {name} -> {target}: 右值与 app.py 里的原写法不一致')

    after = ast.parse(after_text)

    def key(n):
        return (type(n).__name__, getattr(n, 'name', None) or ast.unparse(n)[:90])
    gone = set(sl.funcs) | set(sl.module_funcs) | set(sl.app_replacements)
    gone_assigns = set(sl.consts) | {n for n, _ in sl.state_assigns}
    old_d, new_d = {}, {}
    for n in before.body:
        if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name in gone:
            continue
        if (isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name)
                and n.targets[0].id in gone_assigns):
            continue
        if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name) and n.target.id in gone_assigns:
            continue
        old_d.setdefault(key(n), []).append(ast.dump(n))
    for n in after.body:
        new_d.setdefault(key(n), []).append(ast.dump(n))
    changed = [k for k, v in old_d.items() if new_d.get(k) != v]
    added = [k for k, v in new_d.items() if old_d.get(k) != v and k not in changed]
    return problems, changed, added

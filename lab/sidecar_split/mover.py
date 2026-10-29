# -*- coding: utf-8 -*-
"""机械搬迁工具：从原 app.py 抽取函数源码，按规则做「名字替换 / 首参插入」，再缩进。

只做四种改写，全部基于 AST 位置，不碰字符串和注释：
  1. Name 替换（含装饰器里的 app -> routes）；被映射的名字允许在声明了 ``global`` 的那层函数里被赋值
     （比如 ``_capture_running_task_id = task_id`` -> ``service.running_task_id = task_id``）
  2. 对指定函数的调用 / 定义，在参数列表最前面插入一个参数
  3. 删掉 ``global X`` 声明语句（X 必须都在 name_map 里；X 已经变成属性读写，声明没有意义了）
  4. 整体缩进（多行字符串的续行不缩进，保证字符串内容逐字节不变）
"""
import ast
from collections import defaultdict


class Source:
    def __init__(self, path):
        self.path = path
        self.text = open(path, encoding='utf-8').read()
        self.lines = self.text.split('\n')
        self.tree = ast.parse(self.text)
        self.top = {}
        for node in self.tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                self.top[node.name] = node

    def span(self, node):
        """含装饰器、以及紧挨着上方的连续注释行的 1-based 行号区间 [start, end]。

        紧挨着函数上方的注释说的就是这个函数，必须跟着一起走，不然会在 app.py 里变成孤立注释。
        """
        start = node.lineno
        for dec in getattr(node, 'decorator_list', []):
            start = min(start, dec.lineno)
        while start >= 2 and self.lines[start - 2].lstrip().startswith('#'):
            start -= 1
        return start, node.end_lineno


class Rules:
    def __init__(self, name_map=None, insert_first=None, new_name=None,
                 def_first_param=None, string_names=None, decorator_name_map=None):
        # old Name id -> new text（整段替换，可含点号，如 self._browser.page_state）
        self.name_map = name_map or {}
        # old 被调用的函数名 -> 要插入的第一个实参文本；被调函数名同时按 name_map 改名
        self.insert_first = insert_first or {}
        # 该函数自己的新名字（None=不改）
        self.new_name = new_name
        # 该函数 def 行要在参数最前面插入的形参文本（如 self / record_model）
        self.def_first_param = def_first_param
        # 仅作用于装饰器里的 Name（例如 @app.get 的 app -> routes）；函数体里的同名 Name 走 name_map
        self.decorator_name_map = decorator_name_map or {}


def _line_bytes(lines):
    return [ln.encode('utf-8') for ln in lines]


_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ListComp, ast.SetComp, ast.DictComp,
           ast.GeneratorExp)


def _own_globals(scope):
    """这个函数作用域自己声明的 global 名字（不含嵌套函数里的声明）。"""
    names = set()
    stack = list(ast.iter_child_nodes(scope))
    while stack:
        child = stack.pop()
        if isinstance(child, _SCOPES):
            continue
        if isinstance(child, ast.Global):
            names.update(child.names)
        stack.extend(ast.iter_child_nodes(child))
    return names


def check_mapped_stores(name, fn, mapped):
    """被改名映射的名字不能在函数里被「局部赋值」，除非它所在的那层函数自己声明了 ``global``。

    作用域感知：外层函数声明了 global、内层函数没声明就赋值，在 Python 里内层赋的是局部变量；
    把它改成属性赋值（``service.x = ...``）会悄悄改变语义，所以内层必须有自己的 global 声明才放行。
    """
    def visit(node, scope_globals):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, _SCOPES):
                if hasattr(child, 'args'):
                    clash = {a.arg for a in ast.walk(child.args) if isinstance(a, ast.arg)} & mapped
                    if clash:
                        raise AssertionError((name, 'nested function parameter collides with rename map',
                                              sorted(clash), child.lineno))
                own = _own_globals(child) if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) else set()
                visit(child, own)
                continue
            if isinstance(child, ast.Name) and child.id in mapped and isinstance(child.ctx, (ast.Store, ast.Del)):
                if child.id not in scope_globals:
                    raise AssertionError((name, 'mapped name is assigned locally', child.id, child.lineno))
            visit(child, scope_globals)

    visit(fn, _own_globals(fn))


def extract(src: Source, name: str, rules: Rules, indent: int = 0) -> str:
    node = src.top[name]
    start, end = src.span(node)
    seg_lines = src.lines[start - 1:end]
    seg_bytes = _line_bytes(seg_lines)
    edits = defaultdict(list)  # 相对行号(0-based) -> [(col_start, col_end, replacement_bytes)]

    def rel(lineno):
        return lineno - start

    # 1) def 行：改名 + 首形参
    def_line = rel(node.lineno)
    def_bytes = seg_bytes[def_line]
    # 模块级的类（比如一个自定义异常）也可以原样搬：只改名字 / 缩进，不支持塞首形参，也没有形参要和改名表对冲突
    is_class = isinstance(node, ast.ClassDef)
    assert not (is_class and rules.def_first_param), (name, '类不支持首形参')
    if is_class:
        prefix = b'class '
    else:
        prefix = b'def ' if isinstance(node, ast.FunctionDef) else b'async def '
    name_start = node.col_offset + len(prefix)
    name_end = name_start + len(node.name.encode('utf-8'))
    assert def_bytes[name_start:name_end] == node.name.encode('utf-8'), (name, def_bytes)
    new_name = rules.new_name or node.name
    edits[def_line].append((name_start, name_end, new_name.encode('utf-8')))
    extra_param_line = None
    if rules.def_first_param:
        paren = def_bytes.index(b'(', name_end)
        nxt = def_bytes[paren + 1:paren + 2]
        if def_bytes[paren + 1:].strip() == b'':
            # 参数写在后续行（竖排签名）：在 def 行后面单独补一行 ``self,``，缩进与下一行参数对齐
            following = seg_lines[def_line + 1]
            lead = following[:len(following) - len(following.lstrip())]
            extra_param_line = lead + rules.def_first_param + ','
        else:
            ins = rules.def_first_param.encode('utf-8') + (b'' if nxt == b')' else b', ')
            edits[def_line].append((paren + 1, paren + 1, ins))

    # 2) 函数体 / 装饰器 / 参数默认值里的 Name 与 Call
    inserted_call_ids = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name) and sub.func.id in rules.insert_first:
            fn = sub.func
            ln = rel(fn.lineno)
            line_b = seg_bytes[ln]
            paren = line_b.index(b'(', fn.end_col_offset)
            nxt = line_b[paren + 1:paren + 2]
            ins = rules.insert_first[fn.id].encode('utf-8') + (b'' if nxt == b')' else b', ')
            edits[ln].append((paren + 1, paren + 1, ins))
            inserted_call_ids.add(id(fn))
    mapped = set(rules.name_map) | set(rules.insert_first)
    arg_names = set() if is_class else {a.arg for a in ast.walk(node.args) if isinstance(a, ast.arg)}
    clash = arg_names & mapped
    assert not clash, (name, 'parameter name collides with rename map', clash)
    check_mapped_stores(name, node, mapped)
    # `global X` 声明：X 是模块全局状态，搬进服务 / 工厂之后改成属性读写（service.x / self.x），
    # 声明本身就没有意义了，整句删掉。要求声明里的名字全部在 name_map 里（否则会留下半截 global），
    # 并且这条语句独占一行（否则按行删除会误伤别的语句）。
    drop_lines = set()
    for g in ast.walk(node):
        if not isinstance(g, ast.Global):
            continue
        missing = [n for n in g.names if n not in rules.name_map]
        assert not missing, (name, 'global 声明里的名字不在 name_map 中', missing, g.lineno)
        text_line = seg_lines[rel(g.lineno)].strip()
        assert g.lineno == g.end_lineno and text_line == 'global ' + ', '.join(g.names), (
            name, 'global 语句必须独占一行', g.lineno, text_line)
        drop_lines.add(rel(g.lineno))
    decorator_names = set()
    for dec in node.decorator_list:
        for sub in ast.walk(dec):
            if isinstance(sub, ast.Name):
                decorator_names.add(id(sub))
    for sub in ast.walk(node):
        if not isinstance(sub, ast.Name):
            continue
        if id(sub) in decorator_names:
            table = rules.decorator_name_map
        else:
            table = rules.name_map
        if sub.id in table:
            ln = rel(sub.lineno)
            edits[ln].append((sub.col_offset, sub.end_col_offset, table[sub.id].encode('utf-8')))

    # 3) 应用编辑（同一行从右往左）
    out = []
    for i, line_b in enumerate(seg_bytes):
        for cs, ce, rep in sorted(edits.get(i, []), key=lambda e: (e[0], e[1]), reverse=True):
            line_b = line_b[:cs] + rep + line_b[ce:]
        out.append(line_b.decode('utf-8'))

    # 4) 缩进（多行字符串续行不动；函数自己的文档字符串除外——它只是说明文字，随函数一起缩进，
    #    否则搬进类 / 工厂之后续行会比代码缩进少一截。verify() 按 inspect.cleandoc 归一后比较）
    protected = set()
    first = node.body[0] if node.body else None
    own_doc = (first.value if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
               and isinstance(first.value.value, str) else None)
    for sub in ast.walk(node):
        if isinstance(sub, ast.Constant) and isinstance(sub.value, str) and sub.end_lineno > sub.lineno:
            if sub is own_doc:
                continue
            for ln in range(sub.lineno + 1, sub.end_lineno + 1):
                protected.add(rel(ln))
        if isinstance(sub, ast.JoinedStr) and sub.end_lineno > sub.lineno:
            for ln in range(sub.lineno + 1, sub.end_lineno + 1):
                protected.add(rel(ln))
    pad = ' ' * indent
    res = []
    for i, line in enumerate(out):
        if i in drop_lines:      # `global X` 整句删除（见上）
            continue
        if i in protected or not line.strip():
            res.append(line)
        else:
            res.append(pad + line)
        if i == def_line and extra_param_line is not None:
            res.append(pad + extra_param_line)
    return '\n'.join(res)

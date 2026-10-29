# -*- coding: utf-8 -*-
"""搬迁后 app.py 里「夹在被搬走区域中间」的顶层语句：常量 / 赋值 / 注释块 / 表达式语句。

用法: python list_leftovers.py <before_app.py> <after_app.py> <起始行> <结束行>
把原 app.py 在 [起始行, 结束行] 范围内的顶层非函数语句列出来，并标注它在搬迁后的 app.py 里是否还在。
这些是函数搬走后「留在原地」的东西，要逐个判断：是否属于被搬走的那一组（比如只有测试在用的孤立常量）。
"""
import ast
import sys

before_path, after_path, lo, hi = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
before_text = open(before_path, encoding='utf-8').read()
after_text = open(after_path, encoding='utf-8').read()
before = ast.parse(before_text)
after = ast.parse(after_text)
after_dump = {ast.dump(n) for n in after.body}
lines = before_text.split('\n')

for node in before.body:
    if node.lineno < lo or node.lineno > hi:
        continue
    if isinstance(node, (ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef)):
        continue
    still = ast.dump(node) in after_dump
    seg = ast.get_source_segment(before_text, node) or ''
    first = seg.split('\n')[0][:100]
    # 紧挨着上方的注释
    start = node.lineno
    while start >= 2 and lines[start - 2].lstrip().startswith('#'):
        start -= 1
    print('%5d-%5d %-6s %s%s' % (node.lineno, node.end_lineno, '留在app' if still else '已搬走',
                                 ('[上方注释 %d 行] ' % (node.lineno - start)) if start != node.lineno else '', first))

# -*- coding: utf-8 -*-
"""服务类与路由模块之间的「属性是否存在」静态检查。

搬迁时全局名会被机械改写成 ``self.xxx`` / ``service.xxx``——改名映射写错一个字，生成的代码语法上没问题，``symtable`` 也看不出
（属性不是全局名），只有真调到那条分支才会 ``AttributeError``。这里用 AST 把两类引用对着类的真实成员核一遍：

1. 服务类内部：方法体里读取的 ``self.xxx`` 必须是它的方法 / 类属性 / ``__init__``（或其它方法）里赋过值的实例属性；
2. 路由模块：``service.xxx`` / ``accounts.xxx`` 必须是对应服务类的成员。

覆盖 2026-10 拆出来的所有「服务 + 路由」对：店铺会话、调试浏览器、小红书批量填表、链接采集、淘宝发布、抖店上传。

抖店上传的服务通过两个端口 dataclass 拿浏览器与页面步骤，服务里读的 ``self._browser.xxx`` / ``self._steps.xxx`` 必须是端口的字段，
读的 ``self._accounts.xxx`` 必须是 ``ShopAccountGuard`` 的成员——同样是“改名映射写错一个字就只在那条分支 AttributeError”的问题。
"""
import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SIDECAR = ROOT / 'src' / 'sidecar'

#: (服务类所在模块, 类名, 路由模块, {路由闭包里指向该类实例的变量名})
PAIRS = [
    ('capture_service.py', 'CaptureService', 'capture_routes.py', {'service'}),
    ('xhs_batch_service.py', 'XhsBatchService', 'xhs_batch_routes.py', {'service'}),
    ('shop_service.py', 'ShopSessionService', 'shop_routes.py', {'service'}),
    ('shop_accounts.py', 'ShopAccountGuard', 'shop_routes.py', {'accounts'}),
    ('debug_browser_service.py', 'BrowserDebugService', 'debug_browser_routes.py', {'service'}),
    ('taobao_service.py', 'TaobaoPublishService', 'taobao_routes.py', {'service'}),
    ('shop_accounts.py', 'ShopAccountGuard', 'taobao_routes.py', {'accounts'}),
    ('upload_service.py', 'UploadService', 'upload_routes.py', {'service'}),
    ('shop_accounts.py', 'ShopAccountGuard', 'upload_routes.py', {'accounts'}),
]


def parse(name):
    return ast.parse((SIDECAR / name).read_text(encoding='utf-8'))


def find_class(tree, name):
    return next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == name)


def members(cls):
    """类的方法、类属性，以及任何方法里 ``self.x = ...`` / ``self.x: T = ...`` 赋过值的实例属性。"""
    found = set()
    for node in cls.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            found.add(node.name)
        elif isinstance(node, ast.Assign):
            found.update(t.id for t in node.targets if isinstance(t, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            found.add(node.target.id)
    for node in ast.walk(cls):
        targets = []
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
            targets = [node.target]
        for target in targets:
            for sub in ast.walk(target):
                if isinstance(sub, ast.Attribute) and isinstance(sub.value, ast.Name) and sub.value.id == 'self':
                    found.add(sub.attr)
    return found


def loads(tree, receivers):
    """``<receiver>.attr`` 形式的读取，返回 {attr: 首次出现的行号}。"""
    found = {}
    for node in ast.walk(tree):
        if (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id in receivers
                and isinstance(node.ctx, ast.Load)):
            found.setdefault(node.attr, node.lineno)
    return found


@pytest.mark.parametrize('module,class_name', sorted({(p[0], p[1]) for p in PAIRS}))
def test_service_methods_only_read_self_attributes_that_exist(module, class_name):
    cls = find_class(parse(module), class_name)
    defined = members(cls)
    missing = {attr: line for attr, line in loads(cls, {'self'}).items() if attr not in defined}
    assert missing == {}, '%s.%s 读取了不存在的 self 属性: %s' % (module, class_name, missing)


@pytest.mark.parametrize('service_module,class_name,routes_module,receivers', PAIRS, ids=lambda v: v if isinstance(v, str) else None)
def test_routes_only_use_service_members_that_exist(service_module, class_name, routes_module, receivers):
    defined = members(find_class(parse(service_module), class_name))
    missing = {attr: line for attr, line in loads(parse(routes_module), receivers).items() if attr not in defined}
    assert missing == {}, '%s 用到了 %s 没有的成员: %s' % (routes_module, class_name, missing)


def port_fields(cls):
    """端口 dataclass 的字段名（类体里带类型标注的名字）。"""
    return {node.target.id for node in cls.body if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)}


def nested_loads(cls, outer):
    """``self.<outer>.attr`` 形式的读取，返回 {attr: 首次出现的行号}。"""
    found = {}
    for node in ast.walk(cls):
        if (isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load) and isinstance(node.value, ast.Attribute)
                and isinstance(node.value.value, ast.Name) and node.value.value.id == 'self' and node.value.attr == outer):
            found.setdefault(node.attr, node.lineno)
    return found


@pytest.mark.parametrize('outer,port', [('_browser', 'UploadBrowserPort'), ('_steps', 'UploadStepsPort')])
def test_upload_service_only_reads_port_fields_that_exist(outer, port):
    tree = parse('upload_service.py')
    fields = port_fields(find_class(tree, port))
    used = nested_loads(find_class(tree, 'UploadService'), outer)
    missing = {attr: line for attr, line in used.items() if attr not in fields}
    assert missing == {}, 'UploadService 读取了 %s 没有的字段: %s' % (port, missing)
    # 反过来：端口里声明的每个字段都有人用，没有“声明了却永远传不进来的能力”（死字段会让装配代码白白多传）
    assert fields - set(used) == set(), '%s 声明了但服务没用到的字段: %s' % (port, sorted(fields - set(used)))


def test_upload_service_only_reads_account_guard_members_that_exist():
    guard = members(find_class(parse('shop_accounts.py'), 'ShopAccountGuard'))
    used = nested_loads(find_class(parse('upload_service.py'), 'UploadService'), '_accounts')
    missing = {attr: line for attr, line in used.items() if attr not in guard}
    assert missing == {}, 'UploadService 用到了 ShopAccountGuard 没有的成员: %s' % missing


def test_the_check_itself_catches_a_misspelled_member():
    tree = ast.parse('class S:\n    def __init__(self):\n        self.tasks = {}\n    def run(self):\n        return self.tsaks\n')
    cls = find_class(tree, 'S')
    assert {a for a in loads(cls, {'self'}) if a not in members(cls)} == {'tsaks'}

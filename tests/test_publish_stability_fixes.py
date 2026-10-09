# -*- coding: utf-8 -*-
"""发布稳定性修复的回归测试（2026-10-01 第二轮）。

覆盖本轮修掉的四类问题：
1. `fill_title` 元素句柄在 React 重建后失效（实测 6 次失败，全部死在 click）；
2. 码数「均码」下拉点击未生效 / 判据预算过短（实测 5 次失败）；
3. `_find_sku_row_scope` 传给 `parent()` 的选择器自带 `ancestor::` 轴，
   被 DrissionPage 二次前缀成非法 XPath、异常被吞 —— 两条"优先策略"从未生效；
4. SKU 行容器定位与白底图等待的**成本**（每规格值约 1.4s、每单约 4s）。

前 3 条用桩 + 真实源码执行验证；第 4 条是成本护栏，按源码结构断言。
"""

from __future__ import annotations

import ast
import io
import os
import sys
import time
import types

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

APP_PY = os.path.join(REPO_ROOT, 'tauri-app', 'python-sidecar', 'app.py')
UTILS_PY = os.path.join(REPO_ROOT, 'src', 'utils.py')


def _read(path):
    return io.open(path, encoding='utf-8').read()


def _extract_function(source, name):
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.get_source_segment(source, node)
    raise AssertionError(f'未找到函数 {name}')


def _extract_assign(source, name):
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    return ast.get_source_segment(source, node)
    raise AssertionError(f'未找到模块级常量 {name}')


# ---------------------------------------------------------------------------
# 1. 句柄失效判定
# ---------------------------------------------------------------------------

def _load_is_element_lost_error():
    source = _read(APP_PY)
    namespace = {'__builtins__': __builtins__}
    exec(_extract_function(source, '_is_element_lost_error'), namespace)
    return namespace['_is_element_lost_error']


class _FakeExc(Exception):
    pass


def _exc_named(name, message=''):
    return type(name, (_FakeExc,), {})(message)


@pytest.mark.parametrize('name', ['ElementLostError', 'NoRectError', 'ContextLostError'])
def test_recognises_drissionpage_handle_lost_by_class_name(name):
    """DrissionPage 的句柄失效异常必须被识别（按类名，不依赖硬导入）。"""
    fn = _load_is_element_lost_error()
    assert fn(_exc_named(name)) is True


@pytest.mark.parametrize('message', [
    'Could not find node with given id',
    '元素对象已失效。可能是页面整体刷新，或js局部刷新把元素替换或去除了。\n版本: 4.1.1.4',
])
def test_recognises_handle_lost_by_message(message):
    """类名不匹配时（换包/换导出路径）仍要能按消息文本认出来。"""
    fn = _load_is_element_lost_error()
    assert fn(_FakeExc(message)) is True


@pytest.mark.parametrize('message', ['网络超时', '未找到商品标题输入框', ''])
def test_does_not_misclassify_other_errors(message):
    """非句柄失效的异常绝不能被当成可重试错误，否则会掩盖真实问题。"""
    fn = _load_is_element_lost_error()
    assert fn(_FakeExc(message)) is False


def test_title_fill_no_longer_reuses_a_stale_handle():
    """标题填写必须在每次操作前重新取句柄，并带重试。

    旧实现在 `_ensure_title_brand_name_disabled` **之前**取一次句柄，
    之后直接 `input_element.click()` —— 中间那次页面交互一旦触发重渲染，
    句柄就作废，6 次实盘失败全部死在这一行。
    """
    body = _extract_function(_read(APP_PY), '_fill_title_for_record')
    assert '_is_element_lost_error' in body, '必须按句柄失效重试，而不是整体吞掉异常'
    assert '_title_field_stable' in body, '取句柄前必须等输入框渲染稳定'
    # 取句柄要发生在品牌处理之后（也就是循环体内），不能再是一次性缓存
    brand_pos = body.index('_ensure_title_brand_name_disabled')
    loop_pos = body.index('for attempt in range')
    fetch_inside = body.index('_get_title_input', loop_pos)
    assert brand_pos < loop_pos < fetch_inside, (
        '重新取句柄必须晚于品牌处理，否则竞争窗口依然存在'
    )
    assert 'for attempt in range(1, 4)' in body, '重试次数应有明确上限'
    assert 'raise' in body[body.index('if last_error is not None'):], '重试耗尽必须抛错'


# ---------------------------------------------------------------------------
# 2. 码数下拉点击兜底
# ---------------------------------------------------------------------------

def test_size_picker_click_has_fallbacks_and_menu_confirmation():
    """点击码数下拉必须确认菜单真的展开，并在失败时换点击方式重试。"""
    body = _extract_function(_read(APP_PY), '_configure_sku_structure')
    assert '_size_menu_opened' in body, '点击后必须确认菜单是否展开'
    assert 'by_js=True' in body, '需要准备 JS 点击兜底'
    assert '_click_element_safely' in body, '需要准备安全点击兜底'
    assert '码数下拉未能展开' in body, '必须把"菜单没打开"单列一条错误'
    assert '未找到「均码」分组选项' in body, '必须把"菜单开了但没有均码"单列一条错误'
    assert '_size_menu_candidates_text' in body, '报错必须带上菜单实际候选项'


def test_size_menu_candidates_text_only_reads_visible_menu():
    """诊断 helper 只读可见级联菜单，且不吞掉全部异常。"""
    body = _extract_function(_read(APP_PY), '_size_menu_candidates_text')
    assert 'ecom-g-cascader-menus' in body
    assert 'not(contains(@class,"hidden"))' in body, '必须排除隐藏的菜单，否则会读到陈旧节点'
    assert '(读取失败)' in body, '读取失败要显式标注，不能静默返回空'


# ---------------------------------------------------------------------------
# 3. ancestor:: 非法 XPath（真 bug）
# ---------------------------------------------------------------------------

def test_sku_row_scope_no_longer_passes_ancestor_axis_to_parent():
    """`parent()` 会二次前缀，`ancestor::` 轴必须不再出现在传给它的 locator 里。

    旧代码：`sku_anchor.parent('xpath:ancestor::*[...]')`
    → DrissionPage 拼成 `./ancestor::ancestor::*[...]` 非法 XPath
    → 异常被 except 吞掉，两条"优先策略"永久失效。
    """
    body = _extract_function(_read(UTILS_PY), '_find_sku_row_scope')
    assert 'ancestor::' not in body, (
        '不得再把 ancestor:: 轴交给 parent()；它会被二次前缀成非法 XPath 并被吞掉'
    )
    assert '_SKU_ROW_SCOPE_DEPTH_JS' in body, '应改用一次 JS 在页内算层数'
    # 回退路径必须保留，JS 不可用时功能不能退化
    assert 'for _ in range(10)' in body, '必须保留自底向上硬走的回退路径'


def test_sku_row_scope_depth_js_uses_same_trigger_semantics():
    """JS 探针与 Python 判定必须共用同一套"上传入口"语义，避免两处漂移。"""
    source = _read(UTILS_PY)
    js = _extract_assign(source, '_SKU_ROW_SCOPE_DEPTH_JS')
    xpath = _extract_assign(source, '_SKU_UPLOAD_TRIGGER_XPATH')
    assert 'material-upload-button' in js, 'JS 探针缺少材质上传按钮判据'
    assert 'material-upload-button' in xpath, 'XPath 判据缺少材质上传按钮判据'
    # 注意两种语法的差异：JS 用 CSS 选择器 `input[type="file"]`，
    # XPath 用属性轴 `input[@type="file"]`，不能混用同一个字面量断言。
    assert 'input[type="file"]' in js, 'JS 探针缺少文件输入框判据（CSS 语法）'
    assert 'input[@type="file"]' in xpath, 'XPath 判据缺少文件输入框判据（XPath 语法）'
    assert 'return depth' in js and 'return 0' in js


def test_upload_trigger_probes_one_selector_not_three():
    """行容器内探测上传入口必须只用一条 XPath。

    原来 3 条候选串行探测，全部落空要付 3 × timeout = 0.36s，
    而 `_find_sku_row_scope` 会逐层调用它 —— 这是 SKU 阶段最大的单笔浪费。
    """
    body = _extract_function(_read(UTILS_PY), '_find_sku_upload_trigger_in_scope')
    assert '_SKU_UPLOAD_TRIGGER_XPATH' in body
    assert 'for selector in' not in body, '不得再串行探测多条选择器'
    assert body.count('.eles(') == 1, '整个函数只应发起一次元素查询'


# ---------------------------------------------------------------------------
# 4. 成本护栏（源码结构断言）
# ---------------------------------------------------------------------------

def test_white_bg_settle_no_longer_blocks_on_a_dead_wait():
    """白底图收尾不得再调用返回值只喂 print 的阻塞等待。

    实测 `wait_white_bg_processing_complete(timeout=3.0)` 中位 4.04s、
    33/64 次跑满 4.00~4.25s，返回值只用于一句 print —— 纯等待、零作用。
    """
    source = _read(APP_PY)
    assert 'wait_white_bg_processing_complete(main_tab, timeout=3.0' not in source, (
        '该阻塞等待必须已替换为一次状态探测'
    )
    assert '_white_bg_state' in source, '应改用单次 CDP 往返的状态探测'


def test_white_bg_state_is_imported_explicitly():
    """`from src.utils import *` 不导入下划线开头的名字，必须显式导入。

    这个坑很隐蔽：漏了不会报 ImportError，而是运行时 NameError，
    被上层 except 吞掉后表现为"白底图探测悄悄失效"。

    2026-10-01：app.py 已把 `from src.utils import *` 整体换成显式括号导入，
    原来那行 `from src.utils import _wait_until ...` 不复存在，所以这里改成
    解析 AST 判断——不变量（下划线名字必须在显式导入清单里）没变，而且顺带
    把"不许再用通配导入"也钉住了。
    """
    source = _read(APP_PY)
    tree = ast.parse(source)

    imported = set()
    star_imports = []
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == 'src.utils':
            for alias in node.names:
                if alias.name == '*':
                    star_imports.append(node.lineno)
                    continue
                imported.add(alias.asname or alias.name)

    assert not star_imports, (
        f'app.py 不应再用 `from src.utils import *`（L{star_imports}）：'
        '通配导入会让静态分析和改名检查都失效'
    )
    assert '_white_bg_state' in imported, '下划线开头的名字必须写进显式导入列表'


def test_spec_image_dead_calls_removed():
    """`set_sku_info` 里那两个"算了但没人读"的调用必须删掉。

    `_count_scope_visible_images` / `_collect_scope_visible_image_signatures`
    的结果只被赋给两个从未被读取的局部变量，每个规格值白烧约 0.2s。
    """
    source = _read(UTILS_PY)
    body = _extract_function(source, 'set_sku_info')
    assert 'before_row_image_count' not in body
    assert 'before_row_image_signatures' not in body


# ---------------------------------------------------------------------------
# 5. 全局热点：_is_upload_busy（16 个调用点）
# ---------------------------------------------------------------------------

def _load_utils_function(name, consts=()):
    """从 src/utils.py 提取函数与模块级常量，在桩命名空间里执行。"""
    source = _read(UTILS_PY)
    tree = ast.parse(source)
    segments = []
    found = set()
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            segments.append(ast.get_source_segment(source, node))
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in consts:
                    segments.append(ast.get_source_segment(source, node))
                    found.add(target.id)
    assert found == set(consts), f'缺少模块级常量：{set(consts) - found}'
    namespace = {'__builtins__': __builtins__}
    exec('\n\n'.join(segments), namespace)
    return namespace[name], namespace


class _BusyTab:
    """`run_js` 返回预设值；同时记录是否走了 ele() 回退路径。"""

    def __init__(self, js_result):
        self.js_result = js_result
        self.ele_calls = []

    def run_js(self, script, *args):
        if isinstance(self.js_result, Exception):
            raise self.js_result
        return self.js_result

    def ele(self, selector, timeout=None):
        self.ele_calls.append((selector, timeout))
        return None


@pytest.mark.parametrize('js_result,expected', [(True, True), (False, False)])
def test_upload_busy_uses_single_js_probe(js_result, expected):
    """JS 可用时必须一次判定，且**不再**发起两次串行 ele(timeout=0.1)。

    原实现两次 `ele(timeout=0.1)` 未命中各阻塞满 0.1 秒，实测 509 次调用里
    481 次踩满 0.2 秒 —— 单条商品累计约 2 秒纯空转。
    """
    fn, _ = _load_utils_function('_is_upload_busy', {'_UPLOAD_BUSY_PROBE_JS'})
    tab = _BusyTab(js_result)
    assert fn(tab) is expected
    assert tab.ele_calls == [], 'JS 可用时不得再走 ele 回退（那正是要消掉的空转）'


def test_upload_busy_falls_back_when_js_unavailable():
    """JS 不可用时必须回退原来的两次探测，功能不能依赖该优化。"""
    fn, _ = _load_utils_function('_is_upload_busy', {'_UPLOAD_BUSY_PROBE_JS'})
    tab = _BusyTab(RuntimeError('CDP boom'))
    assert fn(tab) is False
    assert len(tab.ele_calls) == 2, '回退路径应保留原来的两次探测'
    assert all(timeout == 0.1 for _, timeout in tab.ele_calls)


def test_upload_busy_probe_keeps_exact_text_semantics():
    """探针必须沿用 `ele('上传中')` 的**精确**文本语义，不能放宽成"包含"。

    DrissionPage 的无前缀 locator 是精确文本匹配（本会话已实测）。
    放宽成包含会让"上传中"出现在说明文案里时误判为忙，
    把各个 `_wait_until(not busy)` 卡在永远忙上。
    """
    source = _read(UTILS_PY)
    js = _extract_assign(source, '_UPLOAD_BUSY_PROBE_JS')
    assert 'normalize-space(text())="上传中"' in js, '必须是精确匹配'
    assert 'indexOf(\'上传中\')' not in js, '不得用"包含"判断'
    assert 'ecom-g-btn-loading-icon' in js, '必须保留加载图标判据'


# ---------------------------------------------------------------------------
# 6. 全局热点：click_field_action（8 个调用点）
# ---------------------------------------------------------------------------

class _StubArea:
    def __init__(self, js_hit, hit_selector=None):
        self.js_hit = js_hit
        self.hit_selector = hit_selector
        self.ele_calls = []
        self.hovered = 0
        self.scroll = types.SimpleNamespace(to_center=lambda: None)

    def run_js(self, script, *args):
        return self.js_hit

    def ele(self, selector, timeout=None):
        self.ele_calls.append(selector)
        return _StubClickable() if selector == self.hit_selector else None

    def hover(self):
        self.hovered += 1


class _StubClickable:
    def __init__(self):
        self.states = types.SimpleNamespace(is_displayed=True)
        self.clicked = []

    def attr(self, name):
        return 'ecom-g-btn'

    def click(self, by_js=False):
        self.clicked.append(by_js)


class _StubTab:
    def __init__(self, areas):
        self.areas = areas

    def eles(self, selector, timeout=None):
        return self.areas


def _load_click_field_action_with_probe():
    """`click_field_action` 依赖同模块的 `_probe_field_action_index`，一并提取。"""
    source = _read(UTILS_PY)
    tree = ast.parse(source)
    segments = []
    wanted_funcs = {'click_field_action', '_probe_field_action_index'}
    wanted_consts = {'_FIELD_ACTION_PROBE_JS'}
    found = set()
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in wanted_funcs:
            segments.append(ast.get_source_segment(source, node))
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in wanted_consts:
                    segments.append(ast.get_source_segment(source, node))
                    found.add(target.id)
    assert found == wanted_consts

    def _driver(pred, timeout=1.0, interval=0.05):
        for _ in range(3):
            if pred():
                return True
        return False

    namespace = {
        '__builtins__': __builtins__,
        '_wait_until': _driver,
        '_run_interaction_recovery': lambda *a, **k: None,
    }
    exec('\n\n'.join(segments), namespace)
    return namespace['click_field_action']


def test_click_field_action_uses_js_hit_without_serial_fallback_scan():
    """JS 报出命中下标时，必须只对那一条取句柄，不再逐条空扫。

    原来 5 条候选串行探测，未命中各阻塞满 timeout（5 × 0.12 ≈ 0.6s）；
    实测 `媒体上传阶段/主图视频` 在「没有可用按钮」时空转 3133ms 就是这个代价。
    """
    fn = _load_click_field_action_with_probe()
    hit_index = 3
    hit_selector = (
        'xpath:.//*[contains(normalize-space(text()),"一键生成")]'
        '/ancestor::div[contains(@class,"style_modifyButton__")][1]'
    )
    area = _StubArea(js_hit=hit_index, hit_selector=hit_selector)
    assert fn(_StubTab([area]), '主图视频', '一键生成') is True
    assert area.ele_calls and area.ele_calls[0] == hit_selector, (
        'JS 命中的选择器必须被排到最前，否则前面的候选仍要逐条空扫'
    )


def test_click_field_action_keeps_all_five_selectors_and_fallbacks():
    """兜底语义不得被这次提速削掉：候选还必须是 5 条，且 JS 落空时仍逐条探测。"""
    body = _extract_function(_read(UTILS_PY), 'click_field_action')
    # 5 条候选都是相对 area 的 `.//` 路径；不要用 `f'xpath:` 计数，
    # 那会把 `areas = new_tab.eles(f'xpath://div[@attr-field-id=...]')` 也算进来。
    assert body.count("f'xpath:.//") == 5, '候选选择器必须仍是 5 条'
    assert 'area.hover()' in body, 'hover 兜底必须保留'
    assert 'target.click(by_js=True)' in body and 'target.click()' in body, (
        '两种点击兜底必须保留'
    )
    fn = _load_click_field_action_with_probe()
    area = _StubArea(js_hit=-1)
    assert fn(_StubTab([area]), '主图视频', '一键生成') is False
    assert len(area.ele_calls) >= 5, 'JS 报"没有"时仍要走完整的逐条探测兜底'
    assert area.hovered >= 1, 'JS 报"没有"时必须 hover 后再试（按钮可能被 hover 露出）'


def test_field_action_probe_index_semantics():
    """探针三种返回值的语义：命中下标 / -1 全落空 / None 表示 JS 不可用。"""
    fn, _ = _load_utils_function('_probe_field_action_index', {'_FIELD_ACTION_PROBE_JS'})

    class _A:
        def __init__(self, value):
            self.value = value

        def run_js(self, script, *args):
            if isinstance(self.value, Exception):
                raise self.value
            return self.value

    assert fn(_A(2), ['a', 'b', 'c']) == 2
    assert fn(_A(-1), ['a']) == -1
    assert fn(_A(RuntimeError('boom')), ['a']) is None
    assert fn(_A('not-a-number'), ['a']) is None
    assert fn(_A(True), ['a']) is None, 'bool 不能当成下标'
    assert fn(_A(0), []) == -1, '空候选直接判不命中'

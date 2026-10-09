# -*- coding: utf-8 -*-
"""价格库存虚拟滚动表格填写的回归测试（2026-08-27 实盘故障）。

实盘故障：商品 ID-1079741832833 共 15 个 SKU，前 12 个写入成功，
最后 3 个报 `价格库存滚动未推进，剩余SKU未填写：...`。

根因是抖店价格库存表为 rc-virtual-list 虚拟滚动表格：
`scrollTop` 是同步赋值，但行的挂载/卸载由 React 异步提交。
旧实现滚动后只等 `scrollTop` 数值到位就去读行——该判据在赋值瞬间即成立，
等于没等，于是读到的仍是上一屏的旧行，整轮扫描无进展并最终抛错。

本测试不依赖浏览器：用 AST 把 app.py 里的 `_fill_price_stock_and_delivery`
真实源码取出来，在一份模拟 rc-virtual-list 行为（渲染窗口 + 异步提交 + 句柄失效）
的假 DOM 上执行。
"""

import ast
import io
import math
import os
import sys
import time
import types

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

APP_PY = os.path.join(REPO_ROOT, 'tauri-app', 'python-sidecar', 'app.py')


class StaleElementError(RuntimeError):
    """模拟虚拟列表重渲染后旧元素句柄失效。"""


class VirtualTable:
    """rc-virtual-list 虚拟滚动表格模型。

    - holder 视口固定高度，内部按行高铺满总高度
    - 只渲染滚动窗口内的行（含 1 行缓冲）
    - 改变 scrollTop 后要经过 render_delay 才提交新的渲染结果
    - 每次提交都会让上一代的行句柄失效
    """

    def __init__(self, rows, viewport=900, row_height=94.6, render_delay=0.08):
        self.rows = rows
        self.viewport = viewport
        self.row_height = row_height
        self.render_delay = render_delay
        self.scroll_top = 0.0
        self.generation = 0
        self.pending_at = None
        self.committed = self._window_for(0.0)
        self.js_scroll_calls = 0
        # 统计浏览器往返次数：真实环境每次 CDP 往返约 1~5ms，
        # 次数是「流畅度」最直接的代理指标。
        self.roundtrips = 0
        self.by_kind = {}

    def count(self, kind='other', n=1):
        self.roundtrips += n
        self.by_kind[kind] = self.by_kind.get(kind, 0) + n

    def breakdown(self):
        return sorted(self.by_kind.items(), key=lambda kv: kv[1], reverse=True)

    def total_height(self):
        return int(round(self.row_height * len(self.rows)))

    def max_top(self):
        return max(self.total_height() - self.viewport, 0)

    def _window_for(self, top):
        start = max(int(top // self.row_height), 0)
        count = int(math.ceil(self.viewport / self.row_height)) + 1
        return tuple(range(start, min(start + count, len(self.rows))))

    def tick(self):
        if self.pending_at is not None and time.monotonic() >= self.pending_at:
            self.pending_at = None
            window = self._window_for(self.scroll_top)
            if window != self.committed:
                self.committed = window
                self.generation += 1

    def set_scroll(self, top):
        top = float(max(0, min(int(top), self.max_top())))
        if abs(top - self.scroll_top) > 0.5:
            self.scroll_top = top
            self.pending_at = time.monotonic() + self.render_delay
        self.tick()

    def rendered_indices(self):
        self.tick()
        return self.committed

    def root(self):
        return FakeRoot(self)

    def holder(self):
        return FakeHolder(self)


class FakeInput:
    def __init__(self, table, index, field):
        self.table = table
        self.index = index
        self.field = field
        self.generation = table.generation

    def _alive(self):
        self.table.tick()
        if self.generation != self.table.generation or self.index not in self.table.committed:
            raise StaleElementError(f'input {self.field} of row {self.index} detached')

    def attr(self, name):
        self._alive()
        self.table.count('input.attr')
        if name == 'value':
            return self.table.rows[self.index][self.field]
        return None

    def input(self, value, clear=False):
        self._alive()
        self.table.count('input.write')
        self.table.rows[self.index][self.field] = str(value)
        return self


class FakeStates:
    def __init__(self, owner):
        self._owner = owner

    @property
    def is_displayed(self):
        self._owner._alive()
        self._owner.table.count('row.is_displayed')
        return True


class FakeScroll:
    def __init__(self, row):
        self._row = row

    def to_center(self):
        row = self._row
        row._alive()
        table = row.table
        # 真实 scrollIntoView 会同时滚动虚拟容器，可能触发重渲染
        table.set_scroll(row.index * table.row_height - table.viewport / 2 + table.row_height / 2)

    def to_see(self):
        return None


class FakeCell:
    def __init__(self, row, text):
        self._row = row
        self._text = text

    @property
    def text(self):
        self._row._alive()
        self._row.table.count('cell.text')
        return self._text


class FakeRow:
    def __init__(self, table, index):
        self.table = table
        self.index = index
        self.generation = table.generation
        self.states = FakeStates(self)
        self.scroll = FakeScroll(self)

    def _alive(self):
        self.table.tick()
        if self.generation != self.table.generation or self.index not in self.table.committed:
            raise StaleElementError(f'row {self.index} detached')

    @property
    def _data(self):
        return self.table.rows[self.index]

    def attr(self, name):
        self._alive()
        self.table.count('row.attr')
        if name == 'data-row-key':
            return self._data['key']
        return None

    def eles(self, selector, timeout=None):
        self._alive()
        self.table.count('row.eles_spec')
        if 'attr-column-field_spec_' in selector:
            return [FakeCell(self, self._data['name']), FakeCell(self, self._data['size'])]
        return []

    def ele(self, selector, timeout=None):
        self._alive()
        self.table.count('row.ele_input')
        if 'attr-column-field_price' in selector or 'attr-column-field_stock_info' in selector:
            # 允许测试注入「本轮输入框定位不到」：真实环境里 to_center() 触发的
            # 行重挂载会让刚取到的句柄短暂失效，代码据此 continue 交给下一轮重扫。
            flaky = getattr(self.table, 'missing_input_once', None)
            key = self._data['key']
            if flaky and flaky.get(key, 0) > 0:
                flaky[key] -= 1
                self.table.count('row.missing_input')
                return None
        if 'attr-column-field_price' in selector:
            return FakeInput(self.table, self.index, 'price')
        if 'attr-column-field_stock_info' in selector:
            return FakeInput(self.table, self.index, 'stock')
        return None


class FakeHolder:
    def __init__(self, table):
        self.table = table

    def run_js(self, script, *args):
        table = self.table
        table.count('holder.js')
        if 'scrollTop = arguments[0]' in script:
            table.js_scroll_calls += 1
            table.set_scroll(args[0])
            return None
        if 'scrollHeight' in script:
            table.tick()
            return {
                'top': int(table.scroll_top),
                'height': int(table.viewport),
                'total': table.total_height(),
            }
        return None


class FakeRoot:
    def __init__(self, table):
        self.table = table

    def run_js(self, script, *args):
        """整表批量扫描：一次往返拿回所有已渲染行的 key/规格/当前值。"""
        self.table.count('root.run_js_scan')
        self.table.tick()
        out = []
        for index in self.table.rendered_indices():
            data = self.table.rows[index]
            texts = [t for t in (data['name'], data['size']) if t]
            out.append({
                'key': data['key'],
                'texts': texts,
                'price': data['price'],
                'stock': data['stock'],
            })
        return out

    def eles(self, selector, timeout=None):
        self.table.count('root.eles_rows')
        if 'ecom-g-table-row' in selector:
            return [FakeRow(self.table, index) for index in self.table.rendered_indices()]
        return []

    def ele(self, selector, timeout=None):
        self.table.count('root.ele_lookup')
        if 'virtual-holder' in selector or 'tbody-virtual' in selector:
            return self.table.holder()
        if 'data-row-key' in selector:
            wanted = selector.split('data-row-key=')[1].strip('] ').strip('\'"')
            for index in self.table.rendered_indices():
                if self.table.rows[index]['key'] == wanted:
                    return FakeRow(self.table, index)
            return None
        return None


class FakeElement:
    """页面上其它无关元素（运费模板、上架按钮等）的通用桩。"""

    def __init__(self):
        self.scroll = types.SimpleNamespace(to_center=lambda: None, to_see=lambda: None)
        self.states = types.SimpleNamespace(is_displayed=False)

    def click(self, by_js=False):
        return None

    def attr(self, name):
        return None

    def input(self, value, clear=False):
        return None


class FakeTab:
    def ele(self, selector, timeout=None):
        return FakeElement()


def _load_fill_function(table):
    """把 app.py 中的目标函数源码取出来，在桩环境里执行（测的是真实代码）。"""
    source = io.open(APP_PY, encoding='utf-8').read()
    tree = ast.parse(source)
    wanted = {'_fill_price_stock_and_delivery', '_normalize_upload_numeric_text'}
    # 模块级常量也要一并取出，否则函数内引用会 NameError 并被静默降级到慢路径
    wanted_consts = {'_PRICE_STOCK_ROW_SCAN_JS'}
    segments = []
    found_consts = set()
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in wanted:
            segments.append(ast.get_source_segment(source, node))
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in wanted_consts:
                    segments.insert(0, ast.get_source_segment(source, node))
                    found_consts.add(target.id)
    assert len(segments) == len(wanted) + len(wanted_consts), f'未能从 app.py 提取到 {wanted | wanted_consts}'
    assert found_consts == wanted_consts, f'缺少模块级常量：{wanted_consts - found_consts}'

    from decimal import Decimal, InvalidOperation
    import re as re_module

    from src.utils import _wait_until, _xpath_literal

    namespace = {
        'Decimal': Decimal,
        'InvalidOperation': InvalidOperation,
        're': re_module,
        'system_time': time,
        '_wait_until': _wait_until,
        '_xpath_literal': _xpath_literal,
        '_dismiss_interfering_overlays': lambda *a, **k: None,
        '_find_price_stock_root': lambda main_tab, timeout=0.2: table.root(),
        'select_text': lambda *a, **k: None,
    }
    exec('\n\n'.join(segments), namespace)
    return namespace['_fill_price_stock_and_delivery']


def _build_case(render_delay):
    """还原实盘失败商品 ID-1079741832833 的 15 个 SKU。"""
    names = [
        '蝴蝶结+均码', '格子+均码', '白色竖条花+均码', '灰色满身花+均码', '布标+均码',
        '蝴蝶结+格子+均码', '蝴蝶结+白色竖条花+均码', '灰色满身花+布标+均码',
        'S2636组合A+均码', 'S2636组合B+均码', 'S2636组合C+均码', 'S2636组合D+均码',
        'S2636组合E+均码', 'S2636组合自选2双+均码', 'S2636组合自选3双+均码',
    ]
    prices = ['6.99'] * 5 + ['13.99'] * 3 + ['20.99'] * 4 + ['20.99', '13.99', '20.99']
    rows = [
        {'key': str(1295 + index), 'name': name, 'size': '', 'price': '', 'stock': ''}
        for index, name in enumerate(names)
    ]
    table = VirtualTable(rows, render_delay=render_delay)
    sku_list = [{'name': name, 'price': prices[index]} for index, name in enumerate(names)]
    record = types.SimpleNamespace(repo=100, name='ID-1079741832833', id=1)
    return table, sku_list, record


@pytest.mark.parametrize('render_delay', [0.0, 0.05, 0.15, 0.35])
def test_all_skus_filled_despite_virtual_render_delay(render_delay):
    """无论虚拟列表重渲染多慢，15 个 SKU 都必须全部写入。"""
    table, sku_list, record = _build_case(render_delay)
    fill = _load_fill_function(table)

    fill(FakeTab(), record, sku_list, '包邮')

    for index, sku in enumerate(sku_list):
        assert table.rows[index]['price'] == sku['price'], f'第{index + 1}行价格未写入'
        assert table.rows[index]['stock'] == '100', f'第{index + 1}行库存未写入'


def test_tail_rows_outside_first_render_window_are_reached():
    """复现实盘故障：首屏渲染不下全部行，末尾几行必须靠滚动被找到并填写。"""
    table, sku_list, record = _build_case(render_delay=0.12)
    first_window = table.rendered_indices()
    assert len(first_window) < len(sku_list), '用例前提：首屏不能渲染出全部行'
    assert 14 not in first_window, '用例前提：最后一行不在首屏'

    fill = _load_fill_function(table)
    fill(FakeTab(), record, sku_list, '包邮')

    assert table.js_scroll_calls > 0, '应当通过 holder.scrollTop 主动滚动加载后续行'
    # 实盘失败的正是这最后 3 个
    for index in (12, 13, 14):
        assert table.rows[index]['price'] == sku_list[index]['price'], f'第{index + 1}行价格未写入'
        assert table.rows[index]['stock'] == '100', f'第{index + 1}行库存未写入'


def test_roundtrip_budget_stays_reasonable(capsys):
    """填 15 个 SKU 的浏览器往返次数必须控制在预算内（流畅度回归护栏）。

    真实环境每次 CDP 往返约 1~5ms，往返次数是「卡顿感」最直接的代理指标。
    """
    table, sku_list, record = _build_case(render_delay=0.12)
    fill = _load_fill_function(table)

    fill(FakeTab(), record, sku_list, '包邮')

    for index, sku in enumerate(sku_list):
        assert table.rows[index]['price'] == sku['price']

    with capsys.disabled():
        print(f'\n[往返次数] 15 个 SKU 共 {table.roundtrips} 次浏览器往返'
              f'（滚动 {table.js_scroll_calls} 次）')
        for kind, n in table.breakdown():
            print(f'    {kind:24s} {n:6d}')

    # 优化前逐行属性读取需 ~2357 次；改为整表 JS 扫描后降至 ~169 次。
    # 预算留足余量，一旦退回逐行读取（例如 JS 扫描被静默降级）立即报警。
    assert table.roundtrips < 300, (
        f'浏览器往返次数 {table.roundtrips} 超出预算，'
        f'填写过程会明显卡顿——应使用整表批量扫描而非逐行属性读取。'
        f'明细：{table.breakdown()}'
    )


def test_missing_row_reports_visible_rows_for_diagnosis():
    """SKU 在表格里根本不存在时，报错必须带上页面当前可见行，便于区分渲染问题与匹配问题。"""
    table, sku_list, record = _build_case(render_delay=0.05)
    sku_list.append({'name': '根本不存在的SKU+均码', 'price': '9.9'})
    fill = _load_fill_function(table)

    with pytest.raises(Exception) as exc_info:
        fill(FakeTab(), record, sku_list, '包邮')

    message = str(exc_info.value)
    assert '根本不存在的SKU+均码' in message, '报错应指明是哪个 SKU 没填上'
    assert '页面当前可见行' in message, '报错应附带页面实际渲染的行，用于定位根因'


# ---------------------------------------------------------------------------
# 2026-10-01 实盘故障回归
# ---------------------------------------------------------------------------

def _flat_table(names, sizes, viewport=2000.0, row_height=100.0, render_delay=0.05, base_key=3000):
    """构造一张一屏放得下的价格库存表（不需要滚动）。"""
    rows = [
        {'key': str(base_key + i), 'name': name, 'size': sizes[i], 'price': '', 'stock': ''}
        for i, name in enumerate(names)
    ]
    return VirtualTable(rows, viewport=viewport, row_height=row_height, render_delay=render_delay), rows


def test_source_size_differs_from_page_uniform_size():
    """颜色规格值带源平台真实尺码、页面码数轴写死「均码」时，仍必须写入。

    实盘：商品 ID-1078276270149 连败 5 次，报
    `价格库存滚动未推进，剩余SKU未填写：榛子蝴蝶结 / 36-40、灰紫格纹 / 36-40、…`。
    失败现场截图与 DOM 快照都显示：这些行的颜色分类规格值就是完整 SKU 名、
    码数轴是「均码」，行与价格/库存输入框都在 DOM 里。

    根因：`_configure_sku_structure` 把码数轴**写死为「均码」**，
    而 sku_list 的名字带着源平台真实尺码，旧的尺码守卫
    `expected_size != row_size → False` 因此必然判不等，
    整批 SKU 永远匹配不上页面行。
    """
    names = ['榛子蝴蝶结 / 36-40', '灰紫格纹 / 36-40', '塞纳灰格纹 / 36-40']
    table, rows = _flat_table(names, ['均码'] * len(names))
    sku_list = [{'name': name, 'price': '20.99'} for name in names]
    record = types.SimpleNamespace(repo=100, name='ID-1078276270149', id=1)

    fill = _load_fill_function(table)
    fill(FakeTab(), record, sku_list, '包邮')

    for index, sku in enumerate(sku_list):
        assert rows[index]['price'] == sku['price'], f'第{index + 1}行({sku["name"]})价格未写入'
        assert rows[index]['stock'] == '100', f'第{index + 1}行({sku["name"]})库存未写入'


def test_multi_spec_name_joined_by_slash_is_matched():
    """多规格连写的名字（`均码/长绒棉/抗起球/独立包装`）不能被当成尺码而否决。"""
    names = [
        '男袜高橡筋款 / 均码/长绒棉/抗起球/独立包装',
        '男袜平板款 / 均码/长绒棉/抗起球/独立包装',
    ]
    table, rows = _flat_table(names, ['均码'] * len(names))
    sku_list = [{'name': name, 'price': '12.5'} for name in names]
    record = types.SimpleNamespace(repo=100, name='ID-X', id=1)

    fill = _load_fill_function(table)
    fill(FakeTab(), record, sku_list, '包邮')

    for index, sku in enumerate(sku_list):
        assert rows[index]['price'] == sku['price'], f'第{index + 1}行价格未写入'


def test_plus_separated_name_matches_page_row():
    """文件夹导入把文件名里的 "-" 换成 "+"，页面行也用 "+" 连接时必须匹配。

    见 app.py `_derive_sku_name`：`candidate.replace('-', '+')`，
    所以库里的 SKU 名同时存在「颜色 / 尺码」和「颜色+尺码」两种写法。
    """
    names = ['S2636组合A+均码', 'S2636组合B+均码', 'S2636组合E+均码']
    table, rows = _flat_table(names, ['均码'] * len(names), base_key=1300)
    sku_list = [{'name': name, 'price': '20.99'} for name in names]
    record = types.SimpleNamespace(repo=100, name='ID-1079741832833', id=1)

    fill = _load_fill_function(table)
    fill(FakeTab(), record, sku_list, '包邮')

    for index, sku in enumerate(sku_list):
        assert rows[index]['price'] == sku['price'], f'第{index + 1}行价格未写入'


def test_skipped_row_is_retried_when_table_needs_no_scrolling():
    """表格一屏放得下（max_top == 0）时，被瞬态跳过的行必须靠原地重扫补上。

    实盘：商品 ID-1081080198595 的表格 10 行全部渲染、价格/库存输入框都在 DOM 里，
    末尾数行却始终没被写入，最终报「价格库存滚动未推进」。

    根因是恢复路径不可达：`next_top <= current_top` 且 `current_top == 0` 时，
    旧实现直接 raise，于是循环体里那句
    「本轮跳过、交给下一轮以新句柄重扫」的承诺永远不会兑现——
    任何一次瞬态重渲染都变成硬失败，且报错文案把「输入框没定位到」
    说成「滚动未推进」，把排查方向带偏。

    本用例锁死该契约：只要本轮还有行被消解，就必须允许原地重扫。
    """
    names = [f'第{i}款 / 均码' for i in range(4)]
    table, rows = _flat_table(names, ['均码'] * len(names))
    assert table.max_top() == 0, '用例前提：表格一屏放得下，无需滚动'

    sku_list = [{'name': name, 'price': '9.9'} for name in names]
    record = types.SimpleNamespace(repo=100, name='ID-1081080198595', id=1)

    # 第 3 行的输入框在第一次定位时拿不到（模拟 to_center() 触发的重挂载）
    table.missing_input_once = {rows[2]['key']: 1}

    fill = _load_fill_function(table)
    fill(FakeTab(), record, sku_list, '包邮')

    for index, sku in enumerate(sku_list):
        assert rows[index]['price'] == sku['price'], f'第{index + 1}行价格未写入（瞬态失效后未重扫）'
        assert rows[index]['stock'] == '100'


def test_permanently_unlocatable_input_still_fails_fast():
    """输入框**始终**定位不到时必须明确失败，不能靠重扫无限打转。

    重试是有限的：只有「本轮还有行被消解」才允许再扫，且最多 `_stall_retry_limit` 次。
    """
    names = [f'第{i}款 / 均码' for i in range(4)]
    table, rows = _flat_table(names, ['均码'] * len(names))

    sku_list = [{'name': name, 'price': '9.9'} for name in names]
    record = types.SimpleNamespace(repo=100, name='ID-X', id=1)
    table.missing_input_once = {rows[2]['key']: 999}

    fill = _load_fill_function(table)
    with pytest.raises(Exception) as exc_info:
        fill(FakeTab(), record, sku_list, '包邮')

    message = str(exc_info.value)
    assert '第3款' in message, '报错应指明是哪个 SKU 没填上'
    assert '输入框' in message, '报错应区分「行已渲染但输入框没定位到」与「行没渲染」'
    # 已填好的行不该被重扫打乱
    assert rows[0]['price'] == '9.9' and rows[1]['price'] == '9.9'


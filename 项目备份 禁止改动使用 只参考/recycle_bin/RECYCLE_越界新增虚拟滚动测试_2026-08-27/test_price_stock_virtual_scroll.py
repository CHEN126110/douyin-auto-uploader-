# -*- coding: utf-8 -*-
"""价格库存虚拟滚动表格填写的回归测试。

复现线上故障：抖店发布页的价格库存表是 rc-virtual-list 虚拟滚动表格，
`scrollTop` 同步生效但行的挂载/卸载由 React 异步提交。旧实现滚动后只等
`scrollTop` 到位就去读行，在机器较快时读到的是滚动前的旧行集合（旧句柄随即失效），
一轮扫描填不到新行；而"已滚到底仍有 SKU 未填"被当成致命错误直接抛
`价格库存滚动未推进，剩余SKU未填写：...`。

本测试不依赖浏览器，直接把 app.py 里的 `_fill_price_stock_and_delivery`
源码取出来在桩环境中执行，用一份忠实模拟 rc-virtual-list 行为
（渲染窗口 + 异步提交 + 句柄失效）的假 DOM 驱动它。
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

APP_PY = os.environ.get(
    'PRICE_STOCK_APP_PY',
    os.path.join(REPO_ROOT, 'tauri-app', 'python-sidecar', 'app.py'),
)


class StaleElementError(RuntimeError):
    """模拟虚拟列表重渲染后旧元素句柄失效"""


class VirtualTable:
    """rc-virtual-list 虚拟滚动表格模型。

    - holder 视口固定高度，内部按行高铺满总高度
    - 只渲染滚动窗口内的行（含 1 行缓冲）
    - 改变 scrollTop 后要经过 render_delay 才提交新的渲染结果
    - 每次提交都会让上一代的行句柄失效
    """

    HOLDER_TOP_IN_WINDOW = 120
    WINDOW_HEIGHT = 1000

    def __init__(self, rows, viewport=900, row_height=94.6, render_delay=0.08):
        self.rows = rows
        self.viewport = viewport
        self.row_height = row_height
        self.render_delay = render_delay
        self.scroll_top = 0.0
        self.page_offset = 0.0
        self.generation = 0
        self.pending_at = None
        self.committed = self._window_for(0.0)
        self.js_scroll_calls = 0
        self.scroll_into_view_calls = 0

    # ---------- 渲染模型 ----------
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

    # ---------- 元素工厂 ----------
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
        if name == 'value':
            return self.table.rows[self.index][self.field]
        return None

    def input(self, value, clear=False):
        self._alive()
        self.table.rows[self.index][self.field] = str(value)
        return self


class FakeStates:
    def __init__(self, owner):
        self._owner = owner

    @property
    def is_displayed(self):
        self._owner._alive()
        return True


class FakeScroll:
    def __init__(self, row):
        self._row = row

    def to_center(self):
        row = self._row
        row._alive()
        table = row.table
        table.scroll_into_view_calls += 1
        # 真实 scrollIntoView 会同时滚动页面和虚拟容器
        table.set_scroll(row.index * table.row_height - table.viewport / 2 + table.row_height / 2)
        table.page_offset = 0.0

    def to_see(self):
        return None


class FakeCell:
    def __init__(self, row, text):
        self._row = row
        self._text = text

    @property
    def text(self):
        self._row._alive()
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
        if name == 'data-row-key':
            return self._data['key']
        return None

    def eles(self, selector, timeout=None):
        self._alive()
        if 'attr-column-field_spec_' in selector:
            return [FakeCell(self, self._data['name']), FakeCell(self, self._data['size'])]
        return []

    def ele(self, selector, timeout=None):
        self._alive()
        if 'attr-column-field_price' in selector:
            return FakeInput(self.table, self.index, 'price')
        if 'attr-column-field_stock_info' in selector:
            return FakeInput(self.table, self.index, 'stock')
        return None

    def run_js(self, script, *args):
        self._alive()
        table = self.table
        top = table.HOLDER_TOP_IN_WINDOW + self.index * table.row_height - table.scroll_top + table.page_offset
        bottom = top + table.row_height
        holder_top = table.HOLDER_TOP_IN_WINDOW + table.page_offset
        holder_bottom = holder_top + table.viewport
        if top < holder_top + 2 or bottom > holder_bottom - 2:
            return False
        return top >= 80 and bottom <= table.WINDOW_HEIGHT - 60


class FakeHolder:
    def __init__(self, table):
        self.table = table

    def run_js(self, script, *args):
        table = self.table
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

    def eles(self, selector, timeout=None):
        if 'ecom-g-table-row' in selector:
            return [FakeRow(self.table, index) for index in self.table.rendered_indices()]
        return []

    def ele(self, selector, timeout=None):
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
    """页面上其它无关元素（运费模板、上架按钮等）的通用桩"""

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


def _load_fill_function(table, extra_globals=None):
    """把 app.py 中的目标函数源码取出来，在桩环境里执行（测的是真实代码）"""
    source = io.open(APP_PY, encoding='utf-8').read()
    tree = ast.parse(source)
    wanted = {'_fill_price_stock_and_delivery', '_normalize_upload_numeric_text'}
    segments = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in wanted:
            segments.append(ast.get_source_segment(source, node))
    assert len(segments) == len(wanted), f'未能从 app.py 提取到 {wanted}'

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
    namespace.update(extra_globals or {})
    exec('\n\n'.join(segments), namespace)
    return namespace['_fill_price_stock_and_delivery']


def _build_case(render_delay):
    names = [
        '灰色碎华+灰色满身蝴蝶结+均码', '条纹+格子+均码', '格子+灰色满身蝴蝶结+均码',
        '纯色白+纯色黑+均码', '纯色灰+条纹+均码',
        'S2633组合A+均码', 'S2633组合B+均码', 'S2633组合C+均码',
        'S2633组合D+均码', 'S2633组合E+均码',
        'S2633组合自选2双+均码', 'S2633组合自选3双+均码',
        'S2633组合自选4双+均码', 'S2633组合自选5双+均码', 'S2633组合自选6双+均码',
    ]
    rows = [
        {'key': str(1295 + index), 'name': name, 'size': '均码', 'price': '', 'stock': ''}
        for index, name in enumerate(names)
    ]
    table = VirtualTable(rows, render_delay=render_delay)
    sku_list = [
        {'name': name, 'price': '13.99' if index < 5 else '20.99'}
        for index, name in enumerate(names)
    ]
    record = types.SimpleNamespace(repo=100, name='ID-1077423662945', id=1)
    return table, sku_list, record


@pytest.mark.parametrize('render_delay', [0.0, 0.05, 0.15, 0.35])
def test_all_skus_filled_despite_virtual_render_delay(render_delay):
    """无论虚拟列表重渲染多慢，15 个 SKU 都必须全部写入"""
    table, sku_list, record = _build_case(render_delay)
    fill = _load_fill_function(table)

    fill(FakeTab(), record, sku_list, '包邮')

    for index, sku in enumerate(sku_list):
        assert table.rows[index]['price'] == sku['price'], f'第{index + 1}行价格未写入'
        assert table.rows[index]['stock'] == '100', f'第{index + 1}行库存未写入'


def test_rows_outside_first_render_window_are_reached():
    """首屏只渲染 11 行，最后 4 行必须靠滚动被找到并填写（线上故障场景）"""
    table, sku_list, record = _build_case(render_delay=0.12)
    assert len(table.rendered_indices()) == 11, '首屏渲染行数应与线上快照一致'

    fill = _load_fill_function(table)
    fill(FakeTab(), record, sku_list, '包邮')

    assert table.js_scroll_calls > 0, '应当通过 holder.scrollTop 主动滚动加载后续行'
    for index in range(11, 15):
        assert table.rows[index]['price'] == sku_list[index]['price']
        assert table.rows[index]['stock'] == '100'


def test_missing_row_reports_diagnostic_context():
    """SKU 在表格里不存在时，报错必须带上定位信息，而不是含糊的『滚动未推进』"""
    table, sku_list, record = _build_case(render_delay=0.05)
    sku_list.append({'name': '根本不存在的SKU+均码', 'price': '9.9'})
    fill = _load_fill_function(table)

    with pytest.raises(Exception) as exc_info:
        fill(FakeTab(), record, sku_list, '包邮')

    message = str(exc_info.value)
    assert '价格库存未找到匹配行' in message
    assert '根本不存在的SKU+均码' in message
    assert '当前渲染行[' in message


def _build_protocol_executor():
    from src.utils import _wait_until
    from protocol_publish.stages.price_stock_runtime import (
        PriceStockStageDependencies,
        PriceStockStageExecutor,
    )

    deps = PriceStockStageDependencies(
        dismiss_interfering_overlays=lambda *a, **k: None,
        select_text=lambda *a, **k: None,
        wait_until=_wait_until,
        timer_record=lambda *a, **k: None,
        get_current_tab_url=lambda tab: 'https://fxg.jinritemai.com/',
    )
    return PriceStockStageExecutor(deps)


@pytest.mark.parametrize('render_delay', [0.0, 0.05, 0.15, 0.35])
def test_protocol_dom_writer_fills_all_skus(render_delay, monkeypatch):
    """协议发布流水线的 DOM 写入分支同样不能被虚拟滚动重渲染卡住"""
    sidecar_dir = os.path.join(REPO_ROOT, 'tauri-app', 'python-sidecar')
    if sidecar_dir not in sys.path:
        sys.path.insert(0, sidecar_dir)

    table, sku_list, record = _build_case(render_delay)
    executor = _build_protocol_executor()
    monkeypatch.setattr(type(executor), '_get_price_stock_root', lambda self, main_tab: table.root())

    result = executor._execute_dom_price_stock_write(
        main_tab=FakeTab(), record=record, sku_list=sku_list
    )

    assert result['processed_row_count'] == len(sku_list)
    for index, sku in enumerate(sku_list):
        assert table.rows[index]['price'] == sku['price'], f'第{index + 1}行价格未写入'
        assert table.rows[index]['stock'] == '100', f'第{index + 1}行库存未写入'

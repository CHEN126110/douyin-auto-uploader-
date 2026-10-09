# -*- coding: utf-8 -*-
"""提交阶段「假失败」回归测试（2026-10-01 实盘故障）。

实盘现象：商品 ID-1081080198595 已提交成功，页面显示
「商品提交成功，需审核通过后生效」，程序却判定 `submit_publish` 失败，
且数据库里该记录仍是 `status=0`（未发布）。用户看到"失败"就会重跑 ——
而失败路径不落库，重跑即重复铺货。

已实测排除选择器漂移：用 DrissionPage 4.1.1.4 连上失败现场页面，
`'商品提交成功，继续发布商品视频，分享到抖音'` 与
`xpath://*[contains(text(),"商品提交成功")]` 均命中。
真正的根因是 13 秒等待窗口太短（5 次失败的耗时全部跑满窗口）。

本测试不依赖浏览器：用 AST 把 app.py 里的 `_submit_publish` 真实源码取出来，
在一份桩 tab 上执行。
"""

import ast
import io
import os
import sys
import time

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

APP_PY = os.path.join(REPO_ROOT, 'tauri-app', 'python-sidecar', 'app.py')

_WANTED_FUNCS = {'_submit_publish'}
_WANTED_CLASSES = {'PublishUnconfirmedError'}
_WANTED_CONSTS = {'_SUBMIT_CONFIRM_TIMEOUT', '_SUBMIT_RESULT_BUTTONS', '_SUBMIT_STATE_PROBE_JS'}


class StubElement:
    def __init__(self):
        self.clicked = 0

    def click(self, by_js=False):
        self.clicked += 1
        return None


class StubTab:
    """桩标签页：`run_js` 依次吐出预置状态，随后重复最后一个。"""

    def __init__(self, states):
        self.states = list(states)
        self.probe_calls = 0

    def run_js(self, script, *args):
        self.probe_calls += 1
        if len(self.states) > 1:
            return self.states.pop(0)
        return self.states[0] if self.states else None

    def ele(self, selector, timeout=None):
        # 只让「发布商品」按钮命中；弹窗与成功文案回退一律落空，
        # 保证判定完全走 _SUBMIT_STATE_PROBE_JS 这条路径。
        # 注意必须用精确的 XPath 片段匹配：成功文案
        # `商品提交成功，继续发布商品视频…` 里也含「发布商品」四个字，
        # 用 `'发布商品' in selector` 会把它误判成按钮。
        if 'text()="发布商品"' in selector:
            return StubElement()
        return None


class StubRecord:
    def __init__(self):
        self.status = 0
        self.publish_time = None
        self.saved = 0

    def save(self):
        self.saved += 1


def _load_submit_function():
    """把 app.py 里的目标函数 / 常量 / 异常类取出来，在桩环境里执行（测的是真实代码）。"""
    source = io.open(APP_PY, encoding='utf-8').read()
    tree = ast.parse(source)
    segments = {'const': [], 'class': [], 'func': []}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in _WANTED_FUNCS:
            segments['func'].append(ast.get_source_segment(source, node))
        elif isinstance(node, ast.ClassDef) and node.name in _WANTED_CLASSES:
            segments['class'].append(ast.get_source_segment(source, node))
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in _WANTED_CONSTS:
                    segments['const'].append(ast.get_source_segment(source, node))
    assert len(segments['func']) == len(_WANTED_FUNCS), f'未提取到函数 {_WANTED_FUNCS}'
    assert len(segments['class']) == len(_WANTED_CLASSES), f'未提取到异常类 {_WANTED_CLASSES}'
    assert len(segments['const']) == len(_WANTED_CONSTS), f'未提取到常量 {_WANTED_CONSTS}'

    def _now():
        return '2026-10-01T00:00:00'

    namespace = {
        '__builtins__': __builtins__,
        'system_time': time,
        'time': type('_T', (), {'now': staticmethod(_now)}),
        '_dismiss_interfering_overlays': lambda *a, **k: None,
        '_get_current_tab_url': lambda tab: 'https://fxg.jinritemai.com/ffa/g/create?',
    }
    body = '\n\n'.join(segments['const'] + segments['class'] + segments['func'])
    exec(body, namespace)
    return namespace['_submit_publish'], namespace


def test_success_text_confirms_publish():
    """读到成功文案即确认，落库 status=1 并写 publish_time。"""
    submit, _ = _load_submit_function()
    tab = StubTab([{'success': True, 'fieldCount': 0, 'resultButtons': [], 'publishModal': False}])
    record = StubRecord()

    assert submit(tab, record) is True
    assert record.status == 1
    assert record.publish_time is not None
    assert record.saved == 1


def test_result_page_buttons_alone_confirm_publish():
    """没有成功文案、但结果页按钮组出现时，必须同样判成功。

    这是修复的核心：旧实现只认整句文案，文案改版或走别的成功分支就判失败，
    而失败路径不落库，重跑即重复铺货。
    """
    submit, _ = _load_submit_function()
    tab = StubTab([{
        'success': False,
        'fieldCount': 0,
        'resultButtons': ['继续发布', '返回商品列表', '编辑商品'],
        'publishModal': False,
    }])
    record = StubRecord()

    assert submit(tab, record) is True
    assert record.status == 1


def test_unconfirmed_raises_and_marks_record_so_start_all_skips_it():
    """读不到成功信号时必须抛可读异常 + 落库 status=2，而不是静默判失败。

    为什么必须落库：「一键发布全部」只挑 `Record.status == 0` 的记录
    （app.py 的 start-all），status=2 因此不会被自动重跑。
    """
    submit, namespace = _load_submit_function()
    namespace['_SUBMIT_CONFIRM_TIMEOUT'] = 0.4  # 缩短等待，测试不必真等 60 秒

    tab = StubTab([{'success': False, 'fieldCount': 30, 'resultButtons': [], 'publishModal': False}])
    record = StubRecord()

    with pytest.raises(namespace['PublishUnconfirmedError']) as exc_info:
        submit(tab, record)

    message = str(exc_info.value)
    assert record.status == 2, '未确认必须落库为 status=2，否则会被自动重跑'
    assert record.saved == 1, '未确认状态必须持久化'
    assert '重复铺货' in message, '报错必须明确提示重复铺货风险'
    assert '审核记录' in message, '报错必须告诉用户去哪里核对'
    assert '已提交待确认' in message, '报错必须说明记录已被标记，不会被自动重跑'
    # 现场信息要带出来，便于事后判断到底是哪种页面状态
    assert '表单字段数' in message


def test_wait_window_is_much_longer_than_the_old_13_seconds():
    """等待预算回归护栏：13s 实测必然跑满（5/5 次失败），不得退回去。"""
    _, namespace = _load_submit_function()
    assert namespace['_SUBMIT_CONFIRM_TIMEOUT'] >= 45, (
        '提交确认窗口过短会让「已提交成功」被误判为失败，进而重复铺货'
    )


def test_probe_js_checks_result_buttons_not_only_success_text():
    """探针必须同时覆盖「成功文案」与「结果页按钮」两个信号。"""
    _, namespace = _load_submit_function()
    probe = namespace['_SUBMIT_STATE_PROBE_JS']
    assert '商品提交成功' in probe
    for button in ('继续发布', '返回商品列表', '编辑商品'):
        assert button in probe
    assert 'attr-field-id' in probe, '探针应一并带回表单字段数，供失败现场判断'


class _TextOnlyTab:
    """`run_js` 不可用（返回 None），只让成功文案的 XPath 命中。"""

    def __init__(self):
        self.clicked = 0

    def run_js(self, script, *args):
        return None

    def ele(self, selector, timeout=None):
        if 'text()="发布商品"' in selector:
            return StubElement()
        if '商品提交成功，继续发布商品视频' in selector:
            return StubElement()
        return None


def test_falls_back_to_text_criterion_when_js_unavailable():
    """`run_js` 不可用时必须回退到原来的整句文案判据，不能直接判失败。"""
    submit, _ = _load_submit_function()
    record = StubRecord()

    assert submit(_TextOnlyTab(), record) is True
    assert record.status == 1

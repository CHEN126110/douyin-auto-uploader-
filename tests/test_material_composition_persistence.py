# -*- coding: utf-8 -*-
"""「面料材质」写入后必须回读校验（2026-10-17 实盘故障）。

实盘现象：`ID-1086978751076` 走完 9 个阶段后在提交被平台拦下：

    所填写的材质含量总和需为100%
    面料材质：涤纶 50%

而 `%LOCALAPPDATA%\\com.dyin.sock-publisher\\user_settings.json` 里配置的是
`粘纤 50 / 聚酰胺纤维（锦纶）22 / 涤纶 28`，**合计正好 100**。
阶段日志显示真实顺序是：

    01:14:55  面料材质配置写入 ok=True      ← 我们写入了 3 项
    01:14:57  水洗标吊牌上传触发 ok=True     ← 紧接着上传吊牌图
    01:16:27  submit_publish failed        ← 字段已被平台 OCR 覆盖成单项「涤纶 50%」

旧实现只在 `uploaded_wash_label` 为真时才在**上传之后**重写材质；这次它是假，
于是字段被覆盖却没有任何人发现 —— 写入返回 True 不代表字段最终正确。

本测试用 AST 抽取真实实现，在桩标签页上跑，不依赖浏览器。
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

_WANTED_FUNCS = {
    '_read_material_composition',
    '_material_percentage_sorted',
    '_ensure_material_composition_persisted',
}
_WANTED_CONSTS = {'_MATERIAL_PERCENT_RE'}

#: 实盘里配置的那三项（合计 100）。
CONFIGURED = [('粘纤', '50'), ('聚酰胺纤维（锦纶）', '22'), ('涤纶', '28')]


class StubField:
    def __init__(self, text):
        self.text = text


class StubTab:
    """`ele()` 返回当前字段文本；`set_text` 用来模拟平台的 OCR 覆盖。"""

    def __init__(self, text=''):
        self.text = text
        self.writes = 0

    def ele(self, selector, timeout=None):
        if '面料材质' not in selector:
            return None
        return StubField(self.text)


def _load_namespace():
    source = io.open(APP_PY, encoding='utf-8').read()
    tree = ast.parse(source)
    segments = {'const': [], 'func': []}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in _WANTED_FUNCS:
            segments['func'].append(ast.get_source_segment(source, node))
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in _WANTED_CONSTS:
                    segments['const'].append(ast.get_source_segment(source, node))
    assert len(segments['func']) == len(_WANTED_FUNCS), f'未提取到函数 {_WANTED_FUNCS}'
    assert len(segments['const']) == len(_WANTED_CONSTS), f'未提取到常量 {_WANTED_CONSTS}'

    import re as _re
    writes = []

    def _fake_set_material(tab, materials, field_id=None):
        writes.append(list(materials))
        tab.writes += 1
        # 真实写入后字段内容会变成配置值
        tab.text = '面料材质 ' + ' '.join(f'{n} {p}%' for n, p in materials)
        return True

    namespace = {
        '__builtins__': __builtins__,
        're': _re,
        'system_time': time,
        'set_material_composition': _fake_set_material,
        '_set_material_writes': writes,
    }
    exec('\n\n'.join(segments['const'] + segments['func']), namespace)
    return namespace


# 页面文本样例（取自真实页面 innerText 片段）
PAGE_OK = '水洗标/吊牌图上传图片可智能识别并预填材质信息 上传图片 *面料材质 粘纤 50% 锦纶 22% 聚酯纤维（涤纶） 28%'
PAGE_CLOBBERED = '水洗标/吊牌图上传图片可智能识别并预填材质信息 上传图片 *面料材质 涤纶 50%'


def test_reads_percentages_from_the_live_field_text():
    namespace = _load_namespace()
    tab = StubTab(PAGE_OK)

    pairs = namespace['_read_material_composition'](tab)

    assert namespace['_material_percentage_sorted'](pairs) == [22, 28, 50]


def test_name_aliasing_does_not_break_the_comparison():
    """平台会做同义归一：配置 `聚酰胺纤维（锦纶）` 在页面上显示为 `锦纶`。

    所以只能比百分比集合，按名称比会永远判不一致、把正常发布判死。
    """
    namespace = _load_namespace()
    normalized = namespace['_material_percentage_sorted']

    assert normalized([('粘纤', '50'), ('聚酰胺纤维（锦纶）', '22'), ('涤纶', '28')]) == [22, 28, 50]
    assert normalized([('粘纤', '50'), ('锦纶', '22'), ('聚酯纤维（涤纶）', '28')]) == [22, 28, 50]


def test_matching_field_passes_without_rewriting():
    namespace = _load_namespace()
    tab = StubTab(PAGE_OK)

    namespace['_ensure_material_composition_persisted'](tab, CONFIGURED)

    assert tab.writes == 0, '字段已经正确时不应重复写入'


def test_clobbered_field_is_reported_but_not_rewritten():
    """实盘：写完之后平台 OCR 把字段改成单项 50%。

    2026-10-17 起**不再重写**：写入是「先清空再重填」，重填在 AI 生成表单那一屏会失败，
    材质因此被清成「已选 (0)」—— 用户看到的就是「先填好了、后面又多一步把它清了」。
    校验只负责报出来，绝不把已经填好的字段再拆一遍。
    """
    namespace = _load_namespace()
    tab = StubTab(PAGE_CLOBBERED)

    with pytest.raises(Exception) as exc_info:
        namespace['_ensure_material_composition_persisted'](tab, CONFIGURED)

    assert tab.writes == 0, '回读不一致时**不许**重写（重写会先清空字段）'
    message = str(exc_info.value)
    assert '不再重写' in message, '报错要说清为什么不重写'
    assert '100%' in message, '报错要指出平台要求合计 100%'
    assert '[22, 28, 50]' in message, '报错要带上期望的百分比集合，便于定位'


def test_unfixable_field_raises_instead_of_letting_submit_fail():
    """即使外部把写入替成「假成功」，也必须明确失败而不是拖到提交阶段。"""
    namespace = _load_namespace()
    tab = StubTab(PAGE_CLOBBERED)

    def _useless_write(_tab, _materials, _field=None):
        return True  # 写入「成功」但字段不变 —— 正是实盘里那种静默失败

    namespace['set_material_composition'] = _useless_write

    with pytest.raises(Exception) as exc_info:
        namespace['_ensure_material_composition_persisted'](tab, CONFIGURED)

    message = str(exc_info.value)
    assert '回读' in message
    assert '100%' in message, '报错要指出平台要求合计 100%'
    assert '[22, 28, 50]' in message, '报错要带上期望的百分比集合，便于定位'


def test_configured_total_must_be_100():
    """配置本身合计不是 100 时提前报错，别让用户等到提交才发现。"""
    namespace = _load_namespace()
    tab = StubTab(PAGE_OK)

    with pytest.raises(Exception) as exc_info:
        namespace['_ensure_material_composition_persisted'](tab, [('涤纶', '50')])

    assert '50%' in str(exc_info.value)
    assert '设置 → 自动化' in str(exc_info.value), '报错要告诉用户去哪里改'


def test_unreadable_field_does_not_hard_fail():
    """读不到百分比时不能硬失败 —— 误判会挡住本可发布的商品。

    提交阶段的现场采集已经把平台的校验提示带出来了（页面校验提示字段），
    所以这里放行不会造成静默漏填。
    """
    namespace = _load_namespace()
    tab = StubTab('')  # 字段文本为空，读不到任何百分比

    namespace['_ensure_material_composition_persisted'](tab, CONFIGURED)  # 不应抛错

    assert tab.writes == 0


# --------------------------------------------------------------------------
# 选项选中环节的回归护栏（`src/utils.py` 的 aurora 多选填写）
#
# 这一段是浏览器强耦合的，桩测试覆盖不了交互，所以按项目惯例钉源码事实。
# --------------------------------------------------------------------------

UTILS_PY = os.path.join(REPO_ROOT, 'src', 'utils.py')


def _utils_source():
    return io.open(UTILS_PY, encoding='utf-8').read()


def _utils_func_body(name):
    source = _utils_source()
    head = source.index(f'def {name}(')
    tail = source.index('\ndef ', head + 10)
    return source[head:tail]


def test_partial_material_selection_must_not_report_success():
    """部分选中必须失败。

    占比是按配置顺序回填到第 idx 个占比输入框的；缺项会让「配置第 i 项的占比」
    落到「实际第 i 个标签」上 —— 2026-10-17 实盘 3 项只选中 1 项，第 0 项
    （粘纤 50）的占比被填给了唯一存在的标签，页面成了单项「涤纶 50%」，
    提交被「所填写的材质含量总和需为100%」拦下。旧实现 `selected_count > 0`
    让这种错误成分以成功收尾。
    """
    body = _utils_func_body('_fill_aurora_composition_select')

    assert 'selected_count != expected_count' in body, '必须要求全部选中'
    assert 'return selected_count > 0' not in body, '旧的部分成功即成功必须去掉'
    assert '不写占比' in body, '部分选中时要跳过占比回填，避免错配'


def test_incomplete_ratio_fill_must_not_report_success():
    """占比没填全同样不能算成功 —— 平台按「含量总和需为100%」校验。"""
    body = _utils_func_body('_fill_aurora_composition_select')

    assert 'expected_ratio_count' in body
    assert 'ratio_filled != expected_ratio_count' in body


def test_create_material_fallback_exists_and_is_safe():
    """搜索不到时必须能走「新建材质」（用户实测平台支持），且不得误点。"""
    source = _utils_source()
    assert 'def _click_aurora_create_material(' in source, '缺少新建材质入口'

    body = _utils_func_body('_click_aurora_create_material')
    for token in ('新建', '新增', '创建'):
        assert token in body, f'新建入口的文本判据应包含「{token}」'
    assert 'string-length(normalize-space(.)) < 40' in body, (
        '必须限制自身文本长度，否则会匹配到整块下拉容器并误点'
    )

    fill_body = _utils_func_body('_fill_aurora_composition_select')
    assert fill_body.count('_click_aurora_create_material') >= 2, (
        '搜索未命中与回车后仍未命中，两处都要尝试新建材质'
    )

def test_collapsed_chips_are_treated_as_unreadable_not_mismatched():
    """芯片区折叠成「+N」时不能判定为不一致（2026-10-17 实盘误拦）。

    6 项材质写进去后芯片区只显示 3 个 + 「+3」，旧回读只解析出前 3 项百分比，
    于是报「页面=[3,3,44] 期望=[1,3,3,24,25,44]」并拦下一次本可成功的发布。
    """
    src = io.open(
        os.path.join(REPO_ROOT, 'tauri-app', 'python-sidecar', 'app.py'), encoding='utf-8'
    ).read()
    body = src.split('def _read_material_composition')[1].split('def _material_percentage_sorted')[0]
    assert '+\\s*\\d+' in body or "r'+\\s*\\d+'" in body or chr(92) + 's*' in body, '必须识别折叠标记 +N'
    assert 'return None' in body, '折叠时必须返回 None（读不到），而不是返回部分结果'

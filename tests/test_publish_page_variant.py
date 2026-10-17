# -*- coding: utf-8 -*-
"""发布页「多形态」兼容回归测试（AI 卡片臂，2026-10-17）。

平台把 `/ffa/g/create` 放进了灰度实验（埋点 `task_name=商品创建组件曝光_UI改版`）：
同一 URL 会渲染出「经典表单」或「AI 卡片」两套组件树，且**按店铺分桶**。

| 店铺 | 主 CTA | 结果 |
|---|---|---|
| 起了个球球（155450371） | `下一步` | 能跑过（经典表单） |
| 拾寻袜子铺（177886360） | `确认信息，继续生成` | 旧代码跑不过 |

AI 卡片臂的实测事实：
- 主按钮带 `style_aiPublishButton` 类、文案「确认信息，继续生成」、**初始 `disabled`**；
- **没有**「下一步」，也**没有**「返回旧版」（源码级 0 命中）→ 「重载回经典」对它无效；
- 页面上只有 `主图` / `商品详情` / `商品标题` 三个 `attr-field-id`，类目/材质/筒高/售价/
  「发布商品」按钮全都不存在；
- 它**同样**带 `[attr-field-id="商品标题"]` 与可见 `#pg-title-input` —— 这正是旧判据
  （标题框 ⇒ step1）把它误判成经典第一页的原因。

本版设计是「把它当下一步」：AI 卡片判成独立阶段 `ai_card`，入口接受它作为合法起点
（不再重载），`_advance_ai_card_page` 等按钮可点后点击并等页面离开 `ai_card`。

不依赖浏览器、不联网：用 AST 抽源码 + 桩标签页。
"""

import ast
import io
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

APP_PY = os.path.join(REPO_ROOT, 'tauri-app', 'python-sidecar', 'app.py')
CATEGORY_PY = os.path.join(REPO_ROOT, 'src', 'enhanced_category_selector.py')

_WANTED_FUNCS = {'_detect_publish_page_stage'}
_WANTED_CONSTS = {
    '_PUBLISH_STAGE_PROBE_JS',
    '_PUBLISH_STEP1_SELECTORS',
    '_PUBLISH_STEP2_SELECTORS',
    '_PUBLISH_AI_CTA_SELECTORS',
    '_PUBLISH_AI_CONFIRM_TEXT',
    '_PUBLISH_AI_CTA_CLASS',
}


def _read(path):
    return io.open(path, encoding='utf-8').read()


def _func_source(path, name):
    source = _read(path)
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.get_source_segment(source, node)
    raise AssertionError(f'{path} 里没有函数 {name}')


def _const_value(name):
    source = _read(APP_PY)
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    return ast.literal_eval(node.value)
    raise AssertionError(f'app.py 里没有常量 {name}')


class StubTab:
    """`run_js` 返回预置阶段；`url` 可切换以验证 outside 分支。"""

    def __init__(self, stage=None, url='https://fxg.jinritemai.com/ffa/g/create?'):
        self.stage = stage
        self.url = url

    def run_js(self, script, *args):
        return self.stage


def _detect_namespace():
    source = _read(APP_PY)
    chunks = []
    for node in ast.parse(source).body:
        if isinstance(node, ast.FunctionDef) and node.name in _WANTED_FUNCS:
            chunks.append(ast.get_source_segment(source, node))
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in _WANTED_CONSTS:
                    chunks.append(ast.get_source_segment(source, node))
    ns = {
        '__builtins__': __builtins__,
        '_get_current_tab_url': lambda tab: tab.url,
        '_is_any_selector_visible': lambda tab, selectors, timeout=None: False,
        '_get_title_input': lambda tab, timeout=None: None,
        '_find_first_visible_element': lambda *a, **k: None,
    }
    exec('\n\n'.join(chunks), ns)
    return ns


# ---------------------------------------------------------------- 判定 ----

def test_probe_js_uses_the_ai_cta_class_and_text():
    """类名与文案由 Python 注入 JS（单一口径），JS 里只负责使用。"""

    assert _const_value('_PUBLISH_AI_CTA_CLASS') == 'style_aiPublishButton'
    assert _const_value('_PUBLISH_AI_CONFIRM_TEXT') == '确认信息，继续生成'
    js = _const_value('_PUBLISH_STAGE_PROBE_JS')
    assert 'arguments[2]' in js and 'arguments[3]' in js, '文案/类名应通过参数注入，避免两处各写一份'
    assert 'aiText' in js and 'aiClass' in js
    assert "return 'ai_card'" in js


def test_probe_js_checks_ai_card_before_the_title_rule():
    js = _const_value('_PUBLISH_STAGE_PROBE_JS')
    assert js.index("return 'ai_card'") < js.index("return 'step1'"), \
        'ai_card 必须早于 step1，否则标题框会造成假阳性'
    assert 'pg-title-input' in js, '经典第一页仍要靠标题框判'


def test_detect_stage_accepts_ai_card():
    ns = _detect_namespace()
    assert ns['_detect_publish_page_stage'](StubTab('ai_card')) == 'ai_card'


def test_detect_stage_accepts_ai_form():
    """点完「确认信息，继续生成」落地的 AI 生成表单（54 字段 + 发布商品）必须单独认出。

    实测 2026-10-17：该页既没有「下一步」也没有经典 step2 锚点，只有「发布商品」
    与「继续上传材料 / 智能填写 / 商品信息质量分」。旧判定靠标题框把它误判成 step1，
    于是整条流程去选一个并不存在的类目，空转 113 秒后失败。
    """

    ns = _detect_namespace()
    assert ns['_detect_publish_page_stage'](StubTab('ai_form')) == 'ai_form'


def test_probe_js_detects_ai_form_by_publish_button_plus_ai_markers():
    js = _const_value('_PUBLISH_STAGE_PROBE_JS')
    assert "return 'ai_form'" in js
    assert '发布商品' in js, '判据应包含「发布商品」按钮'
    for marker in ('继续上传材料', '智能填写', '商品信息质量分'):
        assert marker in js, f'缺少 AI 生成表单的标记 {marker}'
    # ai_form 必须排在 step1 之前，否则又会被标题框抢先判成第一页
    assert js.index("return 'ai_form'") < js.index("return 'step1'")


def test_category_stage_skips_selection_for_ai_form():
    body = _func_source(APP_PY, '_select_category_and_prepare_attributes')
    assert "stage_now == 'ai_form'" in body, 'ai_form 上类目已由 AI 定好，必须跳过类目选择'
    # unknown 必须有有界等待 + 明确报错，不能放任它白等到超时
    assert "stage_now == 'unknown'" in body
    assert '25.0' in body or '25' in body
    assert '_publish_page_signature' in body, '报错要带页面指纹'


def test_category_attributes_accepts_ai_form():
    body = _func_source(APP_PY, '_fill_category_attributes')
    assert "'ai_form'" in body, '属性阶段必须把 ai_form 当作可填写的表单页'
    assert '_publish_page_signature' in body, '跑错页面时报错要带指纹'


# ------------------------------------------------- AI 生成表单的「就绪」 ----

def test_ready_probe_uses_loading_text_and_field_count():
    """骨架屏判据：还在「预计需要5～10秒」或字段数不足，就不算就绪。

    实盘教训（2026-10-17 10:47）：点完 CTA 后平台先给一屏骨架，字段容器在、值还没填，
    3.2 秒就去探测「面料材质」→ 判成字段缺失 → 报「已配置面料材质但页面找不到字段」。
    """

    js = _const_value('_AI_FORM_READY_JS')
    assert '预计需要5' in js and '继续解析你上传的材料' in js, '骨架期文案是就绪判据的一半'
    assert 'attr-field-id' in js, '另一半是字段数量'
    assert 'loading=' in js and 'fields=' in js, '必须返回扁平字符串（页面的 JSON.stringify 被 polyfill 过）'
    # 只禁止**调用**：注释里说明「为什么不能用」是允许的（这里踩过一次同名误判）
    assert 'JSON.stringify(' not in js, '不能真去序列化对象'


def test_advance_waits_for_ai_form_readiness_after_settling():
    body = _func_source(APP_PY, '_advance_ai_card_page')
    at = body.find("settled_stage == 'ai_form'")
    assert at != -1, '稳定在 ai_form 之后还要等它填好'
    assert '_wait_ai_form_ready' in body[at:], 'ai_form 分支必须调用就绪等待'


def test_attributes_stage_waits_for_readiness_before_probing_fields():
    """就绪等待必须发生在**探测字段之前**，否则又会把骨架屏当成字段缺失。"""

    body = _func_source(APP_PY, '_fill_category_attributes')
    ready_at = body.find('_wait_ai_form_ready')
    probe_at = body.find('_first_existing_field_name')
    assert ready_at != -1, '属性阶段必须先等 AI 表单填好'
    assert probe_at != -1
    assert ready_at < probe_at, '就绪等待必须在字段探测之前'


def test_detect_stage_still_recognises_classic_and_outside():
    ns = _detect_namespace()
    assert ns['_detect_publish_page_stage'](StubTab('step2')) == 'step2'
    outside = StubTab('step1', url='https://fxg.jinritemai.com/ffa/g/list')
    assert ns['_detect_publish_page_stage'](outside) == 'outside'


def test_python_fallback_checks_ai_card_before_title_selector():
    body = _func_source(APP_PY, '_detect_publish_page_stage')
    ai_at = body.find('_PUBLISH_AI_CTA_SELECTORS')
    title_at = body.find('attr-field-id="商品标题"')
    assert ai_at != -1 and title_at != -1
    assert ai_at < title_at, 'JS 不可用时的回退路径也要先排除 AI 卡片'


# ---------------------------------------------------------------- 入口 ----

def test_open_publish_page_accepts_ai_card_as_a_valid_start():
    body = _func_source(APP_PY, '_open_publish_page').replace('"', "'")
    assert "'step1', 'step2', 'ai_card'" in body, 'ok_stages 不含 ai_card 就会被当成未知形态去重载'
    assert "'ai_form'" in body, 'ai_form 也必须算合法起点'


def test_open_publish_page_keeps_ai_form_in_place():
    """已经是 AI 生成表单时就地继续：重载会丢掉已生成的内容，按第一页点「下一步」也不对。"""

    body = _func_source(APP_PY, '_open_publish_page')
    at = body.find("if stage == 'ai_form':")
    assert at != -1, '必须有 ai_form 分支，否则会掉进 elif stage != step1 直接返回 False'
    rest = body[at + len("if stage == 'ai_form':"):]
    nxt = rest.find("if stage == 'step2':")
    branch = rest if nxt == -1 else rest[:nxt]
    assert 'return True' in branch
    assert 'main_tab.get(' not in branch


def test_open_publish_page_does_not_reload_when_already_on_ai_card():
    body = _func_source(APP_PY, '_open_publish_page')
    at = body.find("if stage == 'ai_card':")
    assert at != -1, '必须有 ai_card 分支'
    # 只切到下一个同级分支，别把后面的 step2 处理一起吃进来
    rest = body[at + len("if stage == 'ai_card':"):]
    nxt = rest.find("if stage == 'step2':")
    branch = rest if nxt == -1 else rest[:nxt]
    assert 'return True' in branch, 'ai_card 分支应就地返回'
    assert 'main_tab.get(' not in branch, '该臂没有「返回旧版」出口，重载只会空转'


# ---------------------------------------------------------------- 推进 ----

def test_advance_waits_for_enabled_and_raises_with_signature():
    body = _func_source(APP_PY, '_advance_ai_card_page')
    assert "attr('disabled')" in body, '必须等按钮从 disabled 变成可点'
    assert 'raise Exception' in body, '推进失败必须明确抛错'
    assert '_publish_page_signature' in body, '报错要带页面指纹'
    assert '_detect_publish_page_stage' in body, '必须确认页面真的离开了 ai_card'


def test_advance_runs_before_category_selection():
    body = _func_source(APP_PY, '_select_category_and_prepare_attributes')
    advance_at = body.find('_advance_ai_card_page(')
    category_at = body.find('smart_select_category(')
    assert advance_at != -1
    assert advance_at < category_at, 'AI 卡片上没有任何类目控件，必须先推进再选类目'


# ------------------------------------------------------- 「下一步」按钮 ----

def test_click_next_step_accepts_the_ai_cta():
    body = _func_source(CATEGORY_PY, '_click_next_step')
    assert 'style_aiPublishButton' in body
    assert '确认信息，继续生成' in body, '类名改版时靠文案兜底'
    assert body.index('下一步') < body.index('style_aiPublishButton'), \
        '两页并存时应优先点经典「下一步」'


def test_click_next_step_waits_for_disabled_state_to_clear():
    body = _func_source(CATEGORY_PY, '_click_next_step')
    assert "attr('disabled')" in body, 'AI 卡片臂的 CTA 初始 disabled'
    assert 'for _ in range(' in body, '等待必须有界'

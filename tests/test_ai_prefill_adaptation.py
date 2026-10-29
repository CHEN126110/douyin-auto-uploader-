# -*- coding: utf-8 -*-
"""AI 预填的运行时观察与差异执行：不与平台抢写，不无脑清空。"""
from types import SimpleNamespace

import pytest

from src.sidecar import upload_steps
from src.enhanced_category_selector import EnhancedCategorySelector


def snapshot(status='active', fingerprint='a', title='AI 标题', fields=None):
    return {
        'aiStatus': status,
        'fingerprint': fingerprint,
        'title': title,
        'fields': fields or [],
    }


class SequenceTab:
    def __init__(self, states):
        self.states = list(states)
        self.calls = 0

    def run_js(self, script, *args):
        self.calls += 1
        if len(self.states) > 1:
            return self.states.pop(0)
        return self.states[0]


def test_ai_completion_requires_a_stable_form_snapshot():
    tab = SequenceTab([
        snapshot('active', 'a'),
        snapshot('complete', 'b'),
        snapshot('complete', 'b'),
    ])

    result = upload_steps._wait_for_ai_prefill_ready(tab, timeout=1, interval=0)

    assert result['aiStatus'] == 'complete'
    assert tab.calls == 3


def test_legacy_form_without_ai_does_not_wait_for_ai():
    tab = SequenceTab([snapshot('none', 'a'), snapshot('none', 'a')])

    result = upload_steps._wait_for_ai_prefill_ready(tab, timeout=1, interval=0)

    assert result['aiStatus'] == 'none'
    assert tab.calls == 2


def test_ai_timeout_stops_instead_of_racing_platform_writes():
    tab = SequenceTab([snapshot('active', 'a')])

    with pytest.raises(Exception, match='AI 智能填写尚未完成'):
        upload_steps._wait_for_ai_prefill_ready(tab, timeout=0, interval=0)


def test_unstable_legacy_form_timeout_does_not_report_ai_error():
    tab = SequenceTab([snapshot('none', 'changing')])

    result = upload_steps._wait_for_ai_prefill_ready(tab, timeout=0, interval=0)

    assert result['aiStatus'] == 'none'


def test_js_unavailable_uses_legacy_flow_without_blocking():
    class BrokenTab:
        def run_js(self, script, *args):
            raise RuntimeError('JS unavailable')

    assert upload_steps._wait_for_ai_prefill_ready(BrokenTab(), timeout=0, interval=0) is None


@pytest.mark.parametrize('status,current,expected_calls', [
    ('complete', '与商品记录一致', 0),
    ('complete', 'AI 改写标题', 1),
    ('none', 'AI 改写标题', 0),
])
def test_title_is_rewritten_only_for_a_different_ai_prefill(monkeypatch, status, current, expected_calls):
    record = SimpleNamespace(title='与商品记录一致')
    calls = []
    monkeypatch.setattr(upload_steps, '_fill_title_for_record', lambda tab, row: calls.append(row))

    changed = upload_steps._restore_record_title_after_ai(
        object(), record, snapshot(status=status, title=current)
    )

    assert changed is (expected_calls == 1)
    assert calls == ([record] if expected_calls else [])


def test_category_stage_observes_ai_before_short_title_or_attributes():
    source = upload_steps.__loader__.get_source(upload_steps.__name__)
    function_source = source.split('def _select_category_and_prepare_attributes', 1)[1].split(
        'def _upload_wash_label_or_tag_image', 1
    )[0]

    assert '_wait_for_ai_prefill_ready' in function_source
    assert '_restore_record_title_after_ai' in function_source
    assert function_source.index('_wait_for_ai_prefill_ready') < function_source.index('gen_btn')
    assert function_source.index('_wait_for_ai_prefill_ready') < function_source.index('wash_tag_field_exists')


class AiTransitionTab:
    """AI 面板已经出现，但传统表单字段尚未渲染。"""

    def run_js(self, script, *args):
        xpaths = args[0] if args else []
        for index, xpath in enumerate(xpaths):
            if 'index-module_assistant__' in xpath:
                return index
        return -1

    def ele(self, selector, timeout=None):
        return None


def test_ai_panel_counts_as_second_page_before_legacy_fields_render():
    selector = EnhancedCategorySelector(AiTransitionTab())

    assert selector._is_on_second_page() is True
    assert selector._wait_for_second_page(max_wait=0.3) is True


def test_publish_step2_probe_also_includes_ai_assistant():
    source = upload_steps.__loader__.get_source(upload_steps.__name__)
    import ast
    tree = ast.parse(source)
    assignment = next(
        node for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == '_PUBLISH_STEP2_SELECTORS' for target in node.targets)
    )
    selectors = ast.literal_eval(assignment.value)

    assert any('index-module_assistant__' in selector for selector in selectors)


class CancelButton:
    def __init__(self, tab, effective=True):
        self.tab = tab
        self.effective = effective
        self.states = SimpleNamespace(is_displayed=True, is_enabled=True)
        self.scroll = SimpleNamespace(to_center=lambda: None)

    def click(self, by_js=False):
        self.tab.cancel_clicks += 1
        if self.effective:
            self.tab.cancel_clicked = True
            self.tab.cancel_visible = False


class CancelTab:
    def __init__(self, form_snapshot, show_after=1, effective=True):
        self.form_snapshot = form_snapshot
        self.show_after = show_after
        self.snapshot_reads = 0
        self.cancel_visible = show_after == 0
        self.cancel_clicked = False
        self.cancel_clicks = 0
        self.button = CancelButton(self, effective=effective)

    def run_js(self, script, *args):
        if script == upload_steps._PUBLISH_FORM_SNAPSHOT_JS:
            self.snapshot_reads += 1
            if not self.cancel_clicked and self.snapshot_reads >= self.show_after:
                self.cancel_visible = True
            return dict(self.form_snapshot, cancelVisible=self.cancel_visible)
        if 'const specs = arguments[0]' in script:
            return 0 if self.cancel_visible else -1
        return -1

    def eles(self, selector, timeout=None):
        if '取消识别' in selector and self.cancel_visible:
            return [self.button]
        return []


def test_cancel_recognition_is_clicked_when_it_appears_and_title_is_restored(monkeypatch):
    tab = CancelTab(snapshot('active', 'stable', title='AI 改写标题'), show_after=1)
    result = upload_steps._wait_for_ai_prefill_ready(tab, timeout=1, interval=0)
    assert tab.cancel_clicks == 1
    assert result['cancelled'] is True

    calls = []
    record = SimpleNamespace(title='商品记录标题')
    monkeypatch.setattr(upload_steps, '_fill_title_for_record', lambda tab, row: calls.append(row))
    assert upload_steps._restore_record_title_after_ai(object(), record, result) is True
    assert calls == [record]


def test_cancel_recognition_must_take_effect_before_continuing():
    tab = CancelTab(snapshot('active', 'stable'), show_after=0, effective=False)
    with pytest.raises(Exception, match='入口仍未消失'):
        upload_steps._cancel_ai_prefill_if_present(tab, timeout=0)


def test_cancel_recognition_is_scoped_to_ai_assistant():
    source = upload_steps.__loader__.get_source(upload_steps.__name__)
    body = source.split('def _find_ai_prefill_cancel_button', 1)[1].split('def _cancel_ai_prefill_if_present', 1)[0]
    assert 'aside' in body and '取消识别' in body
    assert '_INTERFERING_OVERLAY_TEXTS' not in body

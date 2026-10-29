# -*- coding: utf-8 -*-
"""aurora 材质标签清理与最终内容一致性校验。"""
import types

import pytest

from src import utils


class CloseButton:
    def __init__(self, area):
        self.area = area
        self.states = types.SimpleNamespace(is_displayed=True)

    def click(self, by_js=False):
        if not self.area.stuck:
            self.area.buttons.remove(self)


class CloseArea:
    def __init__(self, count, stuck=False):
        self.buttons = [CloseButton(self) for _ in range(count)]
        self.stuck = stuck
        self.selector_calls = []

    def eles(self, selector, timeout=None):
        self.selector_calls.append(selector)
        if self.stuck:
            return self.buttons
        return list(self.buttons)


def test_clear_old_material_tags_supports_new_and_legacy_close_buttons():
    area = CloseArea(count=2)

    assert utils._clear_aurora_composition_tags(area) is True
    assert area.buttons == []
    selectors = ''.join(area.selector_calls)
    assert 'aurora-select-selection-tag' in selectors
    assert 'aurora-select-selection-item-remove' in selectors


def test_clear_failure_is_not_silent(monkeypatch):
    class FastTime:
        now = 0.0

        @classmethod
        def time(cls):
            cls.now += 0.01
            return cls.now

        @classmethod
        def sleep(cls, seconds):
            cls.now += seconds

    monkeypatch.setattr('src.utils._time', FastTime)
    area = CloseArea(count=1, stuck=True)

    assert utils._clear_aurora_composition_tags(area) is False


class SelectionArea:
    def __init__(self, labels):
        self.labels = labels

    def run_js(self, script, *args):
        return list(self.labels)


@pytest.mark.parametrize('labels,expected', [
    (['棉 75%', '聚氨酯弹性纤维（氨纶） 25%'], True),
    (['棉 75%', '氨纶 25%'], True),
    (['聚酯纤维 95%', '氨纶 5%'], False),
    (['棉 75%', '氨纶 25%', '棉 75%'], False),
    (['棉', '氨纶 25%'], False),
])
def test_material_selection_must_match_target_names_ratios_and_count(labels, expected):
    area = SelectionArea(labels)
    materials = [('棉', '75'), ('氨纶', '25')]

    assert utils._aurora_material_selection_matches(area, materials) is expected


def test_material_selection_cannot_be_verified_is_not_success():
    class BrokenArea:
        def run_js(self, script, *args):
            raise RuntimeError('JS unavailable')

    assert utils._aurora_material_selection_matches(BrokenArea(), [('棉', '75')]) is False

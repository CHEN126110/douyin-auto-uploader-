# -*- coding: utf-8 -*-
"""归档的中文/ASCII 边界：校验与写前拒绝一致，不连接浏览器。"""
from unittest.mock import Mock

import pytest

from taobao_publish.contracts import load_contracts
from taobao_publish.mapping import validate_title
from taobao_publish.models import PublishItem
from taobao_publish import stages
from taobao_publish.text_rules import count_title_units


@pytest.mark.parametrize('text,units', [('', 0), ('A19', 3), ('袜子', 4),
                                     ('袜' * 29 + 'AB', 60), ('袜' * 29 + 'ABC', 61),
                                     ('\U00020000', 2)])
def test_common_title_counter(text, units):
    assert count_title_units(text) == units


@pytest.mark.parametrize('title', ['袜' * 30, 'A' * 60, '袜' * 29 + 'AB'])
def test_boundary_titles_pass(title):
    item = PublishItem(record_id=1, record_name='商品一', title=title)
    assert validate_title(item, load_contracts()) == []
    assert item.summary()['title_length'] == 60


@pytest.mark.parametrize('title', ['袜' * 31, 'A' * 61, '袜' * 29 + 'ABC'])
def test_overlong_title_is_rejected_before_page_access(monkeypatch, title):
    item = PublishItem(record_id=1, record_name='商品一', title=title)
    assert any(b.field == 'title' for b in validate_title(item, load_contracts()))
    open_page = Mock(side_effect=AssertionError('超长标题不应连接浏览器'))
    monkeypatch.setattr(stages, '_open_publish_page', open_page)
    outcome = stages.stage_fill_base(stages.PipelineContext(item=item, dry_run=False))
    assert not outcome.ok and outcome.error_code == 'TITLE_TOO_LONG'
    open_page.assert_not_called()


def test_guide_title_uses_its_own_limit_and_stops_before_writing(monkeypatch):
    item = PublishItem(record_id=1, record_name='商品一', title='棉袜', guide_title='好' * 16)
    assert any(b.field == 'guide_title' for b in validate_title(item, load_contracts()))
    open_page = Mock(side_effect=AssertionError('导购标题超限不应连接浏览器'))
    monkeypatch.setattr(stages, '_open_publish_page', open_page)
    outcome = stages.stage_fill_base(stages.PipelineContext(item=item, dry_run=False))
    assert not outcome.ok and outcome.error_code == 'TITLE_TOO_LONG'
    open_page.assert_not_called()
    item.guide_title = '好' * 15
    assert validate_title(item, load_contracts()) == []


def test_blank_title_is_missing_in_precheck_too():
    item = PublishItem(record_id=1, record_name='商品一', title='   ')
    assert any(b.field == 'title' and b.code == 'REQUIRED_FIELD_MISSING'
               for b in validate_title(item, load_contracts()))

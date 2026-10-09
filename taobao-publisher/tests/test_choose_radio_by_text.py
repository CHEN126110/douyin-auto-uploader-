# -*- coding: utf-8 -*-
"""「按文本选单选项」（``page.choose_radio_by_text``）的模型页测试。

真实场景（E-255）：`上架时间` 行有三个单选 `立刻上架 / 定时上架 / 放入仓库`，
它决定商品**是否立刻对消费者可见**，所以这条路径必须有测试钉住：

* 选中的是**按文本**匹配的那一个，不是按序号；
* 文案在**外层 label**（`input.closest('label')` 命中空的那层）——夹具保留了
  真机结构，代码取不到文案就会在这里红；
* 已是目标值时**不做动作**（幂等）；
* 选项缺失时**报错，不点任何一个**。
"""

from __future__ import annotations

import pytest
from test_candidate_form_adapters import browser, fixture_contracts, item  # noqa: F401

from taobao_publish import page


def test_reads_option_texts_from_the_outer_label(browser):
    """文案挂在**外层 label** 上——`closest('label')` 那层是空的。"""

    state = browser.evaluate(page.build_choose_radio_by_text_expression(
        "上架时间", "放入仓库", True))
    assert state["ok"] is True, state
    # 夹具里三个选项的文案必须都被读出来（读不到就说明取文本的层级又写错了）
    assert state["options"] == ["立刻上架", "定时上架", "放入仓库"]


def test_default_row_starts_on_immediate_listing(browser):
    """夹具初始是「立刻上架」——这正是真机默认值，也正是需要被改掉的那个。"""

    state = browser.evaluate(page.build_choose_radio_by_text_expression(
        "上架时间", "立刻上架", True))
    assert state["checked"] is True


def test_choose_warehouse_selects_by_text_and_reads_back(browser):
    """选「放入仓库」→ 回读确认，且**另两个必须变成未选中**。"""

    result = page.choose_radio_by_text(browser, "上架时间", "放入仓库")
    assert result["checked"] is True and result["unchanged"] is False
    assert browser.evaluate(page.build_choose_radio_by_text_expression(
        "上架时间", "放入仓库", True))["checked"] is True
    assert browser.evaluate(page.build_choose_radio_by_text_expression(
        "上架时间", "立刻上架", True))["checked"] is False
    assert browser.evaluate(page.build_choose_radio_by_text_expression(
        "上架时间", "定时上架", True))["checked"] is False


def test_choose_is_idempotent(browser):
    """已是目标值时**不重复点击**（重跑流水线不会把值改坏）。"""

    page.choose_radio_by_text(browser, "上架时间", "放入仓库")
    again = page.choose_radio_by_text(browser, "上架时间", "放入仓库")
    assert again["unchanged"] is True, again
    assert browser.evaluate(page.build_choose_radio_by_text_expression(
        "上架时间", "放入仓库", True))["checked"] is True


def test_missing_option_fails_without_clicking_anything(browser):
    """选项不存在时**一次点击都不发生**——不能"随便选一个"。"""

    with pytest.raises(page.PageError) as excinfo:
        page.choose_radio_by_text(browser, "上架时间", "上架到月球")
    assert "option_not_unique_or_missing" in str(excinfo.value)
    # 原状态未被改动
    assert browser.evaluate(page.build_choose_radio_by_text_expression(
        "上架时间", "立刻上架", True))["checked"] is True


def test_missing_row_fails(browser):
    """行不存在时明确失败（不是静默跳过）。"""

    with pytest.raises(page.PageError) as excinfo:
        page.choose_radio_by_text(browser, "不存在的行", "放入仓库")
    assert "label_not_found" in str(excinfo.value)

# -*- coding: utf-8 -*-
"""`required_gaps` 的**自相矛盾闸**回归（2026-10-14 真机实例逼出来的）。

真机现象 ✗：同一页上
- `REQUIRED_FIELDS`（扫 `required-icon` 标记）报 `required_count=13`、**`unfilled: []`**；
- 发布助手（`JUDGES`）报 **「1 项必填」**。

两个数对不上 = **我的判据漏了**（价格库存/SKU 那一块没被必填标记覆盖），
**不能沉默地报"无缺口"** ✗ —— 否则上层会以为填满了，误判进度。
这条闸只做一件事：把矛盾显式说出来；**不猜**那 N 项是什么 ✗。
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO / "xiaohongshu-publisher") not in sys.path:
    sys.path.insert(0, str(REPO / "xiaohongshu-publisher"))

from xiaohongshu_publish.flow import _platform_required_total, required_gaps  # noqa: E402


class _Client:
    def __init__(self, required: dict, judges: dict) -> None:
        self.required = required
        self.judges = judges

    def evaluate(self, script: str):
        return self.required if "required-icon" in script else self.judges


class _Page:
    def __init__(self, required: dict, judges: dict) -> None:
        self.client = _Client(required, judges)


def test_contradiction_is_reported_not_silently_ignored():
    """平台报「1 项必填」而标记扫描为空 → 必须报 incomplete，且**不许**猜是哪一项。"""
    page = _Page(
        required={"required_count": 13, "unfilled": [], "filled": ["商品标题", "商品主图"]},
        judges={"key_attrs": ["关键属性 6/7"], "other_attrs": ["其他属性 4/8"],
                "required": ["1 项必填"], "helper_placeholder": True},
    )
    gaps = required_gaps(page)

    assert gaps["unfilled"] == []
    assert gaps["incomplete"] is True
    assert gaps["platform_required_total"] == 1
    assert "1 项必填" in gaps["note"]
    # 不许把"漏掉的那项"编出来
    assert "价格库存" in gaps["note"] or "SKU" in gaps["note"]


def test_no_contradiction_when_platform_reports_none():
    """平台计数为 0 / 读不到时不报 incomplete（避免噪声）。"""
    page = _Page(
        required={"required_count": 13, "unfilled": ["运费模板"], "filled": []},
        judges={"required": ["0 项必填"], "helper_placeholder": False},
    )
    gaps = required_gaps(page)

    assert gaps["unfilled"] == ["运费模板"]
    assert "incomplete" not in gaps
    assert gaps["platform_required_total"] == 0


def test_contradiction_not_raised_when_my_scan_also_finds_gaps():
    """我的扫描也报了缺口 → 不构成矛盾（两边都承认还有活没干）。"""
    page = _Page(
        required={"required_count": 13, "unfilled": ["商品主图"], "filled": []},
        judges={"required": ["2 项必填"], "helper_placeholder": True},
    )
    gaps = required_gaps(page)

    assert gaps["unfilled"] == ["商品主图"]
    assert "incomplete" not in gaps
    assert gaps["platform_required_total"] == 2


def test_platform_total_reads_the_largest_reported_count():
    """多个「N 项必填」出现时取最大值（保守：宁可多报也不能漏报）。"""
    assert _platform_required_total({"required": ["1 项必填", "3 项必填"]}) == 3
    assert _platform_required_total({"required": []}) is None
    assert _platform_required_total({}) is None

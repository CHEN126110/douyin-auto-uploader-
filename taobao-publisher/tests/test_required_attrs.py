# -*- coding: utf-8 -*-
"""必填项写入器（``taobao_publish.required_attrs``）的离线测试。

用**假客户端**注入固定响应，验证：
* 只处理下拉类必填项，非下拉（图片/标题/价格…）不碰；
* **商品事实**（面料/材质成分/产地…）一律留给人；
* 每项**逐项回读**，回读不符要**如实记失败**，且不中断其余项；
* 某一项失败不影响其它项继续。
"""

from __future__ import annotations

import pytest

from taobao_publish import required_attrs as R


#: 各字段的**真实候选**（真机读到的）。夹具必须用真实候选——
#: 否则「稳妥值必须落在候选内」这条约束会把字段判成"没有稳妥值"，
#: 测试就会因为夹具不真实而失败（实测踩过）。
REAL_OPTIONS = {
    "适用季节": ["春季", "夏季", "秋季", "冬季", "四季通用"],
    "适用性别": ["男女通用", "男", "女", "情侣"],
    "适用年龄": ["儿童", "婴幼儿", "成人"],
    "风格": ["中国风", "其他", "卡通"],
}


class _Client:
    """最小假客户端：按表达式内容分派固定响应。"""

    def __init__(self, rows, values=None, fail_on=(), readback=None):
        self.rows = rows
        self.values = dict(values or {})
        self.fail_on = set(fail_on)
        self.readback = dict(readback or {})
        self.calls = []

    def evaluate(self, expression, **kwargs):
        self.calls.append(expression)
        # 分派顺序按"最有特征的片段"来——不要按松散的 `rows: rows` 匹配
        # （实测那个片段在表达式里并不存在，导致所有响应都走错分支）。
        if "taobaoProbePrevPointerEvents" in expression:      # 预览覆盖层放行/恢复
            return {"ok": True, "affected": 1}
        if "options: [...new Set(items)]" in expression:        # 读弹层候选
            return {"menuCount": 1, "options": ["春季", "夏季"]}
        if "point: { x: Math.round" in expression:              # 下拉/按钮定位
            return {"ok": True, "point": {"x": 10, "y": 10}}
        if "PROFILES" in expression:                            # 读必填行
            return {"ok": True, "rows": self.rows}
        return {"ok": True}

    def send(self, method, params=None, **kwargs):
        self.calls.append("send:" + str(method))
        return 1


def _rows(*names, **overrides):
    """构造行记录——**字段名必须与 `read_required_rows` 的真实返回一致**。

    ⚠️ `selectDisplays` 是 `plan_required_defaults` 判"已有值"用的键；夹具漏给会让
    "已填"项被判成空的。夹具不真实，测试就会去追一个不存在的 bug（实测踩过）。
    """

    base = []
    for name in names:
        display = "请选择"
        row = {"name": name, "display": display, "selectDisplays": [display],
               "empty": True, "required": True,
               "options": list(REAL_OPTIONS.get(name, [])), "hint": ""}
        row.update(overrides.get(name, {}))
        # 覆盖 display 时同步 selectDisplays，保持两者一致
        if "display" in overrides.get(name, {}):
            row["selectDisplays"] = [row["display"]]
            row["empty"] = not row["display"] or row["display"] == "请选择"
        base.append(row)
    return base


def _stub_options(monkeypatch):
    """按**字段名**返回真实候选。

    ⚠️ 不要打桩成"固定返回一个列表"：真实 `read_dropdown_options` 会把读到的候选
    写回该行，固定返回会让"适用于性别的候选"被覆盖成季节的候选，
    于是正确地判成"没有稳妥值"——**测试因此失败，但代码是对的**（实测踩过）。
    """

    def stub(client, label, **kwargs):
        return list(REAL_OPTIONS.get(str(label), []))

    monkeypatch.setattr(R, "read_dropdown_options", stub)


def test_fact_fields_are_never_auto_filled(monkeypatch):
    """**商品事实**必须留给人——本层不许猜面料/材质。"""

    rows = _rows("适用季节", "面料", "面料材质成分", "产地")
    client = _Client(rows)
    _stub_options(monkeypatch)
    filled = []
    monkeypatch.setattr(R, "fill_required_attr",
                        lambda c, label, value, **k: filled.append(label) or {"label": label})
    result = R.fill_required_attrs(client)
    assert "适用季节" in filled
    for name in ("面料", "面料材质成分", "产地"):
        assert name not in filled, name + " 是商品事实，不该被自动填"
    assert {item["name"] for item in result["needs_human"]} >= {"面料", "面料材质成分", "产地"}


def test_each_field_is_read_back_and_failure_is_reported(monkeypatch):
    """回读不符要**如实记失败**，且不中断其余项。"""

    rows = _rows("适用季节", "适用性别")
    client = _Client(rows)
    _stub_options(monkeypatch)

    def fake_fill(c, label, value, **kwargs):
        if label == "适用性别":
            raise RuntimeError("回读不一致")
        return {"label": label, "want": value, "after": value}

    monkeypatch.setattr(R, "fill_required_attr", fake_fill)
    result = R.fill_required_attrs(client)
    failed_names = {item["name"] for item in result["failed"]}
    assert failed_names == {"适用性别"}
    assert result["failed"][0]["error"].startswith("RuntimeError")


def test_non_dropdown_required_fields_are_not_touched(monkeypatch):
    """非下拉的必填项（图片/标题/价格/库存/时间）由各自阶段负责，本层不碰。"""

    rows = [
        {"name": "1:1主图", "display": "", "empty": True, "required": True, "options": []},
        {"name": "宝贝标题", "display": "", "empty": True, "required": True, "options": []},
        {"name": "上架时间", "display": "", "empty": True, "required": True, "options": []},
        {"name": "适用季节", "display": "请选择", "empty": True, "required": True, "options": []},
    ]
    client = _Client(rows)
    _stub_options(monkeypatch)
    filled = []
    monkeypatch.setattr(R, "fill_required_attr",
                        lambda c, label, value, **k: filled.append(label) or {"label": label})
    R.fill_required_attrs(client)
    assert filled == ["适用季节"]


def test_only_filter_limits_fields(monkeypatch):
    rows = _rows("适用季节", "适用性别")
    client = _Client(rows)
    _stub_options(monkeypatch)
    filled = []
    monkeypatch.setattr(R, "fill_required_attr",
                        lambda c, label, value, **k: filled.append(label) or {"label": label})
    R.fill_required_attrs(client, only=["适用性别"])
    assert filled == ["适用性别"]


def test_already_filled_fields_are_skipped(monkeypatch):
    """已填的必填项要记进 `already`，**不重复写**。"""

    rows = _rows("品牌", 品牌={"display": "无品牌"})
    assert rows[0]["selectDisplays"] == ["无品牌"], "夹具自检：已填项要带 selectDisplays"
    client = _Client(rows)
    _stub_options(monkeypatch)
    filled = []
    monkeypatch.setattr(R, "fill_required_attr",
                        lambda c, label, value, **k: filled.append(label) or {"label": label})
    result = R.fill_required_attrs(client)
    assert filled == []
    assert result["already"] == [{"name": "品牌", "value": "无品牌"}]

# -*- coding: utf-8 -*-
"""类目属性补全引擎(L3)单元测试。"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.category_attr_suggester import suggest_category_attributes


def test_full_male_business():
    r = suggest_category_attributes(
        name="男士纯棉中筒袜防臭吸汗商务",
        content="精梳棉 透气",
        month=4,
    )
    s = r["suggestions"]
    # 必填都有建议
    assert s["适用性别"]["value"] == "男"
    assert s["筒高"]["value"] == "中筒袜"
    assert s["面料材质"]["value"]  # 纯棉/精梳棉
    assert s["品牌"]["value"] == "无品牌"
    # 功能多选含防臭
    assert s["功能"]["multi"] is True
    assert any("防臭" in c for c in s["功能"]["candidates"])
    # 完整度：必填应满
    assert r["completeness"]["required_filled"] == r["completeness"]["required_total"]
    assert r["completeness"]["score"] > 0.7


def test_candidates_map_to_real_options():
    """筒高/厚度的候选别名应包含抖店实测真实选项。"""
    r = suggest_category_attributes(name="女士长筒袜加厚保暖", month=12)
    s = r["suggestions"]
    # 筒高候选含真实选项"长筒袜"
    assert "长筒袜" in s["筒高"]["candidates"]
    # 厚度候选含真实选项"厚款"
    assert "厚款" in s["厚度"]["candidates"]


def test_no_fabrication_when_no_signal():
    """无材质信号时不臆造面料材质。"""
    r = suggest_category_attributes(name="男士船袜浅口", month=7)
    s = r["suggestions"]
    assert s["面料材质"]["value"] is None  # 文本无材质信号，不编造
    assert "面料材质" in r["completeness"]["missing_required"]
    assert s["筒高"]["value"] == "船袜"


def test_material_evidence_note():
    """材质建议带"需真实证据"提示，不臆造百分比。"""
    r = suggest_category_attributes(name="纯棉中筒袜", month=4)
    s = r["suggestions"]
    assert s["面料材质"]["value"] is not None
    assert "百分比" in s["面料材质"]["note"]
    # 候选只给材质类型，不含百分比数字
    for c in s["面料材质"]["candidates"]:
        assert "%" not in c


def test_season_inferred_by_month():
    r = suggest_category_attributes(name="纯棉中筒袜", month=7)
    assert r["suggestions"]["适用季节"]["value"] == "夏季"
    r2 = suggest_category_attributes(name="纯棉中筒袜", month=1)
    assert r2["suggestions"]["适用季节"]["value"] == "冬季"


def test_completeness_low_when_sparse():
    """信息稀疏时完整度评分低，缺失项被报告。"""
    r = suggest_category_attributes(name="袜子", month=None)
    c = r["completeness"]
    assert c["score"] < 0.7
    assert c["missing_required"]  # 性别/筒高/材质缺失


def test_style_from_persona():
    r = suggest_category_attributes(name="专业运动袜跑步篮球", content="吸汗速干", month=4)
    assert r["suggestions"]["风格"]["value"] in ("运动", "运动风")


def test_serializable():
    r = suggest_category_attributes(name="男士纯棉中筒袜", month=4)
    import json
    json.dumps(r, ensure_ascii=False)  # 不应抛异常

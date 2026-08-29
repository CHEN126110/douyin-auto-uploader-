# -*- coding: utf-8 -*-
"""人货场建模引擎(L1)单元测试。"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.people_goods_scene import (
    build_profile,
    extract_goods_features,
    extract_quantity,
    infer_personas,
    infer_season,
    infer_scenes,
)


def test_extract_goods_features_basic():
    f = extract_goods_features("男士纯棉中筒袜防臭吸汗商务")
    assert "纯棉" in f.get("材质成分", [])
    assert "中筒袜" in f.get("袜筒高度", [])
    assert "抗菌防臭" in f.get("功能", [])
    assert "吸汗速干" in f.get("功能", [])


def test_extract_goods_features_empty():
    assert extract_goods_features("") == {}
    assert extract_goods_features(None) == {}


def test_extract_quantity():
    assert extract_quantity("5双装纯棉袜") == 5
    assert extract_quantity("家庭装10对超值") == 10
    assert extract_quantity("无数量描述") is None
    # 超出合理范围(>50)忽略
    assert extract_quantity("100双") is None


def test_infer_personas_male_business():
    personas = infer_personas("男士商务正装中筒袜")
    assert personas, "应识别出人群"
    assert personas[0].key == "男士商务通勤"
    assert "抗菌防臭" in personas[0].prefer_points


def test_infer_personas_sport():
    personas = infer_personas("专业跑步运动袜毛巾底")
    keys = [p.key for p in personas]
    assert "运动健身" in keys


def test_infer_season_by_text_signal():
    # 文本显式信号优先于月份
    assert infer_season("加厚保暖羊毛袜", month=7) == "冬季"
    assert infer_season("冰丝凉感船袜", month=1) == "夏季"


def test_infer_season_by_month():
    assert infer_season("纯棉袜子", month=7) == "夏季"
    assert infer_season("纯棉袜子", month=12) == "冬季"
    assert infer_season("纯棉袜子", month=4) == "春秋"


def test_infer_scenes():
    scenes = infer_scenes("商务通勤运动跑步两用袜")
    assert "通勤" in scenes
    assert "运动" in scenes


def test_build_profile_integration_male_business():
    p = build_profile(
        name="男士纯棉中筒袜防臭吸汗商务通勤",
        remark="5双装",
        content="精梳棉材质 透气 无骨缝合",
        month=4,
    )
    # 货
    assert p.goods.get("材质成分")  # 纯棉/精梳棉
    assert p.quantity == 5
    # 人
    assert p.primary_persona == "男士商务通勤"
    assert p.pains  # 有痛点
    # 场
    assert p.season == "春秋"
    assert "通勤" in p.scenes
    # 关键词池三组都非空
    assert p.keyword_pool["人"]
    assert p.keyword_pool["货"]
    # 属性建议含性别和季节
    assert p.attribute_suggestions.get("适用性别") == "男"
    assert p.attribute_suggestions.get("适用季节") == "春秋"
    # 每条建议有依据
    for k in p.attribute_suggestions:
        assert k in p.evidence


def test_build_profile_no_brand_no_fabrication():
    """无材质信号时不臆造材质属性。"""
    p = build_profile(name="女士船袜浅口", month=7)
    assert "材质成分" not in p.attribute_suggestions  # 文本无材质信号，不编造
    assert p.goods.get("袜筒高度") == ["船袜"]
    assert p.season == "夏季"


def test_build_profile_empty_safe():
    p = build_profile(name="袜子")
    # 不报错，画像可序列化
    d = p.to_dict()
    assert isinstance(d, dict)
    assert "keyword_pool" in d

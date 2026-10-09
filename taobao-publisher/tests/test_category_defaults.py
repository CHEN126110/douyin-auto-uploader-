# -*- coding: utf-8 -*-
"""类目驱动取值规则（``taobao_publish.category_defaults``）的离线测试。

约束（与本子项目红线一致）：**能推的才给值，推不出就返回 None**——
不编默认值、不猜商品事实（面料/材质只能来自采集数据或人）。
"""

from __future__ import annotations

import pytest

from taobao_publish.category_defaults import (
    hosiery_height_for, most_recent_option, plan_required_defaults,
    platform_recommendation, safe_default_for,
)

TIGHTS_PATH = ["女士内衣/男士内衣/家居服", "短袜/打底袜/丝袜/美腿袜（新）", "中筒袜"]


@pytest.mark.parametrize("leaf,expected", [
    ("中筒袜", "中筒"),
    ("短筒袜", "短筒"),
    ("长筒袜", "长筒"),
    ("过膝袜", "过膝"),
    ("连裤袜", "连裤"),
    ("打底裤", "连裤"),
    ("船袜", "短筒"),
    ("隐形袜", "短筒"),
])
def test_hosiery_height_follows_category_leaf(leaf, expected):
    """用户提的规则：筒高**跟随类目**。"""

    assert hosiery_height_for(TIGHTS_PATH[:-1] + [leaf]) == expected


def test_hosiery_height_returns_none_when_category_does_not_imply_it():
    """推不出就返回 None——**不编值**（否则会把"连衣裙"也填上筒高）。"""

    assert hosiery_height_for(["女装", "连衣裙"]) is None
    assert hosiery_height_for([]) is None


def test_hosiery_height_matches_leaf_not_parent():
    """只看**末级**：上级「短袜/打底袜/丝袜/美腿袜（新）」同时含多个关键词，
    用它会推错（该层既有"打底袜"也有"美腿袜"）。"""

    assert hosiery_height_for(["女装", "打底裤类目", "中筒袜"]) == "中筒"
    # 末级没有筒高关键词 → None，即使上级含"打底"
    assert hosiery_height_for(["女装", "打底袜", "其他"]) is None


@pytest.mark.parametrize("hint,expected", [
    ("* 适用季节 重要 平台推荐值：春季", "春季"),
    ("适用场景 平台推荐值：篮球", "篮球"),
    ("* 风格 重要", None),
    ("", None),
])
def test_platform_recommendation_is_preferred_source(hint, expected):
    """平台自己给的推荐值优先——比我们编的更稳妥。"""

    assert platform_recommendation(hint) == expected


@pytest.mark.parametrize("name,options,prefer,expected", [
    ("适用季节", ["春季", "夏季", "秋季", "冬季", "四季通用"], None, "四季通用"),
    ("适用性别", ["男女通用", "男", "女", "情侣"], None, "男女通用"),
    ("适用年龄", ["儿童", "婴幼儿", "成人"], None, "成人"),
    ("风格", ["中国风", "其他", "卡通"], None, "其他"),
    ("适用季节", ["春季", "夏季"], "春季", "春季"),
    # 适用场景：实测长筒袜类目（2026-10-08，catId=201581801）候选全是运动场景，
    # 唯一不含具体运动卖点的「全天候穿戴」应命中；候选里没有它就返回 None（不编）。
    ("适用场景", ["全天候穿戴", "篮球", "跑步"], None, "全天候穿戴"),
    ("适用场景", ["篮球", "跑步"], None, None),
    # 候选里没有稳妥值 → None（不编）
    ("风格", ["中国风", "卡通"], None, None),
    ("未知字段", ["甲", "乙"], None, None),
    ("适用季节", [], None, None),
])
def test_safe_default_stays_inside_platform_options(name, options, prefer, expected):
    """稳妥值**必须落在平台候选内**；落不进去就先不用它，退回稳妥值或 None。"""

    assert safe_default_for(name, options, prefer=prefer) == expected


def test_category_specific_override_beats_global_default():
    """同一个属性名在不同类目下稳妥值不同——**类目专属覆盖**必须生效。

    实测场景：袜子类目「适用年龄」取 `成人` 是对的；但童袜类目下同一属性
    取 `成人` 就错了，应取 `儿童`。所以稳妥值不能全局写死一个。
    """

    options = ["儿童", "婴幼儿", "成人"]
    assert safe_default_for("适用年龄", options) == "成人"
    assert safe_default_for("适用年龄", options, category_leaf_name="中筒袜") == "成人"
    assert safe_default_for("适用年龄", options, category_leaf_name="童袜") == "儿童"
    assert safe_default_for("适用年龄", options, category_leaf_name="儿童短袜") == "儿童"


def test_plan_uses_category_path_for_override():
    """处置计划要把类目带进去，覆盖才生效。"""

    plan = plan_required_defaults([
        {"name": "适用年龄", "required": True, "selectDisplays": ["请选择"],
         "options": ["儿童", "婴幼儿", "成人"], "hint": "* 适用年龄",
         "category_path": ["袜子", "童袜"]},
    ])
    assert plan[0]["value"] == "儿童"


def test_platform_recommendation_outside_options_falls_back_to_safe_default():
    """平台推荐值不在候选里时不硬用，**退回稳妥值**（比留空好）；
    两者都没有才返回 None。"""

    assert safe_default_for("适用季节", ["春季", "夏季"], prefer="冬季") == "春季"
    assert safe_default_for("风格", ["中国风", "卡通"], prefer="其他") is None


@pytest.mark.parametrize("options,expected", [
    (["2026年冬季", "2026年秋季", "2020年春季"], "2026年冬季"),
    (["2025年冬季", "2026年春季"], "2026年春季"),
    (["春季", "夏季"], None),
    ([], None),
])
def test_most_recent_option_for_listing_label(options, expected):
    """上市年份季节取**最新一期**；没有年份可判就返回 None。"""

    assert most_recent_option(options) == expected


def test_plan_marks_product_facts_as_needing_human():
    """`面料` 这种**商品事实**必须留给人——本层不许猜。"""

    plan = plan_required_defaults([
        {"name": "面料", "required": True, "selectDisplays": ["请选择"],
         "options": ["棉", "涤纶"], "hint": "面料"},
    ])
    assert plan == [{"name": "面料", "action": "needs_human", "value": None,
                     "reason": "没有稳妥通用值，必须由人或商品数据决定"}]


def test_plan_fills_only_the_low_risk_fields():
    plan = plan_required_defaults([
        {"name": "品牌", "required": True, "selectDisplays": ["无品牌"], "hint": "品牌"},
        {"name": "适用季节", "required": True, "selectDisplays": ["请选择"],
         "options": ["春季", "夏季", "秋季", "冬季", "四季通用"],
         "hint": "* 适用季节 平台推荐值：春季"},
        {"name": "适用性别", "required": True, "selectDisplays": ["请选择"],
         "options": ["男女通用", "男", "女", "情侣"], "hint": "* 适用性别"},
        {"name": "上市年份季节", "required": True, "selectDisplays": ["请选择"],
         "options": ["2026年冬季", "2026年春季"], "hint": "* 上市年份季节"},
        {"name": "风格", "required": True, "selectDisplays": ["请选择"],
         "options": ["中国风", "其他"], "hint": "* 风格"},
        # 非必填项不参与
        {"name": "产地", "required": False, "selectDisplays": ["请选择"],
         "options": ["中国"], "hint": "产地"},
    ])
    by_name = {item["name"]: item for item in plan}
    assert by_name["品牌"]["action"] == "already"
    assert by_name["适用季节"] == {"name": "适用季节", "action": "fill", "value": "春季",
                                   "reason": "平台推荐值"}
    assert by_name["适用性别"]["value"] == "男女通用"
    assert by_name["上市年份季节"]["value"] == "2026年冬季"
    assert by_name["风格"]["value"] == "其他"
    assert "产地" not in by_name, "非必填项不该出现在处置计划里"

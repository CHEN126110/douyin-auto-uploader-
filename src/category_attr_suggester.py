# -*- coding: utf-8 -*-
"""类目属性补全引擎（L3）

基于人货场画像(L1 PgsProfile)，对抖店袜子类目的真实属性字段给出**建议值 + 候选别名 +
完整度评分 + 缺失报告**。属性完整度直接影响搜索召回与推荐打标，是流量核心之一。

真实属性字段来源：调试浏览器实测发布页"类目属性"区（不臆造）：
  必填：适用性别 / 筒高 / 面料材质 / 品牌
  选填(流量相关)：厚度 / 图案 / 功能 / 适用季节 / 风格 / 服饰工艺 / 产地 / 里料材质…

设计原则：
- 只对画像有据的属性给建议；无据则标缺失，不编造（材质成分百分比等需真实证据，不臆造）。
- L3 产出"建议值 + 候选别名列表"；到抖店真实下拉选项的精确匹配由 L4 集成时
  运行时读取选项做模糊匹配（自适应类目变化），故本层别名列表力求覆盖常见写法。
- 品牌统一建议"无品牌"（项目无品牌政策），实际写入仍由现有发布安全门处理。
- 不调用外部 AI，符合 external_ai_policy。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .people_goods_scene import PgsProfile, build_profile


# L1 画像值 -> 抖店真实选项候选别名（基于实测选项）。L4 用候选做模糊匹配。
ATTR_VALUE_ALIASES: Dict[str, Dict[str, List[str]]] = {
    "筒高": {
        "船袜": ["船袜", "船底袜", "隐形袜", "浅口袜"],
        "短袜": ["短筒袜", "短袜", "低筒袜"],
        "中筒袜": ["中筒袜", "中筒"],
        "长筒袜": ["长筒袜", "长筒", "小腿袜"],
        "过膝袜": ["过膝袜", "及膝袜", "大腿袜"],
    },
    "厚度": {
        "加厚": ["厚款", "加厚", "加绒"],
        "薄款": ["薄款", "超薄"],
        "_default": ["常规款", "常规"],
    },
    "图案": {
        "纯色": ["纯色", "净色", "素色"],
        "条纹": ["条纹"],
        "卡通": ["卡通动漫", "卡通", "动物"],
        "格子": ["几何", "格子", "格纹"],
    },
    "适用性别": {
        "男": ["男", "男士"],
        "女": ["女", "女士"],
        "中性": ["通用", "男女通用", "中性"],
        "儿童": ["儿童", "通用"],
    },
    "适用季节": {
        "夏季": ["夏", "夏季"],
        "冬季": ["冬", "冬季"],
        "春秋": ["春秋", "四季", "春", "秋"],
    },
    "功能": {  # 多选
        "抗菌防臭": ["抗菌防臭", "防臭", "抗菌"],
        "吸汗速干": ["吸汗速干", "吸湿排汗", "速干"],
        "保暖加厚": ["保暖", "加厚保暖"],
        "透气": ["透气"],
        "无骨缝合": ["无骨", "无缝"],
        "防滑": ["防滑", "防掉跟"],
    },
    "面料材质": {  # 仅建议材质类型，成分百分比需真实证据，不臆造
        "纯棉": ["棉", "纯棉"],
        "精梳棉": ["棉", "精梳棉"],
        "竹纤维": ["竹纤维"],
        "羊毛": ["羊毛", "毛"],
        "冰丝": ["锦纶", "聚酰胺纤维", "冰丝"],
        "莫代尔": ["莫代尔"],
        "珊瑚绒": ["聚酯纤维", "珊瑚绒"],
    },
}

# 主人群 -> 风格候选
_PERSONA_STYLE = {
    "男士商务通勤": ["商务", "通勤", "基础"],
    "女士日常": ["简约", "基础", "日常"],
    "学生少女": ["学院", "甜美", "ins"],
    "运动健身": ["运动", "运动风"],
    "儿童": ["可爱", "卡通"],
    "中老年": ["基础", "简约"],
    "送礼家庭装": ["基础", "简约"],
}


@dataclass
class AttrSuggestion:
    field: str
    value: Optional[str]              # 首选建议值(L1 画像词)
    candidates: List[str]            # 抖店选项候选别名(供 L4 模糊匹配)
    confidence: float                # 0-1
    required: bool
    evidence: List[str] = field(default_factory=list)
    multi: bool = False
    note: str = ""


@dataclass
class AttrCompleteness:
    required_total: int
    required_filled: int
    optional_total: int
    optional_filled: int
    score: float                     # 0-1，必填权重更高
    missing_required: List[str] = field(default_factory=list)
    missing_high_value: List[str] = field(default_factory=list)


# 字段定义：(字段名, 必填, 多选, 高价值选填)
_FIELD_SPEC = [
    ("适用性别", True, False, True),
    ("筒高", True, False, True),
    ("面料材质", True, False, True),
    ("品牌", True, False, False),
    ("适用季节", False, False, True),
    ("功能", False, True, True),
    ("厚度", False, False, True),
    ("图案", False, False, False),
    ("风格", False, False, False),
]


def _alias_candidates(field_name: str, l1_value: str) -> List[str]:
    table = ATTR_VALUE_ALIASES.get(field_name, {})
    return table.get(l1_value, [l1_value] if l1_value else [])


def _suggest_one(field_name: str, profile: PgsProfile, required: bool, multi: bool) -> AttrSuggestion:
    goods = profile.goods

    # 品牌：政策默认无品牌
    if field_name == "品牌":
        return AttrSuggestion(field=field_name, value="无品牌", candidates=["无品牌"],
                              confidence=1.0, required=required, evidence=["无品牌政策"],
                              note="由发布安全门确认")

    # 适用性别
    if field_name == "适用性别":
        gender = profile.attribute_suggestions.get("适用性别", "")
        if not gender and profile.primary_persona:
            gender = "中性"
        if gender:
            return AttrSuggestion(field=field_name, value=gender,
                                  candidates=_alias_candidates("适用性别", gender),
                                  confidence=0.9 if gender in ("男", "女", "儿童") else 0.6,
                                  required=required, evidence=profile.evidence.get("适用性别", []))
        return AttrSuggestion(field=field_name, value=None, candidates=[], confidence=0.0, required=required)

    # 适用季节
    if field_name == "适用季节":
        season = profile.season
        if season:
            conf = 0.9 if any(season in str(v) for v in profile.evidence.get("适用季节", [])) else 0.6
            return AttrSuggestion(field=field_name, value=season,
                                  candidates=_alias_candidates("适用季节", season),
                                  confidence=conf, required=required,
                                  evidence=profile.evidence.get("适用季节", ["季节推断"]))
        return AttrSuggestion(field=field_name, value=None, candidates=[], confidence=0.0, required=required)

    # 风格：从主人群推
    if field_name == "风格":
        styles = _PERSONA_STYLE.get(profile.primary_persona or "", [])
        if styles:
            return AttrSuggestion(field=field_name, value=styles[0], candidates=styles,
                                  confidence=0.6, required=required,
                                  evidence=[profile.primary_persona or ""])
        return AttrSuggestion(field=field_name, value=None, candidates=[], confidence=0.0, required=required)

    # 货属性映射（筒高/面料材质/厚度/图案/功能）
    source_attr = {
        "筒高": "袜筒高度",
        "面料材质": "材质成分",
        "厚度": "厚薄",
        "图案": "图案款式",
        "功能": "功能",
    }.get(field_name)

    if source_attr:
        values = goods.get(source_attr, [])
        if values:
            if multi:
                cands: List[str] = []
                for v in values:
                    cands.extend(_alias_candidates(field_name, v))
                note = "材质成分百分比需真实证据，此处仅建议材质类型" if field_name == "面料材质" else ""
                return AttrSuggestion(field=field_name, value=values[0], candidates=_dedup(cands),
                                      confidence=0.85, required=required, evidence=values,
                                      multi=True, note=note)
            first = values[0]
            note = "材质成分百分比需真实证据，此处仅建议材质类型" if field_name == "面料材质" else ""
            return AttrSuggestion(field=field_name, value=first,
                                  candidates=_alias_candidates(field_name, first),
                                  confidence=0.85, required=required, evidence=values, note=note)
        # 厚度无信号时给常规款兜底（低置信）
        if field_name == "厚度":
            return AttrSuggestion(field=field_name, value="常规", candidates=["常规款", "常规"],
                                  confidence=0.4, required=required, evidence=["默认"],
                                  note="无厚薄信号，默认常规款（建议人工确认）")
        return AttrSuggestion(field=field_name, value=None, candidates=[], confidence=0.0, required=required)

    return AttrSuggestion(field=field_name, value=None, candidates=[], confidence=0.0, required=required)


def suggest_category_attributes(
    name: str = "",
    remark: str = "",
    content: str = "",
    sku_colors=None,
    month: Optional[int] = None,
    profile: Optional[PgsProfile] = None,
) -> Dict[str, object]:
    """对袜子类目属性给出建议 + 完整度评分 + 缺失报告。"""
    if profile is None:
        profile = build_profile(name, remark, content, sku_colors, month)

    suggestions: Dict[str, AttrSuggestion] = {}
    req_total = req_filled = opt_total = opt_filled = 0
    missing_required: List[str] = []
    missing_high_value: List[str] = []

    for field_name, required, multi, high_value in _FIELD_SPEC:
        s = _suggest_one(field_name, profile, required, multi)
        suggestions[field_name] = s
        filled = bool(s.value) and s.confidence > 0
        if required:
            req_total += 1
            if filled:
                req_filled += 1
            else:
                missing_required.append(field_name)
        else:
            opt_total += 1
            if filled:
                opt_filled += 1
            elif high_value:
                missing_high_value.append(field_name)

    req_ratio = (req_filled / req_total) if req_total else 1.0
    opt_ratio = (opt_filled / opt_total) if opt_total else 1.0
    score = round(req_ratio * 0.7 + opt_ratio * 0.3, 3)

    completeness = AttrCompleteness(
        required_total=req_total, required_filled=req_filled,
        optional_total=opt_total, optional_filled=opt_filled, score=score,
        missing_required=missing_required, missing_high_value=missing_high_value,
    )

    return {
        "suggestions": {k: _suggestion_to_dict(v) for k, v in suggestions.items()},
        "completeness": _completeness_to_dict(completeness),
        "primary_persona": profile.primary_persona,
        "season": profile.season,
    }


def _suggestion_to_dict(s: AttrSuggestion) -> Dict[str, object]:
    return {
        "field": s.field, "value": s.value, "candidates": s.candidates,
        "confidence": s.confidence, "required": s.required,
        "evidence": s.evidence, "multi": s.multi, "note": s.note,
    }


def _completeness_to_dict(c: AttrCompleteness) -> Dict[str, object]:
    return {
        "required_total": c.required_total, "required_filled": c.required_filled,
        "optional_total": c.optional_total, "optional_filled": c.optional_filled,
        "score": c.score, "missing_required": c.missing_required,
        "missing_high_value": c.missing_high_value,
    }


def _dedup(items) -> List[str]:
    seen = set(); out = []
    for it in items:
        it = (it or "").strip()
        if it and it not in seen:
            seen.add(it); out.append(it)
    return out

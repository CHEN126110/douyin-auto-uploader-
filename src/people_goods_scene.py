# -*- coding: utf-8 -*-
"""人货场建模引擎（People-Goods-Scene, PGS）

从商品信息构建"人(目标人群) / 货(差异卖点) / 场(消费场景与季节)"三维画像，
作为标题引擎(L2)、类目属性补全(L3)的统一输入。

设计约束：
- 不调用任何外部 AI / LLM（遵守 src/config.py external_ai_policy）。
- "智能"来自本地领域知识库 + 规则提取 + 采集数据增量，不臆造商品事实
  （材质成分、克重等需真实证据的字段不在此处编造，只识别文本中已出现的信号）。

数据来源分层：
1. 固化领域知识库：袜子品类的人群/卖点/场景/季节常识（本文件常量）。
2. 商品自身文本：name / remark / content / sku 颜色（规则提取）。
3. 采集竞品数据增量：后续从 Record 库挖词丰富（见 merge_corpus_keywords）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Sequence


# ---------------------------------------------------------------------------
# 货：袜子硬属性识别词典（值 -> 触发该值的文本信号）
# 仅识别文本里"已出现"的信号，不臆造。顺序内靠前的为更具体的写法。
# ---------------------------------------------------------------------------
GOODS_ATTRIBUTE_SIGNALS: Dict[str, Dict[str, List[str]]] = {
    "袜筒高度": {
        "船袜": ["船袜", "隐形袜", "浅口", "浅口袜", "船型"],
        "船袜短袜": ["低帮"],
        "短袜": ["短袜", "短筒"],
        "中筒袜": ["中筒"],
        "长筒袜": ["长筒", "及膝", "小腿袜"],
        "过膝袜": ["过膝", "大腿袜", "过膝袜"],
    },
    "材质成分": {
        "精梳棉": ["精梳棉"],
        "纯棉": ["纯棉", "全棉", "棉袜"],
        "竹纤维": ["竹纤维", "竹炭"],
        "羊毛": ["羊毛", "美利奴", "羊绒"],
        "冰丝": ["冰丝", "凉感", "凉皮"],
        "莫代尔": ["莫代尔"],
        "珊瑚绒": ["珊瑚绒", "加绒", "毛圈"],
    },
    "功能": {
        "抗菌防臭": ["防臭", "抗菌", "除臭", "银离子"],
        "吸汗速干": ["吸汗", "速干", "排汗", "干爽"],
        "保暖加厚": ["保暖", "加厚", "加绒", "毛圈", "厚款"],
        "透气": ["透气", "网眼", "薄款", "凉爽"],
        "无骨缝合": ["无骨", "无缝", "无勒痕"],
        "防滑": ["防滑", "硅胶", "防掉跟", "不掉跟"],
    },
    "图案款式": {
        "纯色": ["纯色", "净色", "素色", "基础款"],
        "条纹": ["条纹", "杠"],
        "卡通": ["卡通", "ins", "可爱", "动漫"],
        "格子": ["格子", "格纹"],
    },
    "厚薄": {
        "加厚": ["加厚", "厚款", "加绒", "毛圈"],
        "薄款": ["薄款", "超薄", "夏季薄"],
    },
}

# 数量装识别（影响"性价比/家庭装"卖点）
_QUANTITY_PATTERN = re.compile(r"(\d+)\s*(双|对)")


# ---------------------------------------------------------------------------
# 人：目标人群知识库
# signals: 文本命中信号；search_terms: 该人群真实搜索习惯词；
# pains: 痛点；prefer_points: 该人群偏好的货卖点(对应 GOODS 功能/材质)。
# ---------------------------------------------------------------------------
@dataclass
class Persona:
    key: str
    gender: str  # 男 / 女 / 中性 / 儿童
    signals: List[str]
    search_terms: List[str]
    pains: List[str]
    prefer_points: List[str]
    weight: float = 1.0


PERSONAS: List[Persona] = [
    Persona(
        key="男士商务通勤", gender="男",
        signals=["男", "男士", "商务", "正装", "西装", "绅士"],
        search_terms=["男士袜子", "商务袜", "男士中筒袜", "男袜纯棉"],
        pains=["脚臭", "出汗", "易破", "起球"],
        prefer_points=["抗菌防臭", "吸汗速干", "纯棉", "精梳棉"],
        weight=1.2,
    ),
    Persona(
        key="女士日常", gender="女",
        signals=["女", "女士", "女款"],
        search_terms=["女袜", "女士袜子", "女生袜子", "纯棉女袜"],
        pains=["磨脚", "勒腿", "掉跟"],
        prefer_points=["无骨缝合", "防滑", "透气", "纯棉"],
        weight=1.1,
    ),
    Persona(
        key="学生少女", gender="女",
        signals=["jk", "少女", "学生", "学院", "可爱", "ins"],
        search_terms=["jk袜", "少女袜", "学生袜", "ins袜子", "中筒袜女"],
        pains=["不百搭", "易脏"],
        prefer_points=["透气", "纯色", "卡通"],
        weight=1.0,
    ),
    Persona(
        key="运动健身", gender="中性",
        signals=["运动", "跑步", "篮球", "健身", "瑜伽", "户外"],
        search_terms=["运动袜", "跑步袜", "篮球袜", "毛巾底运动袜"],
        pains=["出汗", "磨脚", "掉跟", "起水泡"],
        prefer_points=["吸汗速干", "防滑", "无骨缝合", "透气"],
        weight=1.1,
    ),
    Persona(
        key="儿童", gender="儿童",
        signals=["儿童", "宝宝", "婴儿", "小孩", "中大童", "童袜"],
        search_terms=["儿童袜", "宝宝袜", "童袜纯棉", "婴儿袜"],
        pains=["勒腿", "起球", "不透气"],
        prefer_points=["无骨缝合", "纯棉", "透气"],
        weight=1.0,
    ),
    Persona(
        key="中老年", gender="中性",
        signals=["中老年", "老人", "爸爸", "妈妈", "宽口"],
        search_terms=["中老年袜子", "老人袜", "宽口袜", "无勒痕袜"],
        pains=["勒腿", "脚肿", "脚凉"],
        prefer_points=["无骨缝合", "保暖加厚", "纯棉"],
        weight=0.9,
    ),
    Persona(
        key="送礼家庭装", gender="中性",
        signals=["礼盒", "送礼", "家庭装", "全家", "多双装", "组合装"],
        search_terms=["袜子礼盒", "家庭装袜子", "袜子组合", "多双装袜子"],
        pains=["买着不划算", "款式单一"],
        prefer_points=["精梳棉", "纯棉"],
        weight=0.9,
    ),
]


# ---------------------------------------------------------------------------
# 场：季节 + 消费场景知识库
# ---------------------------------------------------------------------------
SEASONS: Dict[str, Dict[str, object]] = {
    # 季节信号只保留"强季节词"——通用功能词(透气)、材质词(纯棉)、款式词(船袜/中筒)
    # 不在此处充当季节信号，避免误判；它们由"货"维度识别。
    "夏季": {
        "months": [5, 6, 7, 8],
        "keywords": ["薄款", "超薄", "冰丝", "凉感", "夏季", "夏天"],
        "avoid": ["加厚", "保暖", "羊毛", "加绒"],
    },
    "冬季": {
        "months": [11, 12, 1, 2],
        "keywords": ["加厚", "保暖", "羊毛", "加绒", "毛圈", "冬季", "冬天"],
        "avoid": ["薄款", "冰丝", "超薄"],
    },
    "春秋": {
        "months": [3, 4, 9, 10],
        "keywords": ["春秋"],
        "avoid": [],
    },
}

SCENES: Dict[str, List[str]] = {
    "通勤": ["商务", "正装", "上班", "办公", "通勤"],
    "运动": ["运动", "跑步", "健身", "篮球", "户外", "瑜伽"],
    "居家": ["居家", "地板袜", "睡眠", "月子"],
    "送礼": ["礼盒", "送礼", "节日", "情人节"],
    "日常百搭": ["日常", "百搭", "四季", "通用"],
}


# ---------------------------------------------------------------------------
# 画像数据结构
# ---------------------------------------------------------------------------
@dataclass
class PgsProfile:
    goods: Dict[str, List[str]] = field(default_factory=dict)       # 货：属性 -> 命中值列表
    quantity: Optional[int] = None                                  # 货：数量装(双)
    personas: List[str] = field(default_factory=list)               # 人：命中人群 key
    primary_persona: Optional[str] = None                           # 人：主人群
    pains: List[str] = field(default_factory=list)                  # 人：痛点
    season: Optional[str] = None                                    # 场：季节
    scenes: List[str] = field(default_factory=list)                 # 场：消费场景
    keyword_pool: Dict[str, List[str]] = field(default_factory=dict)  # 人/货/场 分组关键词
    attribute_suggestions: Dict[str, str] = field(default_factory=dict)  # 给 L3 的属性建议
    evidence: Dict[str, List[str]] = field(default_factory=dict)    # 每项结论的文本依据

    def to_dict(self) -> Dict[str, object]:
        return {
            "goods": self.goods,
            "quantity": self.quantity,
            "personas": self.personas,
            "primary_persona": self.primary_persona,
            "pains": self.pains,
            "season": self.season,
            "scenes": self.scenes,
            "keyword_pool": self.keyword_pool,
            "attribute_suggestions": self.attribute_suggestions,
            "evidence": self.evidence,
        }


# ---------------------------------------------------------------------------
# 提取：货
# ---------------------------------------------------------------------------
def extract_goods_features(text: str) -> Dict[str, List[str]]:
    """从商品文本提取袜子硬属性（仅识别已出现的信号，不臆造）。"""
    text = text or ""
    features: Dict[str, List[str]] = {}
    for attr, value_signals in GOODS_ATTRIBUTE_SIGNALS.items():
        hits: List[str] = []
        for value, signals in value_signals.items():
            if any(sig in text for sig in signals):
                # 归一：船袜短袜/船袜 合并到更具体的已命中值，避免重复污染
                normalized = value.replace("船袜短袜", "船袜")
                if normalized not in hits:
                    hits.append(normalized)
        if hits:
            features[attr] = hits
    return features


def extract_quantity(text: str) -> Optional[int]:
    """提取"N双装"。取文本中出现的最大合理数量(<=50)。"""
    text = text or ""
    nums = [int(m.group(1)) for m in _QUANTITY_PATTERN.finditer(text)]
    nums = [n for n in nums if 1 <= n <= 50]
    return max(nums) if nums else None


# ---------------------------------------------------------------------------
# 推断：人
# ---------------------------------------------------------------------------
def infer_personas(text: str, sku_colors: Optional[Sequence[str]] = None) -> List[Persona]:
    """按信号命中 + 权重排序，返回命中的人群（可能多个）。"""
    text = text or ""
    scored: List[tuple] = []
    for p in PERSONAS:
        hit = sum(1 for sig in p.signals if sig in text)
        if hit:
            scored.append((hit * p.weight, p))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [p for _, p in scored]


# ---------------------------------------------------------------------------
# 推断：场
# ---------------------------------------------------------------------------
def infer_season(text: str, month: Optional[int] = None) -> Optional[str]:
    """优先用文本里的季节信号；否则用当前月份兜底。"""
    text = text or ""
    # 文本显式信号优先
    for season, info in SEASONS.items():
        if any(kw in text for kw in info["keywords"]):  # type: ignore[index]
            return season
    # 月份兜底
    m = month if month is not None else datetime.now().month
    for season, info in SEASONS.items():
        if m in info["months"]:  # type: ignore[index]
            return season
    return None


def infer_scenes(text: str) -> List[str]:
    text = text or ""
    out: List[str] = []
    for scene, signals in SCENES.items():
        if any(sig in text for sig in signals):
            out.append(scene)
    return out


# ---------------------------------------------------------------------------
# 整合：build_profile
# ---------------------------------------------------------------------------
def build_profile(
    name: str,
    remark: str = "",
    content: str = "",
    sku_colors: Optional[Sequence[str]] = None,
    month: Optional[int] = None,
    extra_keywords: Optional[Sequence[str]] = None,
) -> PgsProfile:
    """构建人货场画像。extra_keywords 预留给采集数据增量挖词(L1.2)。"""
    text = " ".join(filter(None, [name or "", remark or "", content or ""]))
    if sku_colors:
        text += " " + " ".join(str(c) for c in sku_colors)

    profile = PgsProfile()

    # 货
    profile.goods = extract_goods_features(text)
    profile.quantity = extract_quantity(text)

    # 人
    personas = infer_personas(text, sku_colors)
    profile.personas = [p.key for p in personas]
    profile.primary_persona = personas[0].key if personas else None
    profile.pains = personas[0].pains if personas else []

    # 场
    profile.season = infer_season(text, month)
    profile.scenes = infer_scenes(text)

    # 关键词池（人 / 货 / 场 三组，去重）
    people_kw: List[str] = []
    for p in personas[:2]:
        people_kw.extend(p.search_terms)
    goods_kw: List[str] = []
    for values in profile.goods.values():
        goods_kw.extend(values)
    scene_kw: List[str] = []
    if profile.season:
        scene_kw.extend(
            [k for k in SEASONS[profile.season]["keywords"] if not k.endswith("季")]  # type: ignore[index]
        )
    scene_kw.extend(profile.scenes)
    if extra_keywords:
        goods_kw.extend([k for k in extra_keywords if k])

    profile.keyword_pool = {
        "人": _dedup(people_kw),
        "货": _dedup(goods_kw),
        "场": _dedup(scene_kw),
    }

    # 给 L3 的属性建议（仅高置信、文本有据的；每属性取首个命中值）
    suggestions: Dict[str, str] = {}
    evidence: Dict[str, List[str]] = {}
    for attr, values in profile.goods.items():
        suggestions[attr] = values[0]
        evidence[attr] = values
    if personas:
        gender = personas[0].gender
        if gender in ("男", "女", "儿童"):
            suggestions["适用性别"] = gender
            evidence["适用性别"] = [personas[0].key]
    if profile.season:
        suggestions["适用季节"] = profile.season
        evidence["适用季节"] = ["季节推断"]
    profile.attribute_suggestions = suggestions
    profile.evidence = evidence

    return profile


def _dedup(items: Sequence[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for it in items:
        it = (it or "").strip()
        if it and it not in seen:
            seen.add(it)
            out.append(it)
    return out

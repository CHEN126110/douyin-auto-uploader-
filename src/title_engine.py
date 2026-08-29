# -*- coding: utf-8 -*-
"""标题引擎（L2）

基于人货场画像(L1 PgsProfile)结构化合成商品标题候选，并按"人货场匹配度 + 流量友好度"
评分排序。核心原则与旧版相反——**反关键词堆砌**：

- 旧版：把 20+ 个营销词塞满 60 字（"爆款…透气舒适防臭吸汗运动休闲居家办公…包邮特价限时
  热销新品优质精选高档四季"），抖店搜索判低质，反而压流量。
- 新版：按"人(人群词) → 货(袜筒+材质+核心功能) → 场(季节/场景)"结构化组词，每类卖点限量，
  控制长度与密度，让标题精准锚定人群与需求。

合规：复用 professional_title_generator 的无品牌/违禁词审计，不重造。
不调用外部 AI，符合 external_ai_policy。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

from .people_goods_scene import PgsProfile, build_profile
from .professional_title_generator import (
    audit_no_brand_title_text,
    sanitize_no_brand_title_text,
)

# 抖店商品标题字数上限：不同类目可能不同，需按实际校准。
# 项目旧代码曾用 60；这里参数化，默认 30（服饰类常见上限），由调用方按真实上限覆盖。
DEFAULT_TITLE_MAX_CHARS = 30
# 标题过短下限（低于此长度信息量不足）
MIN_REASONABLE_CHARS = 10

# 性别 -> 标题人群词（兜底）
_GENDER_TITLE_TERM = {"男": "男士", "女": "女士", "儿童": "儿童", "中性": ""}

# 人群 -> 标题核心锚点词：流量命脉。运动袜必须含"运动"、jk 袜含"少女"等，
# 否则对应人群搜索时召回不到。优先于性别兜底。
_PERSONA_TITLE_ANCHOR = {
    "男士商务通勤": "男士",
    "女士日常": "女士",
    "学生少女": "少女",
    "运动健身": "运动",
    "儿童": "儿童",
    "中老年": "中老年",
    "送礼家庭装": "",  # 家庭装/礼盒属货特征，由数量装等体现，不强加人群词
}

# 极限词/违禁词（抖店禁用的绝对化用语，命中则降权或清除）；与品牌词审计互补
BANNED_SUPERLATIVES = [
    "爆款", "热销", "限时", "特价", "秒杀", "第一", "最", "顶级", "国家级",
    "全网", "包邮", "新品", "精选", "高档", "超值",
]


@dataclass
class TitleCandidate:
    title: str
    score: float
    char_count: int
    coverage: Dict[str, List[str]] = field(default_factory=dict)  # 人/货/场 覆盖到的词
    missing: List[str] = field(default_factory=list)              # 缺失的高价值维度
    notes: List[str] = field(default_factory=list)                # 评分说明
    source: str = "本地"                                          # 来源：本地 / LLM

    def to_dict(self) -> Dict[str, object]:
        return {
            "title": self.title,
            "score": round(self.score, 3),
            "char_count": self.char_count,
            "coverage": self.coverage,
            "missing": self.missing,
            "notes": self.notes,
            "source": self.source,
        }


def _persona_title_term(profile: PgsProfile) -> str:
    # 优先用主人群的核心锚点词（运动/少女/男士…），兜底用性别词
    anchor = _PERSONA_TITLE_ANCHOR.get(profile.primary_persona or "", None)
    if anchor:
        return anchor
    if anchor == "":  # 显式定义为无锚点(如送礼家庭装)，不再退回性别
        return ""
    gender = profile.attribute_suggestions.get("适用性别", "")
    return _GENDER_TITLE_TERM.get(gender, "")


def _season_title_term(profile: PgsProfile) -> str:
    if not profile.season:
        return ""
    # "春秋" 直接用；"夏季/冬季" 标题里更自然的写法
    return {"夏季": "夏季", "冬季": "冬季", "春秋": "春秋"}.get(profile.season, "")


def _compose_variants(profile: PgsProfile, max_chars: int) -> List[List[str]]:
    """生成若干"词组件序列"候选（人→货→场→款式/数量）。每类卖点限量，防堆砌。"""
    persona = _persona_title_term(profile)
    goods = profile.goods
    cylinder = (goods.get("袜筒高度") or [""])[0]
    material = (goods.get("材质成分") or [""])[0]
    functions = goods.get("功能") or []
    pattern = (goods.get("图案款式") or [""])[0]
    season = _season_title_term(profile)
    scene = profile.scenes[0] if profile.scenes else ""
    qty = f"{profile.quantity}双装" if profile.quantity else ""

    variants: List[List[str]] = []

    # 变体1：标准结构，单功能词
    variants.append([persona, cylinder, material, functions[0] if functions else "", season, scene])
    # 变体2：双功能词，省略场景，强调货差异
    variants.append([persona, cylinder, material, *(functions[:2]), season])
    # 变体3：人群+场景导向（搜索"人群+场景"习惯）
    variants.append([persona, season, scene, cylinder, functions[0] if functions else "", material])
    # 变体4：含款式/数量（性价比/款式人群）
    variants.append([persona, cylinder, material, functions[0] if functions else "", pattern, qty])
    # 变体5：精简强锚（人群+核心货+季节）
    variants.append([persona, material, cylinder, season])

    return variants


def _assemble(components: Sequence[str], max_chars: int) -> str:
    """组件去重拼接，超长则按优先级（靠前优先）截断。"""
    seen = set()
    parts: List[str] = []
    for c in components:
        c = (c or "").strip()
        if not c or c in seen:
            continue
        seen.add(c)
        parts.append(c)
    title = "".join(parts)
    if len(title) <= max_chars:
        return title
    # 超长：逐个回退末尾组件直到不超限
    while parts and len("".join(parts)) > max_chars:
        parts.pop()
    return "".join(parts)


def _score_title(title: str, profile: PgsProfile, max_chars: int) -> TitleCandidate:
    char_count = len(title)
    coverage: Dict[str, List[str]] = {"人": [], "货": [], "场": []}
    notes: List[str] = []
    score = 0.0

    # 人：含人群词 / 主人群搜索词成分
    persona_term = _persona_title_term(profile)
    if persona_term and persona_term in title:
        coverage["人"].append(persona_term)
        score += 2.0
    # 货：不同类别卖点各计分，边际递减（防堆砌）
    goods_hits = 0
    for attr, values in profile.goods.items():
        for v in values:
            if v and v in title:
                coverage["货"].append(v)
                goods_hits += 1
                break  # 每类只计一次，鼓励"多类别"而非"同类堆砌"
    # 边际递减：第1个+1.5，第2个+1.0，第3个+0.6，之后+0.3
    marginal = [1.5, 1.0, 0.6]
    for i in range(goods_hits):
        score += marginal[i] if i < len(marginal) else 0.3
    # 场：季节/场景
    season_term = _season_title_term(profile)
    if season_term and season_term in title:
        coverage["场"].append(season_term)
        score += 1.0
    for scene in profile.scenes:
        if scene in title:
            coverage["场"].append(scene)
            score += 0.6
            break

    # 长度利用率：贴近上限但不超最好
    if char_count > max_chars:
        score -= 3.0
        notes.append(f"超出上限{max_chars}字")
    elif char_count < MIN_REASONABLE_CHARS:
        score -= 1.5
        notes.append("标题过短，信息量不足")
    else:
        # 利用率 0.5~1.0 区间给正分
        util = char_count / max_chars
        score += min(util, 1.0) * 1.0

    # 堆砌惩罚：极限词/违禁词
    banned_hits = [w for w in BANNED_SUPERLATIVES if w in title]
    if banned_hits:
        score -= 1.0 * len(banned_hits)
        notes.append(f"含违禁/极限词:{','.join(banned_hits)}")

    # 重复字惩罚（粗略：字符去重率过低）
    if char_count:
        uniq_ratio = len(set(title)) / char_count
        if uniq_ratio < 0.6:
            score -= 1.0
            notes.append("用词重复度高")

    # 缺失维度提示
    missing: List[str] = []
    if not coverage["人"]:
        missing.append("人群锚点")
    if len(coverage["货"]) < 2:
        missing.append("货差异卖点不足(建议≥2类)")
    if not coverage["场"]:
        missing.append("场景/季节词")

    return TitleCandidate(
        title=title,
        score=score,
        char_count=char_count,
        coverage=coverage,
        missing=missing,
        notes=notes,
    )


def _llm_generate_title_candidates(profile: PgsProfile, llm_client, max_chars: int, n: int = 5) -> List[str]:
    """用 LLM 基于人货场画像生成标题候选。失败返回 []（由本地候选兜底，混合模式）。"""
    kw = profile.keyword_pool or {}
    persona = profile.primary_persona or "通用人群"
    people = "、".join(kw.get("人", [])) or "无"
    goods = "、".join(kw.get("货", [])) or "无"
    scene = "、".join(kw.get("场", [])) or "无"
    system = "你是抖音电商标题优化助手，只输出标题文本，每行一个，不要序号、引号或解释。"
    prompt = (
        f"基于以下人货场信息生成 {n} 个商品标题：\n"
        f"目标人群：{persona}（搜索习惯词：{people}）\n"
        f"货品卖点：{goods}\n"
        f"场景季节：{scene}\n"
        f"硬性要求：\n"
        f"1. 每个标题不超过 {max_chars} 个汉字；\n"
        f"2. 结构为「人群词+核心卖点+场景词」，精准锚定，禁止堆砌大量近义词；\n"
        f"3. 禁止极限词（最/第一/爆款/热销/限时/包邮/特价/新品/精选/高档/超值等）；\n"
        f"4. 禁止任何品牌名、旗舰店、店铺名。"
    )
    try:
        text = llm_client.complete(prompt, system=system, max_tokens=400, temperature=0.8)
    except Exception:
        return []
    out: List[str] = []
    for line in (text or "").splitlines():
        ln = re.sub(r'^[\s\d、.)）"\'’“”-]+', "", line).strip()
        if ln:
            out.append(ln)
    return out[:n]


def generate_titles(
    name: str,
    remark: str = "",
    content: str = "",
    sku_colors: Optional[Sequence[str]] = None,
    month: Optional[int] = None,
    max_chars: int = DEFAULT_TITLE_MAX_CHARS,
    top_n: int = 5,
    profile: Optional[PgsProfile] = None,
    llm_client=None,
) -> List[TitleCandidate]:
    """生成并按人货场匹配度排序的标题候选（混合：有 llm_client 则 LLM 增强，否则纯本地兜底）。

    无论候选来自 LLM 还是本地，都统一经过无品牌/违禁词清洗 + 本地评分排序，
    保证质量与合规一致（LLM 负责自然度，本地评分负责把关）。
    """
    if profile is None:
        profile = build_profile(name, remark, content, sku_colors, month)

    # 收集原始候选：LLM（若配置可用）+ 本地结构化（始终生成，作兜底）
    raw_titles: List[tuple] = []
    if llm_client is not None:
        for t in _llm_generate_title_candidates(profile, llm_client, max_chars, n=top_n):
            raw_titles.append((t, "LLM"))
    for components in _compose_variants(profile, max_chars):
        raw = _assemble(components, max_chars)
        if raw:
            raw_titles.append((raw, "本地"))

    seen_titles = set()
    candidates: List[TitleCandidate] = []
    for raw, source in raw_titles:
        cleaned = sanitize_no_brand_title_text(raw)
        if not cleaned:
            continue
        audit = audit_no_brand_title_text(cleaned)
        if audit.get("has_risk"):
            cleaned = audit.get("sanitized_title") or cleaned
        cleaned = cleaned.strip()
        if not cleaned or cleaned in seen_titles:
            continue
        seen_titles.add(cleaned)
        cand = _score_title(cleaned, profile, max_chars)
        cand.source = source
        candidates.append(cand)

    candidates.sort(key=lambda c: c.score, reverse=True)
    return candidates[:top_n]

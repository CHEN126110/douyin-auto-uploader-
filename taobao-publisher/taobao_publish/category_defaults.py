# -*- coding: utf-8 -*-
"""类目驱动的取值规则：把"必填项"按**类目**推导出稳妥通用的值。

## 为什么要有这一层（用户提出的设计）

「SKU 部分中的筒高可以跟随类目选择来填写」——这句话点出一个通用原则：
**能从类目推出来的字段，就跟着类目走**，不要每个商品手填。袜子类目尤其明显：

| 类目末级 | 筒高应为 |
|---|---|
| 中筒袜 | 中筒 |
| 短筒袜 / 船袜 / 隐形袜 | 短筒 |
| 长筒袜 | 长筒 |
| 过膝袜 | 过膝 |
| 连裤袜 / 打底裤 | 连裤 |

## 设计约束（沿用本子项目的红线）

1. **不猜**：只在**类目关键词能确定**时给值；判不出来就返回 ``None``，
   由调用方明确报缺，不由这里编一个默认值。
2. **只给"零商品语义"的稳妥值**：像 `四季通用`（季节）、`男女通用`（性别）、
   `其他`（风格）这类**不含具体卖点**的取值是安全的；而 `面料`、`材质成分`
   属于商品事实，**只从采集数据或人那里来**，不在本层猜。
3. **平台推荐值优先**：平台行内会写「平台推荐值：春季」——那是平台自己的建议，
   比我们编的更稳妥；解析得到就用它。
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Sequence, Tuple

#: 筒高规则：`(类目末级里的关键词, 筒高取值)`，**按顺序匹配，先命中先用**。
#:
#: 注意顺序：`中筒` 必须在 `筒` 之前，`过膝` 必须在 `长筒` 之前，否则会被更宽的关键词抢走。
HOSIERY_HEIGHT_RULES: Tuple[Tuple[str, str], ...] = (
    ("过膝", "过膝"),
    ("连裤", "连裤"),
    ("打底裤", "连裤"),
    ("中筒", "中筒"),
    ("短筒", "短筒"),
    ("船袜", "短筒"),
    ("隐形", "短筒"),
    ("长筒", "长筒"),
)

#: 零商品语义的稳妥默认值（**仅在平台候选里存在时才用**）。
SAFE_DEFAULTS: Dict[str, Tuple[str, ...]] = {
    # 季节：四季通用不含具体卖点，最不容易与实物冲突
    "适用季节": ("四季通用", "春季", "夏季", "秋季", "冬季"),
    # 性别：袜子/内衣类多为此值
    "适用性别": ("男女通用", "女", "男", "情侣"),
    # 年龄：本类目候选实测为 `儿童 / 婴幼儿 / 成人`；成人向商品取「成人」不含具体卖点。
    # （若将来做童装类目，这个默认值应当由**类目**覆盖——见 `CATEGORY_SAFE_DEFAULTS`。）
    "适用年龄": ("成人",),
    "风格": ("其他", "简约", "时尚", "休闲"),
    # 场景：实测袜子类目（长筒袜 2026-10-08，catId=201581801）的候选全是运动场景
    # （篮球/跑步/徒步登山…），唯一不含具体运动卖点的是「全天候穿戴」——
    # 相当于「适用季节→四季通用」的位置。候选里没有它时照样返回 None（不编值）。
    "适用场景": ("全天候穿戴",),
}

#: **类目专属**的稳妥默认值（优先级高于 :data:`SAFE_DEFAULTS`）。
#:
#: 为什么要有：同一个属性名在不同类目下稳妥值不同。例如「适用年龄」在袜子里
#: 取「成人」，在童装类目里就该取「儿童」——所以稳妥值需要能**按类目关键词覆盖**，
#: 而不是全局写死一个。
CATEGORY_SAFE_DEFAULTS: Tuple[Tuple[str, str, Tuple[str, ...]], ...] = (
    # (类目关键词, 属性名, 优先候选序列)
    ("童袜", "适用年龄", ("儿童", "婴幼儿", "成人")),
    ("儿童", "适用年龄", ("儿童", "婴幼儿", "成人")),
)


#: 需要"取最近一期"的字段：候选是**按当前时间生成**的标签（如 `2026年冬季`/`2026年秋季`），
#: 它们只是**上架时间标签**，不参与搜索卖点，所以"最近一期"是稳妥通用解。
#: 实测某类目候选含 `2026年冬季`、`2026年秋季`，往下还有 2017–2020 年的历史项——
#: 显然应取最新一期，而不是随手挑一个。
RECENCY_FIELDS: Tuple[str, ...] = ("上市年份季节",)

#: `2026年冬季` 这种取年份数字用
_YEAR_PATTERN = re.compile(r"(\d{4})")


def most_recent_option(options: Sequence[str]) -> Optional[str]:
    """从"年份+季节"候选里取**最新一期**；取不到年份就返回 ``None``（不编值）。"""

    best: Optional[Tuple[int, int, str]] = None
    # 季节先后：春 < 夏 < 秋 < 冬（同年内冬最晚）
    season_rank = {"春": 1, "夏": 2, "秋": 3, "冬": 4}
    for candidate in (options or ()):
        text = str(candidate).strip()
        match = _YEAR_PATTERN.search(text)
        if not match:
            continue
        year = int(match.group(1))
        rank = next((v for k, v in season_rank.items() if k in text), 0)
        key = (year, rank, text)
        if best is None or key > best:
            best = key
    return best[2] if best else None


def category_leaf(category_path: Sequence[str]) -> str:
    """取类目末级名。"""

    parts = [str(p).strip() for p in (category_path or ()) if str(p).strip()]
    return parts[-1] if parts else ""


def hosiery_height_for(category_path: Sequence[str]) -> Optional[str]:
    """从类目路径推**筒高**；推不出返回 ``None``（不编值）。

    只在**末级**里匹配关键词——上级（如「短袜/打底袜/丝袜/美腿袜（新）」这种混合层）
    含多个关键词，用它推会得出错误结论（例如该层同时含"打底袜"与"美腿袜"）。
    """

    leaf = category_leaf(category_path)
    if not leaf:
        return None
    for keyword, value in HOSIERY_HEIGHT_RULES:
        if keyword in leaf:
            return value
    # 末级推不出时，再看**整条路径**里有没有"袜"字——有袜字但推不出筒高，
    # 说明这个类目不区分筒高，返回 None 由调用方决定，**不硬给**。
    return None


def platform_recommendation(row_hint: str) -> Optional[str]:
    """从属性行提示里解析**平台推荐值**（如「平台推荐值：春季」）。

    平台自己给的建议比我们编的更稳妥，所以优先用它。
    """

    text = str(row_hint or "")
    match = re.search(r"平台推荐值[：:]\s*([^\s，,；;。]+)", text)
    return match.group(1).strip() if match else None


def safe_default_for(field_name: str, options: Sequence[str], *,
                     prefer: Optional[str] = None,
                     category_leaf_name: str = "") -> Optional[str]:
    """在**平台给定的候选**里挑一个稳妥值。

    :param prefer: 优先值（例如平台推荐值）。**必须也在候选里**才采用。
    :param category_leaf_name: 类目末级名；用于 :data:`CATEGORY_SAFE_DEFAULTS`
        的**类目专属覆盖**（如童袜类目下「适用年龄」取儿童）。
    :return: 选中值；候选为空或没有可用稳妥值时返回 ``None``（**不编值**）。
    """

    candidates = [str(o).strip() for o in (options or ()) if str(o).strip()]
    if not candidates:
        return None
    if prefer:
        wanted = str(prefer).strip()
        for candidate in candidates:
            if candidate == wanted:
                return candidate
        # 平台推荐值可能是"春季"，候选里是"2026年春季"这种带年份的形态
        for candidate in candidates:
            if wanted and wanted in candidate:
                return candidate
    # 类目专属稳妥值优先于全局稳妥值
    wanted_groups: Tuple[Tuple[str, ...], ...] = ()
    for keyword, field, values in CATEGORY_SAFE_DEFAULTS:
        if keyword and keyword in str(category_leaf_name or "") and field == str(field_name):
            wanted_groups += (values,)
    wanted_groups += (SAFE_DEFAULTS.get(str(field_name), ()),)
    for group in wanted_groups:
        for wanted in group:
            for candidate in candidates:
                if candidate == wanted:
                    return candidate
    return None


def plan_required_defaults(rows: Sequence[dict]) -> List[dict]:
    """按扫描结果给出**每个必填项的处置建议**（纯函数，便于测试与复核）。

    :param rows: `scan-category-attributes` 那种行记录，至少含
        ``name`` / ``required`` / ``selectDisplays`` / ``options`` / ``hint``。
    :return: 每项 ``{name, action, value, reason}``；``action`` 取
        ``fill``（有稳妥值可填）/ ``needs_human``（必须人来定）/ ``already``（已填）。
    """

    plan: List[dict] = []
    for row in rows or ():
        if not row.get("required"):
            continue
        name = str(row.get("name") or "")
        displays = [str(d) for d in (row.get("selectDisplays") or [])]
        filled = [d for d in displays if d and d != "请选择"]
        if filled:
            plan.append({"name": name, "action": "already", "value": filled[0],
                         "reason": "已有值"})
            continue
        recommendation = platform_recommendation(str(row.get("hint") or ""))
        leaf = category_leaf(row.get("category_path") or ())
        value = safe_default_for(name, row.get("options") or (), prefer=recommendation,
                                 category_leaf_name=leaf)
        if not value and name in RECENCY_FIELDS:
            # 上市年份季节：取**最新一期**（它只是上架时间标签，不参与搜索卖点）
            value = most_recent_option(row.get("options") or ())
            if value:
                plan.append({"name": name, "action": "fill", "value": value,
                             "reason": "上架时间标签，取最新一期"})
                continue
        if value:
            plan.append({"name": name, "action": "fill", "value": value,
                         "reason": "平台推荐值" if recommendation == value else "零商品语义的稳妥值"})
        else:
            plan.append({"name": name, "action": "needs_human", "value": None,
                         "reason": "没有稳妥通用值，必须由人或商品数据决定"})
    return plan

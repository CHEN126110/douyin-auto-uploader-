# -*- coding: utf-8 -*-
"""电商罗盘域：核心经营数据（只读）。

罗盘核心数据页在独立子域 compass.jinritemai.com/shop，以"指标卡"展示经营数据。
每张卡的 DOM 文本形如：
    成交金额 ¥2.90 昨日 ¥0.00 同行基准 ¥86.78
卡片容器 class 含 data-card-wrapper；同一指标会相邻渲染两次（且核心区 / 财务区可能出现
同名指标），故按 label 去重保留首个。

合规：纯只读数据查询，仅查看用户自己店铺的罗盘数据；不复现签名、不绕过风控。
说明：页面图表为 canvas 绘制，其内部明细数值无法经 DOM 提取，本接口只汇总指标卡数值。
"""
from __future__ import annotations

import re
from typing import List, Optional

from flask import Blueprint

from ..core import BrowserContext, BusinessApiError, ErrorCode
from .base import (
    SkeletonEndpoint,
    as_int,
    get_context,
    get_json,
    handle_errors,
    json_ok,
    register_skeleton,
)

bp = Blueprint("compass", __name__, url_prefix="/api/compass")

URLS = {"core": "https://compass.jinritemai.com/shop"}
SEL = {"card": "css:[class*=data-card-wrapper]"}

_YESTERDAY_MARK = "昨日"
# 同行对比标记：优先用"同行基准"（同行均值），缺值时退而用"同行顶尖"等
_PEER_PREFERENCE = ("同行基准", "同行均值", "同行顶尖", "同行标杆")
# 昨日值取首个同行标记之前的内容（含兜底裸"同行"），避免被对比段污染
_PEER_MARKS = _PEER_PREFERENCE + ("同行",)
# 值 token：货币/数字/百分比，或 "-"（页面用 "-" 表示该指标当日暂无数据）
_VALUE_TOKEN_RE = re.compile(r"^(?:[¥￥]?[-+]?\d[\d,]*(?:\.\d+)?%?|-)$")
# 成交渠道分布卡（非核心 KPI，且有数据时为"渠道额+占比"的异形格式），统一从概览排除
_CHANNEL_LABELS = {"商品卡", "直播", "短视频", "图文"}


def _extract_peers(peer_seg: str) -> dict:
    """解析对比段里各"同行*"标记 -> 其后的值（截到下一个标记前）。"""
    hits = sorted((peer_seg.find(mk), mk) for mk in _PEER_PREFERENCE if mk in peer_seg)
    result = {}
    for i, (pos, mk) in enumerate(hits):
        start = pos + len(mk)
        end = hits[i + 1][0] if i + 1 < len(hits) else len(peer_seg)
        result[mk] = peer_seg[start:end].strip()
    return result


def _parse_compare(tail: str) -> tuple:
    """从对比段提取（昨日值, 同行对比值, 同行对比类型）。

    对比段形如 " ¥0.00 同行基准 ¥86.78" 或 " 0% 同行顶尖 100% 同行基准 9.04%"。
    昨日值 = 首个"同行*"标记之前的内容；同行对比优先取"同行基准"，缺值时退用顶尖/标杆，
    并回传实际采用的类型，避免把"同行均值"与"同行顶尖"混为一谈。
    """
    tail = tail.strip()
    if not tail:
        return "", "", ""
    cut = len(tail)
    for mk in _PEER_MARKS:
        idx = tail.find(mk)
        if idx != -1:
            cut = min(cut, idx)
    yesterday = tail[:cut].strip()
    peers = _extract_peers(tail[cut:])
    for mk in _PEER_PREFERENCE:
        if peers.get(mk):
            return yesterday, peers[mk], mk
    return yesterday, "", ""


def _parse_card(text: str) -> Optional[dict]:
    """把一张指标卡整段文本解析为 {label, value, yesterday, benchmark, benchmark_type}。

    形如："成交金额 ¥2.90 昨日 ¥0.00 同行基准 ¥86.78"，或当日暂无数据时"成交金额 - 昨日 -"。
    先按首个"昨日"切出"标签+值"段，值取该段最后一个 token（数值或 "-"），其余为标签；
    再从对比段取昨日值与同行对比。标签为空 / 含货币百分号（异形卡）/ 属渠道分布卡，返回 None。
    """
    norm = " ".join((text or "").split())
    if not norm:
        return None
    head, tail = norm.split(_YESTERDAY_MARK, 1) if _YESTERDAY_MARK in norm else (norm, "")
    tokens = head.split()
    if len(tokens) < 2:
        return None  # 至少要有"标签 值"两段
    value = tokens[-1]
    if not _VALUE_TOKEN_RE.match(value):
        return None  # 末尾不是值（纯标签 / 异形卡）
    label = " ".join(tokens[:-1]).strip()
    if not label or label in _CHANNEL_LABELS or any(sym in label for sym in ("¥", "￥", "%")):
        return None
    yesterday, benchmark, benchmark_type = _parse_compare(tail)
    return {
        "label": label,
        "value": value,
        "yesterday": yesterday,
        "benchmark": benchmark,
        "benchmark_type": benchmark_type,
    }


class CompassService:
    def __init__(self, ctx: BrowserContext) -> None:
        self.ctx = ctx

    def _open_core(self) -> None:
        self.ctx.goto(URLS["core"])
        self.ctx.require_login()
        if not self.ctx.wait_visible(SEL["card"], timeout=15):
            raise BusinessApiError(
                ErrorCode.ELEMENT_NOT_FOUND,
                "未能加载罗盘核心数据指标卡。",
                hint="可能页面尚未渲染完成、登录态失效，或罗盘改版导致选择器失效。",
                context={"url": URLS["core"]},
            )
        # 罗盘指标卡为 SPA 渐进渲染，等数量稳定再读，避免读到半截页面（漏指标）
        self.ctx.wait_count_stable(SEL["card"], min_count=1)

    def overview(self, keyword: str = "", limit: int = 50) -> dict:
        self._open_core()
        texts = self.ctx.read_texts(SEL["card"])
        seen = set()
        unique: List[dict] = []
        for t in texts:
            card = _parse_card(t)
            if not card or card["label"] in seen:
                continue
            seen.add(card["label"])
            unique.append(card)
        if keyword:
            unique = [m for m in unique if keyword in m["label"]]
        metrics = unique[: max(1, limit)]
        return {
            "count": len(metrics),
            "metrics": metrics,
            "by_label": {m["label"]: m["value"] for m in metrics},
            "note": (
                "数值取自罗盘指标卡 DOM 文本；value/yesterday 为 \"-\" 表示该指标当日暂无数据"
                "（实时数据尚未产生），并非接口异常。benchmark_type 标明同行对比口径"
                "（同行基准=均值 / 同行顶尖=头部），为空表示该卡未展示同行对比。"
                "成交渠道分布卡（商品卡/直播/短视频/图文）与 canvas 图表不在本接口范围内。"
            ),
        }


@bp.post("/overview")
@handle_errors
def compass_overview():
    data = get_json()
    keyword = str(data.get("keyword") or "")
    limit = as_int(data, "limit", 50)
    svc = CompassService(get_context())
    return json_ok("罗盘核心经营数据已读取。", svc.overview(keyword=keyword, limit=limit))


# 罗盘其余分析页（商品 / 流量 / 直播）为独立子页，待各自联调后填充
register_skeleton(
    bp,
    [
        SkeletonEndpoint("POST", "/product-analysis", "product_analysis", "商品分析"),
        SkeletonEndpoint("POST", "/traffic-analysis", "traffic_analysis", "流量分析"),
        SkeletonEndpoint("POST", "/live-analysis", "live_analysis", "直播分析"),
    ],
    "compass",
)

# -*- coding: utf-8 -*-
"""运营闭环核心逻辑。

本模块只做本地规则计算和 SQLite 账本读写，不调用任何外部 AI 或抖店官方 API。
"""

from __future__ import annotations

import copy
import json
import math
import re
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, asdict
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path
from statistics import median
from typing import Any, Dict, Iterable, Iterator, List, Mapping, Optional, Sequence

from .professional_title_generator import audit_no_brand_title_text
from .runtime_paths import get_resource_dir, resolve_data_file

DAILY_NET_PROFIT_TARGET = 500
AI_POLICY = {
    "external_ai_disabled": True,
    "decision_source": "codex_only",
    "blocked_providers": ["openai", "ollama", "deepseek", "claude", "third_party"],
}


def resolve_ops_ledger_path() -> Path:
    return resolve_data_file("ops_ledger.db", legacy_fallback=get_resource_dir() / "ops_ledger.db")


def _money(value: Any) -> float:
    decimal_value = Decimal(str(value or 0))
    return float(decimal_value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _rate(value: Any) -> float:
    number = float(value or 0)
    return number / 100 if number > 1 else number


@dataclass(frozen=True)
class OperatingCostInput:
    sale_price: float
    goods_cost: float
    shipping_cost: float = 0
    packaging_cost: float = 0
    platform_commission_rate: float = 0
    promotion_cost: float = 0
    refund_loss: float = 0
    after_sale_loss: float = 0


@dataclass(frozen=True)
class OperatingProfitResult:
    sale_price: float
    goods_cost: float
    shipping_cost: float
    packaging_cost: float
    platform_commission_rate: float
    platform_commission: float
    promotion_cost: float
    refund_loss: float
    after_sale_loss: float
    cost_total: float
    net_profit: float
    net_margin: float
    target_daily_orders: Optional[int]


@dataclass(frozen=True)
class ProductEvaluationInput(OperatingCostInput):
    record_id: int = 0
    title: str = ""
    expected_daily_orders: int = 0


@dataclass(frozen=True)
class ProductEvaluation:
    record_id: int
    title: str
    net_profit_per_order: float
    net_margin: float
    expected_daily_orders: int
    expected_daily_net_profit: float
    target_daily_orders: Optional[int]
    decision: str
    rationale: str
    profit: Dict[str, Any]


@dataclass(frozen=True)
class StockPlanInput:
    record_id: int
    sku_count: int
    expected_daily_orders: int = 0
    replenishment_days: int = 1
    can_restock_same_day: bool = True
    max_per_sku_without_sales_signal: int = 2


@dataclass(frozen=True)
class StockPlan:
    record_id: int
    sku_count: int
    expected_daily_orders: int
    replenishment_days: int
    can_restock_same_day: bool
    per_sku_stock: int
    total_recommended_stock: int
    risk_level: str
    rationale: str


@dataclass(frozen=True)
class ProductCandidateInput:
    record_id: int
    title: str
    sku_prices: Sequence[float]
    current_sku_prices: Sequence[float] = ()
    shipping_cost: float = 0
    packaging_cost: float = 0
    platform_commission_rate: float = 0
    promotion_cost: float = 0
    refund_loss: float = 0
    after_sale_loss: float = 0
    target_net_margin: float = 0.30
    expected_daily_orders: int = 0
    replenishment_days: int = 1
    can_restock_same_day: bool = True
    max_per_sku_without_sales_signal: int = 2


def calculate_operating_profit(cost: OperatingCostInput) -> OperatingProfitResult:
    sale_price = _money(cost.sale_price)
    goods_cost = _money(cost.goods_cost)
    shipping_cost = _money(cost.shipping_cost)
    packaging_cost = _money(cost.packaging_cost)
    commission_rate = _rate(cost.platform_commission_rate)
    platform_commission = _money(sale_price * commission_rate)
    promotion_cost = _money(cost.promotion_cost)
    refund_loss = _money(cost.refund_loss)
    after_sale_loss = _money(cost.after_sale_loss)
    cost_total = _money(
        goods_cost
        + shipping_cost
        + packaging_cost
        + platform_commission
        + promotion_cost
        + refund_loss
        + after_sale_loss
    )
    net_profit = _money(sale_price - cost_total)
    net_margin = _money((net_profit / sale_price) * 100) if sale_price > 0 else 0
    target_orders = math.ceil(DAILY_NET_PROFIT_TARGET / net_profit) if net_profit > 0 else None

    return OperatingProfitResult(
        sale_price=sale_price,
        goods_cost=goods_cost,
        shipping_cost=shipping_cost,
        packaging_cost=packaging_cost,
        platform_commission_rate=commission_rate,
        platform_commission=platform_commission,
        promotion_cost=promotion_cost,
        refund_loss=refund_loss,
        after_sale_loss=after_sale_loss,
        cost_total=cost_total,
        net_profit=net_profit,
        net_margin=net_margin,
        target_daily_orders=target_orders,
    )


def _marketing_price(raw_price: float) -> float:
    price = float(raw_price or 0)
    if price <= 0:
        return 0.0
    return _money(max(math.ceil(price - 0.9) + 0.9, 0.9))


def recommend_sale_price_for_margin(cost: OperatingCostInput, target_net_margin: float = 0.30) -> float:
    margin_rate = _rate(target_net_margin)
    commission_rate = _rate(cost.platform_commission_rate)
    denominator = 1 - commission_rate - margin_rate
    if denominator <= 0:
        return 0.0
    fixed_costs = _money(
        cost.goods_cost
        + cost.shipping_cost
        + cost.packaging_cost
        + cost.promotion_cost
        + cost.refund_loss
        + cost.after_sale_loss
    )
    return _marketing_price(fixed_costs / denominator)


def evaluate_product(product: ProductEvaluationInput) -> ProductEvaluation:
    profit = calculate_operating_profit(product)
    expected_profit = _money(profit.net_profit * max(product.expected_daily_orders, 0))

    if profit.net_profit <= 0:
        decision = "block"
        rationale = "单笔经营净利不为正，禁止发布或需要重新定价"
    elif expected_profit >= DAILY_NET_PROFIT_TARGET:
        decision = "priority_launch"
        rationale = "预计日经营净利已达到目标，优先发布并跟踪真实订单"
    elif profit.net_margin >= 20:
        decision = "test_launch"
        rationale = "单笔净利和毛利率可接受，建议低预算试卖并控制备货"
    else:
        decision = "review_price"
        rationale = "净利率偏低，先复核拿货价、售价或推广成本"

    return ProductEvaluation(
        record_id=int(product.record_id or 0),
        title=str(product.title or ""),
        net_profit_per_order=profit.net_profit,
        net_margin=profit.net_margin,
        expected_daily_orders=max(int(product.expected_daily_orders or 0), 0),
        expected_daily_net_profit=expected_profit,
        target_daily_orders=profit.target_daily_orders,
        decision=decision,
        rationale=rationale,
        profit=asdict(profit),
    )


def _order_has_key(order: Mapping[str, Any], key: str) -> bool:
    return key in order and order.get(key) not in (None, "")


def build_net_profit_verification_matrix(
    orders: Sequence[Mapping[str, Any]],
    target_net_profit: float = DAILY_NET_PROFIT_TARGET,
) -> Dict[str, Any]:
    """按订单明细核验经营净利。

    只有每笔订单的商品成本、运费、包装、佣金、推广、退款和售后损失都具备时，才把净利标记为已验证。
    """

    required_cost_fields = [
        "sale_price",
        "goods_cost",
        "shipping_cost",
        "packaging_cost",
        "platform_commission_rate",
        "promotion_cost",
        "refund_loss",
        "after_sale_loss",
    ]
    order_rows = [dict(order) for order in (orders or []) if isinstance(order, Mapping)]
    verified_orders: List[Dict[str, Any]] = []
    unverified_orders: List[Dict[str, Any]] = []

    for index, order in enumerate(order_rows, start=1):
        missing_fields = [field for field in required_cost_fields if not _order_has_key(order, field)]
        order_id = str(order.get("order_id") or order.get("orderId") or f"order_{index}")
        if missing_fields:
            unverified_orders.append({
                "order_id": order_id,
                "product_id": str(order.get("product_id") or order.get("productId") or ""),
                "missing_fields": missing_fields,
                "verified": False,
            })
            continue
        profit = calculate_operating_profit(
            OperatingCostInput(
                sale_price=_money(order.get("sale_price")),
                goods_cost=_money(order.get("goods_cost")),
                shipping_cost=_money(order.get("shipping_cost")),
                packaging_cost=_money(order.get("packaging_cost")),
                platform_commission_rate=_rate(order.get("platform_commission_rate")),
                promotion_cost=_money(order.get("promotion_cost")),
                refund_loss=_money(order.get("refund_loss")),
                after_sale_loss=_money(order.get("after_sale_loss")),
            )
        )
        verified_orders.append({
            "order_id": order_id,
            "product_id": str(order.get("product_id") or order.get("productId") or ""),
            "sale_price": profit.sale_price,
            "cost_total": profit.cost_total,
            "net_profit": profit.net_profit,
            "net_margin": profit.net_margin,
            "verified": True,
        })

    total_net_profit = _money(sum(_money(order.get("net_profit", 0)) for order in verified_orders))
    net_profit_verified = bool(order_rows and not unverified_orders and verified_orders)
    target_achieved = bool(net_profit_verified and total_net_profit >= _money(target_net_profit))
    if not order_rows:
        decision = "wait_for_orders"
    elif unverified_orders:
        decision = "needs_cost_evidence"
    elif target_achieved:
        decision = "target_verified"
    else:
        decision = "verified_below_target"

    blockers: List[str] = []
    if not order_rows:
        blockers.append("没有订单，不能核验经营净利")
    if unverified_orders:
        blockers.append("存在订单缺少商品成本、运费、佣金、推广费、退款或售后证据")
    if order_rows and not target_achieved:
        blockers.append("真实经营净利尚未验证达到500元")

    ready_for_paid_scale = bool(target_achieved)
    brand_policy = {
        "required_value": "无品牌",
        "title_use_brand_name_required": False,
        "keyword_brand_comparison_allowed": False,
        "reason": "用户无品牌资质，安全稳健优先",
    }
    return {
        "plan_type": "net_profit_verification_matrix",
        "target_net_profit": _money(target_net_profit),
        "decision": decision,
        "net_profit_verified": net_profit_verified,
        "target_achieved": target_achieved,
        "ready_for_paid_scale": ready_for_paid_scale,
        "paid_ads_paused": not ready_for_paid_scale,
        "safe_to_auto_apply": False,
        "order_count": len(order_rows),
        "verified_order_count": len(verified_orders),
        "unverified_order_count": len(unverified_orders),
        "total_net_profit": total_net_profit,
        "verified_orders": verified_orders,
        "unverified_orders": unverified_orders,
        "required_cost_fields": required_cost_fields,
        "next_actions": [
            "同步订单明细、商品成本、运费、包装、平台佣金、推广费、退款和售后损失",
            "全部订单成本字段完整后再写入 net_profit_verified=true",
            "未验证达到500元日净利前不投放、不采购、不批量备货",
        ],
        "blockers": blockers,
        "safety_gates": [
            "不调用抖店官方 API",
            "不调用外部 AI 或第三方模型",
            "品牌字段统一无品牌，标题不写品牌词",
            "不自动保存、不发布、不投放、不付款",
            "不自动采购、不批量备货",
        ],
        "brand_policy": brand_policy,
        "no_brand_policy": brand_policy,
        "ai_policy": dict(AI_POLICY),
    }


def _positive_prices(values: Sequence[float]) -> List[float]:
    prices: List[float] = []
    for value in values or []:
        try:
            number = float(value or 0)
        except Exception:
            number = 0
        if number > 0:
            prices.append(number)
    return prices


def _positive_number(value: Any) -> float:
    try:
        number = float(value or 0)
    except Exception:
        return 0.0
    return number if number > 0 else 0.0


def extract_sku_goods_costs(sku_list: Sequence[Mapping[str, Any]]) -> List[float]:
    costs: List[float] = []
    for sku in sku_list or []:
        if not isinstance(sku, Mapping):
            continue
        cost = _positive_number(sku.get("ops_goods_cost"))
        if cost <= 0:
            cost = _positive_number(sku.get("goods_cost"))
        if cost <= 0:
            cost = _positive_number(sku.get("price"))
        if cost > 0:
            costs.append(cost)
    return costs


def apply_candidate_pricing_to_skus(sku_list: Sequence[Mapping[str, Any]], sale_price: float) -> Dict[str, Any]:
    next_price = _money(sale_price)
    if next_price <= 0:
        raise ValueError("sale_price must be greater than 0")

    updated: List[Dict[str, Any]] = []
    changes: List[Dict[str, Any]] = []
    for sku in sku_list or []:
        row = copy.deepcopy(dict(sku or {}))
        old_price = _positive_number(row.get("price"))
        old_goods_cost = _positive_number(row.get("ops_goods_cost")) or _positive_number(row.get("goods_cost"))
        if old_goods_cost <= 0 and old_price > 0:
            old_goods_cost = old_price
        if old_goods_cost > 0:
            row["ops_goods_cost"] = _money(old_goods_cost)
        row["price"] = next_price
        updated.append(row)
        changes.append({
            "path": row.get("path") or "",
            "name": row.get("name") or "",
            "old_price": _money(old_price),
            "new_price": next_price,
            "ops_goods_cost": row.get("ops_goods_cost", 0),
        })

    return {
        "skus": updated,
        "changes": changes,
        "updated_count": len(changes),
        "sale_price": next_price,
    }


def build_product_candidate(candidate: ProductCandidateInput) -> Dict[str, Any]:
    sku_prices = _positive_prices(candidate.sku_prices)
    current_sku_prices = _positive_prices(candidate.current_sku_prices)
    display_sku_prices = current_sku_prices or sku_prices
    sku_count = max(len(candidate.current_sku_prices or candidate.sku_prices or []), 1)
    goods_cost = _money(median(sku_prices)) if sku_prices else 0.0
    recommended_sale_price = recommend_sale_price_for_margin(
        OperatingCostInput(
            sale_price=0,
            goods_cost=goods_cost,
            shipping_cost=candidate.shipping_cost,
            packaging_cost=candidate.packaging_cost,
            platform_commission_rate=candidate.platform_commission_rate,
            promotion_cost=candidate.promotion_cost,
            refund_loss=candidate.refund_loss,
            after_sale_loss=candidate.after_sale_loss,
        ),
        target_net_margin=candidate.target_net_margin,
    )
    evaluation = evaluate_product(
        ProductEvaluationInput(
            record_id=candidate.record_id,
            title=candidate.title,
            sale_price=recommended_sale_price,
            goods_cost=goods_cost,
            shipping_cost=candidate.shipping_cost,
            packaging_cost=candidate.packaging_cost,
            platform_commission_rate=candidate.platform_commission_rate,
            promotion_cost=candidate.promotion_cost,
            refund_loss=candidate.refund_loss,
            after_sale_loss=candidate.after_sale_loss,
            expected_daily_orders=candidate.expected_daily_orders,
        )
    )
    stock_plan = build_stock_plan(
        StockPlanInput(
            record_id=candidate.record_id,
            sku_count=sku_count,
            expected_daily_orders=candidate.expected_daily_orders,
            replenishment_days=candidate.replenishment_days,
            can_restock_same_day=candidate.can_restock_same_day,
            max_per_sku_without_sales_signal=candidate.max_per_sku_without_sales_signal,
        )
    )

    warnings: List[str] = []
    if current_sku_prices and min(current_sku_prices) < recommended_sale_price:
        warnings.append("当前 SKU 发布价低于建议售价，发布前应人工确认或重新应用建议售价")
    elif sku_prices and not current_sku_prices and min(sku_prices) < recommended_sale_price:
        warnings.append("当前 SKU 价格像拿货成本，发布前应改为建议售价或人工确认售价")
    if not sku_prices:
        warnings.append("未读取到 SKU 成本价格，不能形成可靠利润测算")
    if evaluation.target_daily_orders and evaluation.target_daily_orders >= 150:
        warnings.append(f"达到 500 元日净利需要约 {evaluation.target_daily_orders} 单，需先低预算验证转化")

    return {
        "record_id": int(candidate.record_id or 0),
        "title": str(candidate.title or ""),
        "sku_count": sku_count,
        "sku_price_min": _money(min(display_sku_prices)) if display_sku_prices else 0.0,
        "sku_price_max": _money(max(display_sku_prices)) if display_sku_prices else 0.0,
        "goods_cost_min": _money(min(sku_prices)) if sku_prices else 0.0,
        "goods_cost_max": _money(max(sku_prices)) if sku_prices else 0.0,
        "goods_cost_source": "sku_price_median" if sku_prices else "missing",
        "goods_cost": goods_cost,
        "recommended_sale_price": recommended_sale_price,
        "target_net_margin": _rate(candidate.target_net_margin),
        "evaluation": asdict(evaluation),
        "stock_plan": asdict(stock_plan),
        "warnings": warnings,
    }


def build_product_candidate_list(candidates: Iterable[ProductCandidateInput]) -> List[Dict[str, Any]]:
    rows = [build_product_candidate(candidate) for candidate in candidates]

    def sort_key(row: Mapping[str, Any]) -> tuple:
        evaluation = row.get("evaluation") if isinstance(row.get("evaluation"), dict) else {}
        target_orders = evaluation.get("target_daily_orders")
        if target_orders is None:
            target_orders = 10**9
        return (int(target_orders), -float(evaluation.get("net_profit_per_order") or 0), int(row.get("record_id") or 0))

    return sorted(rows, key=sort_key)


def build_stock_plan(stock: StockPlanInput) -> StockPlan:
    sku_count = max(int(stock.sku_count or 0), 1)
    expected_daily_orders = max(int(stock.expected_daily_orders or 0), 0)
    replenishment_days = max(int(stock.replenishment_days or 1), 1)

    if expected_daily_orders <= 0:
        per_sku_stock = max(int(stock.max_per_sku_without_sales_signal or 1), 1)
        total_stock = per_sku_stock * sku_count
        risk_level = "low" if stock.can_restock_same_day else "medium"
        rationale = "没有实销信号，按每个 SKU 少量试卖备货，避免库存积压"
    else:
        base_stock = expected_daily_orders * replenishment_days
        safety_rate = 0.1 if stock.can_restock_same_day else 0.25
        total_stock = math.ceil(base_stock * (1 + safety_rate))
        per_sku_stock = max(math.ceil(total_stock / sku_count), 1)
        total_stock = per_sku_stock * sku_count
        risk_level = "medium" if total_stock <= 100 else "high"
        rationale = "按预计销量、补货周期和安全库存生成备货建议"

    return StockPlan(
        record_id=int(stock.record_id or 0),
        sku_count=sku_count,
        expected_daily_orders=expected_daily_orders,
        replenishment_days=replenishment_days,
        can_restock_same_day=bool(stock.can_restock_same_day),
        per_sku_stock=per_sku_stock,
        total_recommended_stock=total_stock,
        risk_level=risk_level,
        rationale=rationale,
    )


def _bottleneck_action(area: str, action: str, verification: str) -> Dict[str, str]:
    return {
        "area": area,
        "action": action,
        "verification": verification,
    }


def build_market_context(metrics: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """Return local operations knowledge for socks without calling external AI."""

    metrics = metrics or {}
    product_exposure_count = max(int(metrics.get("product_exposure_count", 0) or 0), 0)
    product_click_count = max(int(metrics.get("product_click_count", 0) or 0), 0)
    orders_count = max(int(metrics.get("orders_count", 0) or 0), 0)

    stage_actions: List[str] = []
    if product_exposure_count > 0 and product_click_count == 0:
        stage_actions.extend([
            "当前是商品卡点击瓶颈，暂停付费投放，先优化首图、标题、主图视频和价格口径",
            "利用已有搜索曝光验证核心词，不堆无关词，下一轮看商品点击人数是否转正",
        ])
    elif product_click_count > 0 and orders_count == 0:
        stage_actions.extend([
            "当前是详情承接瓶颈，先复核详情页、SKU、运费、退换说明和下单口径",
            "继续暂停放量投放，直到点击能转化为订单且单笔净利仍为正",
        ])
    elif orders_count > 0:
        stage_actions.extend([
            "当前进入利润验证阶段，必须同步订单、退款、售后、运费、佣金和推广消耗",
            "补货按真实销量和同日补货能力推进，不因单日曝光扩大库存",
        ])
    else:
        stage_actions.append("先保证商品可发布、素材完整、数据可读，再做最终发布和增长验证")

    return {
        "category": "socks",
        "brand_policy": "no_brand_only_without_qualification",
        "platform_signals": [
            "抖音电商学习中心持续强调搜索运营、商品优化和货架流量；当前计划以浏览器可见数据验证，不使用官方 API",
            "搜索曝光已经出现时，优先围绕搜索运营做标题关键词和商品卡素材承接",
            "商品卡有曝光无点击时，先解决首图、主图视频、规格和价格口径，再考虑付费放量",
        ],
        "market_signals": [
            "袜子是刚需低客单高复购品类，但白牌同质化强，不能只靠低价",
            "2026 袜子消费趋势更偏功能化、场景化和快反上新，例如春夏薄款、浅口、运动、防臭、搭配场景",
            "当前女款浅口船袜应突出春夏薄款、上脚效果、适配小白鞋/帆布鞋、均码和 1 双口径",
        ],
        "compliance_rules": [
            "没有品牌资质时，类目属性统一选择无品牌",
            "标题区使用品牌名保持关闭，标题和导购短标题不写品牌词",
            "不借用、不猜测、不自造品牌，不为了短期流量牺牲合规稳定",
            "最终发布、付款、投放扣费和不可逆确认仍保留人工安全闸",
        ],
        "stage_actions": stage_actions,
        "knowledge_source": "local_rules_public_research_codex_only",
    }


def _contains_any(text: str, terms: Sequence[str]) -> bool:
    lowered = text.lower()
    return any(str(term).lower() in lowered for term in terms)


def _search_text_from_metrics(metrics: Mapping[str, Any]) -> str:
    raw_payload = metrics.get("raw_payload")
    if not isinstance(raw_payload, Mapping):
        raw_payload = _json_dict(metrics.get("raw_payload_json"))
    text_parts = [
        str(raw_payload.get("text_excerpt") or ""),
        str(metrics.get("text_excerpt") or ""),
        str(metrics.get("notes") or ""),
    ]
    return " ".join(part for part in text_parts if part)


def _no_brand_search_term_candidates(title: str) -> List[str]:
    audit = audit_no_brand_title_text(title)
    clean = str(audit.get("sanitized_title") or title or "")
    if audit.get("has_risk"):
        clean = str(audit.get("sanitized_title") or "")

    phrase_rules = [
        ("波点", "中筒袜", "波点中筒袜"),
        ("夏季", "薄款", "夏季薄款袜"),
        ("蕾丝", "花边", "蕾丝花边袜"),
        ("防臭", "袜", "防臭袜子女"),
        ("堆堆", "袜", "甜美堆堆袜"),
        ("小雏菊", "碎花", "小雏菊碎花袜"),
        ("镂空", "网眼", "镂空网眼袜"),
        ("船袜", "隐形", "隐形船袜女"),
        ("冰丝", "船袜", "冰丝船袜女"),
        ("蝴蝶结", "中筒袜", "蝴蝶结中筒袜"),
        ("木耳边", "袜", "木耳边袜子女"),
        ("春夏", "中筒袜", "春夏中筒袜"),
    ]
    terms: List[str] = []
    for left, right, term in phrase_rules:
        if left in clean and right in clean:
            terms.append(term)

    fallback_terms = ["中筒袜女", "夏季薄款袜", "透气袜子女"]
    for term in fallback_terms:
        if term in clean:
            terms.append(term)
    return list(dict.fromkeys(terms))


def build_search_conversion_work_package(
    metrics: Mapping[str, Any],
    product_issue_actions: Sequence[Mapping[str, Any]],
    target_net_profit: float = DAILY_NET_PROFIT_TARGET,
    action_id: Optional[int] = None,
) -> Dict[str, Any]:
    """生成搜索承接工作包。

    只根据本地账本和浏览器可见文本做规则化拆解，不自动配置看后搜/小蓝词，不保存、发布、投放或付款。
    """

    metric_row = dict(metrics or {})
    exposure = _nonnegative_int(metric_row.get("product_exposure_count"))
    clicks = _nonnegative_int(metric_row.get("product_click_count"))
    orders = _nonnegative_int(metric_row.get("orders_count"))
    search_exposure = _nonnegative_int(metric_row.get("search_exposure_count"))
    click_rate = _money((clicks / exposure) * 100) if exposure > 0 else 0
    if clicks > 0 and orders == 0:
        stage = "search_click_without_order"
    elif search_exposure > 0 and clicks == 0:
        stage = "search_exposure_without_click"
    elif orders > 0:
        stage = "order_profit_verification"
    else:
        stage = "search_signal_collection"

    visible_text = _search_text_from_metrics(metric_row)
    readonly_platform_signals: List[str] = []
    if "看后搜" in visible_text:
        readonly_platform_signals.append("浏览器可见提示包含看后搜配置机会，但只能先生成候选词和人工配置清单")
    if "小蓝词" in visible_text:
        readonly_platform_signals.append("浏览器可见提示包含小蓝词配置机会，但不得自动批量设置")
    if not readonly_platform_signals:
        readonly_platform_signals.append("未读到新的看后搜或小蓝词提示，继续围绕搜索曝光和商品点击做只读复盘")

    actions = [dict(action) for action in product_issue_actions or [] if isinstance(action, Mapping)]
    requested_action_id = _nonnegative_int(action_id)
    safe_focus_rows: List[Dict[str, Any]] = []
    for action in actions:
        audit = audit_no_brand_title_text(str(action.get("title") or ""))
        row_action_id = _nonnegative_int(action.get("id") or action.get("action_id") or action.get("actionId"))
        row = {
            "action_id": row_action_id,
            "product_id": str(action.get("product_id") or action.get("productId") or ""),
            "title": str(action.get("title") or ""),
            "recent_30d_sales": _nonnegative_int(action.get("recent_30d_sales") or action.get("recent30dSales")),
            "action_status": action.get("action_status") or action.get("actionStatus"),
            "brand_risk": bool(audit.get("has_risk")),
            "requires_supplier_evidence": True,
            "safe_to_auto_apply": False,
            "allowed_next_action": "只采集同款素材、无品牌供货凭证、供应商成本和搜索承接词证据",
        }
        if requested_action_id and row_action_id != requested_action_id:
            continue
        if row["brand_risk"]:
            row["allowed_next_action"] = "只读确认线上品牌字段和标题来源，清理品牌残留后才能进入搜索承接"
        safe_focus_rows.append(row)

    if not safe_focus_rows:
        safe_focus_rows = [
            {
                "action_id": 0,
                "product_id": "",
                "title": "",
                "recent_30d_sales": 0,
                "action_status": "none",
                "brand_risk": False,
                "requires_supplier_evidence": False,
                "safe_to_auto_apply": False,
                "allowed_next_action": "继续只读同步搜索曝光、商品点击和订单数据",
            }
        ]
    safe_focus_rows.sort(key=lambda row: (-_nonnegative_int(row.get("recent_30d_sales")), _nonnegative_int(row.get("action_id"))))

    forbidden_fragments = ["品牌", "牌子", "songmu", "淞木", "kikisocks", "澳洲小绿"]
    candidate_terms: List[str] = []
    for row in safe_focus_rows:
        if row.get("brand_risk"):
            continue
        for term in _no_brand_search_term_candidates(str(row.get("title") or "")):
            if term and not _contains_any(term, forbidden_fragments):
                candidate_terms.append(term)
    if not candidate_terms:
        candidate_terms.extend(["中筒袜女", "夏季薄款袜", "透气袜子女"])
    candidate_terms = list(dict.fromkeys(candidate_terms))[:12]

    brand_policy = {
        "required_value": "无品牌",
        "title_use_brand_name_required": False,
        "keyword_brand_comparison_allowed": False,
        "reason": "用户无品牌资质，安全稳健优先",
    }

    return {
        "plan_type": "search_conversion_work_package",
        "target_net_profit": _money(target_net_profit),
        "stage": stage,
        "current_state": {
            "snapshot_id": _nonnegative_int(metric_row.get("id") or metric_row.get("snapshot_id") or metric_row.get("snapshotId")),
            "snapshot_date": str(metric_row.get("snapshot_date") or date.today().isoformat()),
            "product_exposure_count": exposure,
            "product_click_count": clicks,
            "product_click_rate": click_rate,
            "search_exposure_count": search_exposure,
            "orders_count": orders,
            "promotion_cost": _money(metric_row.get("promotion_cost", 0)),
            "net_profit": _money(metric_row.get("net_profit", 0)),
            "net_profit_verified": bool(metric_row.get("net_profit_verified", False)),
        },
        "readonly_platform_signals": readonly_platform_signals,
        "focus_products": safe_focus_rows[:5],
        "candidate_search_terms": candidate_terms,
        "manual_work_items": [
            "人工确认后才可在平台配置看后搜或小蓝词，且只使用无品牌搜索词",
            "先补 action id=1 的同款主图视频、SKU 图、材质凭证、成本、运费和无品牌供货证明",
            "保存或配置前重新运行无品牌页面闸：品牌=无品牌、使用品牌名=false、标题不含品牌词",
            "下一次复盘只看真实订单和经营净利，不用未验证曝光替代收入",
        ],
        "verification_metrics": [
            "product_exposure_count",
            "product_click_count",
            "search_exposure_count",
            "orders_count",
            "gross_sales",
            "net_profit_verified",
            "promotion_cost",
        ],
        "safe_to_auto_apply": False,
        "paid_ads_paused": True,
        "forbidden_actions": [
            "不得自动批量设置小蓝词或看后搜",
            "不得点击立即优化、一键优化、标题托管或销量助推",
            "不得自动保存、发布、投放、付款或采购",
            "不得写入任何非无品牌品牌词",
        ],
        "safety_gates": [
            "不调用抖店官方 API",
            "不调用外部 AI 或第三方模型",
            "品牌字段统一无品牌，标题和搜索词不写品牌词",
            "平台配置、保存、发布、付款和投放扣费保留人工安全闸",
        ],
        "brand_policy": brand_policy,
        "no_brand_policy": brand_policy,
        "ai_policy": dict(AI_POLICY),
    }


def build_no_brand_title_audit(product_issue_actions: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    risky_products: List[Dict[str, Any]] = []
    safe_products: List[Dict[str, Any]] = []

    for action in product_issue_actions:
        title = str(action.get("title") or "").strip()
        audit = audit_no_brand_title_text(title)
        row = {
            "action_id": action.get("id") or action.get("action_id") or action.get("actionId"),
            "product_id": action.get("product_id") or action.get("productId"),
            "title": title,
            "action_status": action.get("action_status") or action.get("actionStatus"),
            "sanitized_title": audit["sanitized_title"],
            "risk_flags": audit["risk_flags"],
        }
        if audit["has_risk"]:
            row["recommended_next_action"] = "先只读进入商品编辑页确认线上品牌字段和标题来源，再走无品牌标题整改安全闸"
            risky_products.append(row)
        else:
            safe_products.append(row)

    return {
        "brand_policy": {
            "required_value": "无品牌",
            "title_use_brand_name_required": False,
            "keyword_brand_comparison_allowed": False,
            "reason": "当前无品牌资质，安全稳健优先",
        },
        "risk_count": len(risky_products),
        "safe_count": len(safe_products),
        "risky_products": risky_products,
        "safe_products": safe_products,
        "next_actions": [
            "风险商品只允许先做只读确认，不直接改线上标题",
            "标题整改必须同时确认类目属性品牌为无品牌、标题区使用品牌名关闭",
            "没有用户明确确认前，不保存、不发布、不投放、不付款",
        ],
        "ai_policy": dict(AI_POLICY),
    }


def build_no_brand_remediation_plan(product_issue_actions: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """为品牌残留风险商品生成无品牌整改计划。

    本函数只做本地标题清理和安全闸输出；不改线上商品、不保存、不发布。
    """

    audit = build_no_brand_title_audit(product_issue_actions)
    remediation_items: List[Dict[str, Any]] = []
    for product in audit.get("risky_products") or []:
        if not isinstance(product, Mapping):
            continue
        proposed_title = str(product.get("sanitized_title") or "").strip()
        risk_flags = _string_list(product.get("risk_flags"))
        remediation_items.append({
            "action_id": product.get("action_id"),
            "product_id": str(product.get("product_id") or ""),
            "original_title": str(product.get("title") or ""),
            "proposed_title": proposed_title,
            "risk_flags": risk_flags,
            "required_precheck": "只读确认线上品牌字段为无品牌、标题区使用品牌名关闭、当前页为目标商品编辑页",
            "safe_to_auto_save": False,
            "safe_to_auto_apply": False,
            "browser_gate": "ops_publish_preflight_safety 或专用只读页面核验通过后，仍需用户确认才可保存",
            "forbidden_actions": [
                "未确认前不得保存",
                "不得发布商品",
                "不得投放或付款",
                "不得点击立即优化、一键优化、标题托管或销量助推",
                "不得写入任何非无品牌品牌词",
            ],
        })

    return {
        "plan_type": "no_brand_remediation_plan",
        "summary": {
            "risk_count": len(remediation_items),
            "safe_count": _nonnegative_int(audit.get("safe_count")),
            "source_action_count": len([
                action for action in product_issue_actions or []
                if isinstance(action, Mapping)
            ]),
        },
        "browser_readonly_first": True,
        "safe_to_auto_apply": False,
        "remediation_items": remediation_items,
        "safe_products": audit.get("safe_products") or [],
        "allowed_next_actions": [
            "只读打开目标商品编辑页核验品牌字段和标题区使用品牌名状态",
            "本地生成清理品牌词后的标题草案",
            "用户明确确认后，才允许保存当前编辑页这一项动作",
        ],
        "safety_gates": [
            "不调用抖店官方 API",
            "不调用外部 AI 或第三方模型",
            "品牌字段统一无品牌，标题不写品牌词",
            "不自动保存、不发布、不投放、不付款",
            "不自动采购、不备货",
        ],
        "brand_policy": {
            "required_value": "无品牌",
            "title_use_brand_name_required": False,
            "keyword_brand_comparison_allowed": False,
            "reason": "用户无品牌资质，安全稳健优先",
        },
        "ai_policy": dict(AI_POLICY),
    }


def _diagnostic_signals_from_metrics(metrics: Mapping[str, Any]) -> Dict[str, Any]:
    if isinstance(metrics.get("diagnostic_signals"), Mapping):
        return dict(metrics.get("diagnostic_signals") or {})
    if isinstance(metrics.get("diagnosticSignals"), Mapping):
        return dict(metrics.get("diagnosticSignals") or {})
    signal_keys = {
        "missing_main_video_count",
        "missing_spec_image_count",
        "missing_live_replay_count",
        "attribute_optimization_count",
        "risk_product_count",
        "product_count",
        "excellent_product_count",
        "opportunity_keywords",
        "refund_reasons",
    }
    return {key: metrics.get(key) for key in signal_keys if key in metrics}


def _nonnegative_int(value: Any) -> int:
    try:
        return max(int(float(value or 0)), 0)
    except Exception:
        return 0


def _string_list(value: Any) -> List[str]:
    if isinstance(value, str):
        values = [item.strip() for item in value.replace("，", "、").replace(",", "、").split("、")]
    elif isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        values = [str(item or "").strip() for item in value]
    else:
        values = []
    deduped: List[str] = []
    for item in values:
        if item and item not in deduped:
            deduped.append(item)
    return deduped


def _json_list(value: Any) -> List[Any]:
    if isinstance(value, list):
        return value
    if not isinstance(value, str) or not value.strip():
        return []
    try:
        loaded = json.loads(value)
    except json.JSONDecodeError:
        return []
    return loaded if isinstance(loaded, list) else []


def _json_dict(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        loaded = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return dict(loaded) if isinstance(loaded, Mapping) else {}


def _action_id(action: Mapping[str, Any]) -> int:
    return _nonnegative_int(action.get("id") or action.get("action_id") or action.get("actionId"))


def _strategy_snapshot_id(action: Mapping[str, Any]) -> int:
    return _nonnegative_int(
        action.get("strategy_snapshot_id")
        or action.get("strategySnapshotId")
        or action.get("strategy_id")
    )


def _action_status(action: Mapping[str, Any]) -> str:
    return str(action.get("action_status") or action.get("actionStatus") or "open").strip() or "open"


def _action_evidence(row: Mapping[str, Any]) -> Dict[str, Any]:
    evidence = row.get("evidence")
    if isinstance(evidence, Mapping):
        return dict(evidence)
    return _json_dict(row.get("evidence_json"))


def _reconcile_evidence_score(action: Mapping[str, Any]) -> int:
    evidence = _action_evidence(action)
    score = 0
    if evidence.get("mutation_type") == "main_video_upload_only":
        score += 8
    upload_result = evidence.get("upload_result") if isinstance(evidence.get("upload_result"), Mapping) else {}
    if upload_result.get("upload_triggered"):
        score += 2
    if upload_result.get("upload_confirmed"):
        score += 4
    save_gate = evidence.get("save_edit_human_gate") if isinstance(evidence.get("save_edit_human_gate"), Mapping) else {}
    if save_gate.get("ready_for_human_save_confirmation"):
        score += 4
    preflight = evidence.get("latest_preflight") or evidence.get("preflight")
    if isinstance(preflight, Mapping) and preflight.get("ready_for_upload_preflight"):
        score += 1
    return score


def _risk_terms_from_title(title: str) -> List[str]:
    lower_title = str(title or "").lower()
    terms = []
    for term in ("songmu", "淞木", "kikisocks"):
        if term.lower() in lower_title:
            terms.append(term)
    return list(dict.fromkeys(terms))


def build_strategy_action_reconcile_plan(
    product_issue_actions: Sequence[Mapping[str, Any]],
    latest_strategy_snapshot_id: Optional[int] = None,
) -> Dict[str, Any]:
    """对齐重复诊断待办状态，避免刷新诊断页后重复 open。"""

    actions = [dict(action) for action in product_issue_actions or [] if isinstance(action, Mapping)]
    snapshot_ids = [_strategy_snapshot_id(action) for action in actions if _strategy_snapshot_id(action) > 0]
    latest_id = _nonnegative_int(latest_strategy_snapshot_id) or (max(snapshot_ids) if snapshot_ids else 0)
    latest_actions = [
        action for action in actions
        if latest_id > 0 and _strategy_snapshot_id(action) == latest_id
    ]

    prior_by_product: Dict[str, List[Dict[str, Any]]] = {}
    for action in actions:
        product_id = str(action.get("product_id") or action.get("productId") or "").strip()
        if not product_id:
            continue
        if latest_id and _strategy_snapshot_id(action) >= latest_id:
            continue
        prior_by_product.setdefault(product_id, []).append(action)

    status_priority = {"in_progress": 4, "blocked": 3, "done": 2, "skipped": 1, "open": 0}
    local_updates: List[Dict[str, Any]] = []
    safe_open_actions: List[Dict[str, Any]] = []
    brand_risk_actions: List[Dict[str, Any]] = []

    for action in latest_actions:
        action_id = _action_id(action)
        product_id = str(action.get("product_id") or action.get("productId") or "").strip()
        title = str(action.get("title") or "")
        current_status = _action_status(action)
        if current_status != "open":
            continue

        audit = audit_no_brand_title_text(title)
        if audit.get("has_risk"):
            risk_terms = _risk_terms_from_title(title)
            update = {
                "action_id": action_id,
                "product_id": product_id,
                "from_status": current_status,
                "recommended_status": "blocked",
                "reason": "brand_residue",
                "risk_flags": _string_list(audit.get("risk_flags")),
                "risk_terms": risk_terms,
                "note": "标题存在品牌残留，只允许先只读核验线上品牌字段并生成无品牌整改方案",
                "evidence": {
                    "strategy_snapshot_id": latest_id,
                    "product_id": product_id,
                    "brand_policy": "无品牌",
                    "risk_flags": _string_list(audit.get("risk_flags")),
                    "risk_terms": risk_terms,
                    "sanitized_title": str(audit.get("sanitized_title") or ""),
                    "no_save": True,
                    "no_publish": True,
                    "no_ad_or_payment": True,
                },
            }
            local_updates.append(update)
            brand_risk_actions.append(update)
            continue

        inheritable = [
            prior for prior in prior_by_product.get(product_id, [])
            if _action_status(prior) in {"blocked", "in_progress", "done", "skipped"}
        ]
        inheritable.sort(
            key=lambda item: (
                status_priority.get(_action_status(item), 0),
                _reconcile_evidence_score(item),
                _strategy_snapshot_id(item),
                _action_id(item),
            ),
            reverse=True,
        )
        if inheritable:
            prior = inheritable[0]
            prior_evidence = _action_evidence(prior)
            prior_status = _action_status(prior)
            prior_note = str(prior.get("action_note") or prior.get("note") or "").strip()
            if prior_status == "blocked":
                note = "继承历史待办阻塞：供应商/同款素材/无品牌凭证或成本证据未满足"
                if prior_note:
                    note = f"{note}；历史备注：{prior_note}"
            elif prior_status == "in_progress":
                note = f"继承历史待办进行中状态：{prior_note or '等待当前安全闸完成'}"
            else:
                note = f"继承历史待办状态：{prior_status}"
                if prior_note:
                    note = f"{note}；历史备注：{prior_note}"
            local_updates.append({
                "action_id": action_id,
                "product_id": product_id,
                "from_status": current_status,
                "recommended_status": prior_status,
                "reason": "duplicate_product_inherits_prior_status",
                "inherited_from_action_id": _action_id(prior),
                "inherited_from_strategy_snapshot_id": _strategy_snapshot_id(prior),
                "note": note,
                "evidence": {
                    **prior_evidence,
                    "strategy_snapshot_id": latest_id,
                    "product_id": product_id,
                    "inherited_from_action_id": _action_id(prior),
                    "inherited_status": prior_status,
                    "brand_policy": "无品牌",
                    "no_shop_mutation": True,
                    "no_save": True,
                    "no_publish": True,
                    "no_ad_or_payment": True,
                },
            })
            continue

        safe_open_actions.append({
            "action_id": action_id,
            "product_id": product_id,
            "title": title,
            "recent_30d_sales": _nonnegative_int(action.get("recent_30d_sales") or action.get("recent30dSales")),
            "issues": _string_list(action.get("issues") or _json_list(action.get("issues_json"))),
            "recommended_next_action": "只读核验素材缺口、SKU/详情承接和无品牌证据后再进入人工安全闸",
        })

    return {
        "plan_type": "strategy_action_reconcile_plan",
        "latest_strategy_snapshot_id": latest_id,
        "source_action_count": len(actions),
        "latest_action_count": len(latest_actions),
        "local_ledger_updates": local_updates,
        "update_count": len(local_updates),
        "brand_risk_actions": brand_risk_actions,
        "safe_open_actions": safe_open_actions,
        "safe_open_count": len(safe_open_actions),
        "safe_to_shop_mutation": False,
        "safe_to_auto_save": False,
        "safe_to_auto_apply_platform": False,
        "allowed_local_action": "仅允许写入本地 ops_product_issue_actions 状态和事件",
        "forbidden_actions": [
            "不得点击立即优化、一键优化、标题托管或销量助推",
            "不得保存、发布、投放、付款或采购",
            "不得调用抖店官方 API",
            "不得调用外部 AI 或第三方模型",
        ],
        "brand_policy": {
            "required_value": "无品牌",
            "title_use_brand_name_required": False,
            "keyword_brand_comparison_allowed": False,
            "reason": "用户无品牌资质，安全稳健优先",
        },
        "ai_policy": dict(AI_POLICY),
    }


def _match_text(value: Any) -> str:
    raw = str(value or "").lower()
    kept = []
    for char in raw:
        if char.isalnum() or "\u4e00" <= char <= "\u9fff":
            kept.append(char)
    return "".join(kept)


def _similarity_of_normalized(left_text: str, right_text: str) -> float:
    """对**已经过 `_match_text` 归一化**的两串文本算相似度。

    单独拆出来是为了让批量匹配能把「归一化」提到循环外——`_match_text` 是逐字符循环，
    `SequenceMatcher.ratio()` 是 O(L²)，在 n×m 的双层循环里重复归一化同一侧是纯浪费。
    """
    if not left_text or not right_text:
        return 0.0
    return round(SequenceMatcher(None, left_text, right_text).ratio(), 4)


def _title_similarity(left: Any, right: Any) -> float:
    return _similarity_of_normalized(_match_text(left), _match_text(right))


def build_product_record_mappings(
    shop_products: Sequence[Mapping[str, Any]],
    local_records: Sequence[Mapping[str, Any]],
    min_confidence: float = 0.72,
) -> List[Dict[str, Any]]:
    """Map browser-observed shop products to local Records by conservative title similarity."""
    threshold = max(min(float(min_confidence or 0.72), 1.0), 0.0)
    mappings: List[Dict[str, Any]] = []
    normalized_records = []
    for record in local_records:
        record_title = str(record.get("title") or "")
        normalized_records.append({
            "record_id": record.get("record_id") or record.get("id"),
            "record_title": record_title,
            "record_path": str(record.get("path") or ""),
            # 归一化只做一次：原来在内层循环里对同一条 record 标题反复 _match_text
            "record_match_text": _match_text(record_title),
        })

    for product in shop_products:
        product_title = str(product.get("title") or "")
        product_match_text = _match_text(product_title)
        best_record: Optional[Dict[str, Any]] = None
        best_score = 0.0
        for record in normalized_records:
            score = _similarity_of_normalized(product_match_text, record["record_match_text"])
            if score > best_score:
                best_score = score
                best_record = record
        matched = bool(best_record and best_score >= threshold)
        mappings.append({
            "action_id": product.get("action_id"),
            "product_id": str(product.get("product_id") or product.get("productId") or ""),
            "title": product_title,
            "record_id": best_record.get("record_id") if matched and best_record else None,
            "record_title": best_record.get("record_title") if matched and best_record else "",
            "record_path": best_record.get("record_path") if matched and best_record else "",
            "confidence": round(best_score, 4),
            "match_status": "matched" if matched else "unmatched",
            "reason": (
                "标题相似度达到自动匹配阈值"
                if matched
                else f"没有达到自动匹配阈值 {threshold:.2f}，不能强行关联本地 Record"
            ),
            "evidence": {
                "best_record_id": best_record.get("record_id") if best_record else None,
                "best_record_title": best_record.get("record_title") if best_record else "",
                "min_confidence": threshold,
                "matcher": "normalized_title_sequence_ratio",
            },
        })
    return mappings


def _action_identifier(action: Mapping[str, Any]) -> Any:
    return action.get("id") or action.get("action_id") or action.get("actionId")


def _mapping_identifier(mapping: Mapping[str, Any]) -> Any:
    return mapping.get("action_id") or mapping.get("actionId")


def _latest_mapping_index(product_record_mappings: Sequence[Mapping[str, Any]]) -> Dict[str, Dict[str, Any]]:
    def mapping_sort_key(mapping: Mapping[str, Any]) -> int:
        try:
            return int(mapping.get("id") or 0)
        except Exception:
            return 0

    indexed: Dict[str, Dict[str, Any]] = {}
    for mapping in sorted(product_record_mappings, key=mapping_sort_key, reverse=True):
        action_id = _mapping_identifier(mapping)
        product_id = str(mapping.get("product_id") or mapping.get("productId") or "").strip()
        for key in (f"action:{action_id}" if action_id not in (None, "") else "", f"product:{product_id}" if product_id else ""):
            if key and key not in indexed:
                indexed[key] = dict(mapping)
    return indexed


def _mapping_for_action(action: Mapping[str, Any], mapping_index: Mapping[str, Mapping[str, Any]]) -> Dict[str, Any]:
    action_id = _action_identifier(action)
    product_id = str(action.get("product_id") or action.get("productId") or "").strip()
    if action_id not in (None, ""):
        matched = mapping_index.get(f"action:{action_id}")
        if isinstance(matched, Mapping):
            return dict(matched)
    if product_id:
        matched = mapping_index.get(f"product:{product_id}")
        if isinstance(matched, Mapping):
            return dict(matched)
    return {}


def _material_required_items(issues: Sequence[str]) -> List[str]:
    issue_text = " ".join(str(item or "") for item in issues)
    required = [
        "main_images",
        "sku_color_images",
        "material_label_or_supplier_composition",
        "sell_unit",
        "goods_cost",
        "shipping_fee",
        "stock_per_color",
        "no_brand_confirmation",
    ]
    if "主图视频" in issue_text:
        required.insert(1, "main_video")
    if "规格图" in issue_text:
        required.insert(3 if "main_video" in required else 2, "spec_image")
    if "main_video" not in required:
        required.insert(1, "main_video")
    if "spec_image" not in required:
        required.insert(3, "spec_image")
    return list(dict.fromkeys(required))


def _material_gap_row(action: Mapping[str, Any], mapping: Mapping[str, Any], risk_flags: Optional[Sequence[str]] = None) -> Dict[str, Any]:
    issues = _string_list(action.get("issues") or _json_list(action.get("issues_json")))
    action_id = _action_identifier(action)
    mapping_status = str(mapping.get("match_status") or mapping.get("matchStatus") or "missing").strip() or "missing"
    mapping_reason = str(mapping.get("reason") or "")
    if not mapping_reason and mapping_status == "missing":
        mapping_reason = "没有最新本地 Record 映射记录，不能直接复用素材"
    title = str(action.get("title") or "").strip()
    row = {
        "action_id": action_id,
        "product_id": str(action.get("product_id") or action.get("productId") or "").strip(),
        "title": title,
        "action_status": action.get("action_status") or action.get("actionStatus"),
        "recent_30d_sales": _nonnegative_int(action.get("recent_30d_sales") or action.get("recent30dSales")),
        "issues": issues,
        "mapping_status": mapping_status,
        "mapping_confidence": float(mapping.get("confidence") or 0),
        "mapping_reason": mapping_reason,
        "safe_to_optimize": False,
        "safe_to_auto_apply": False,
        "required_materials": _material_required_items(issues),
        "missing_evidence": [
            "本地 Record 可信匹配",
            "商品主图/视频/规格图与线上商品一致性",
            "材质成分、售卖单位、成本、运费和库存的真实凭证",
            "品牌字段为无品牌且标题不含品牌词",
        ],
        "collection_brief": {
            "brand_required_value": "无品牌",
            "title_use_brand_name_required": False,
            "collect_main_images": True,
            "collect_main_video": True,
            "collect_sku_color_images": True,
            "collect_spec_image": True,
            "collect_cost_and_shipping": True,
            "collect_stock_per_color": True,
            "collect_material_evidence": True,
        },
        "recommended_next_action": "先采集/导入经人工确认的本地素材，再重新建立 Record 映射和发布前校验",
    }
    if risk_flags:
        row["risk_flags"] = list(risk_flags)
    return row


def build_material_gap_plan(
    product_issue_actions: Sequence[Mapping[str, Any]],
    product_record_mappings: Sequence[Mapping[str, Any]],
    no_brand_audit: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """把商品问题待办和本地 Record 映射转成素材采集计划。

    本函数只做本地规则分流，不复用未匹配素材，不保存、不发布、不投放。
    """

    actions = [dict(action) for action in product_issue_actions if isinstance(action, Mapping)]
    audit = dict(no_brand_audit) if isinstance(no_brand_audit, Mapping) else build_no_brand_title_audit(actions)
    risky_products = audit.get("risky_products") if isinstance(audit.get("risky_products"), Sequence) else []
    risk_by_action: Dict[Any, Dict[str, Any]] = {}
    risk_by_product: Dict[str, Dict[str, Any]] = {}
    for product in risky_products:
        if not isinstance(product, Mapping):
            continue
        action_id = product.get("action_id") or product.get("actionId")
        product_id = str(product.get("product_id") or product.get("productId") or "").strip()
        if action_id not in (None, ""):
            risk_by_action[action_id] = dict(product)
        if product_id:
            risk_by_product[product_id] = dict(product)

    mapping_index = _latest_mapping_index(product_record_mappings)
    blocked_revenue_products: List[Dict[str, Any]] = []
    open_missing_material_products: List[Dict[str, Any]] = []
    brand_risk_products: List[Dict[str, Any]] = []
    active_manual_gate_products: List[Dict[str, Any]] = []
    collection_briefs: List[Dict[str, Any]] = []

    for action in actions:
        status = str(action.get("action_status") or action.get("actionStatus") or "open")
        if status in {"done", "skipped"}:
            continue
        action_id = _action_identifier(action)
        product_id = str(action.get("product_id") or action.get("productId") or "").strip()
        mapping = _mapping_for_action(action, mapping_index)
        mapping_status = str(mapping.get("match_status") or mapping.get("matchStatus") or "missing")
        has_trusted_mapping = mapping_status == "matched" and mapping.get("record_id") not in (None, "")
        risk = risk_by_action.get(action_id) or risk_by_product.get(product_id) or {}
        risk_flags = _string_list(risk.get("risk_flags") or risk.get("riskFlags"))

        if risk:
            risk_row = _material_gap_row(action, mapping, risk_flags=risk_flags)
            risk_row["required_next_action"] = "只读确认品牌字段与标题来源"
            risk_row["recommended_next_action"] = "品牌风险商品先确认线上品牌字段为无品牌、标题区使用品牌名关闭，再生成整改安全闸"
            brand_risk_products.append(risk_row)
            continue

        if status == "in_progress":
            active_row = _material_gap_row(action, mapping)
            active_row["recommended_next_action"] = "当前已有进行中的平台安全闸，继续等待人工确认，不切换到自动素材复用"
            active_manual_gate_products.append(active_row)
            collection_briefs.append(active_row)
            continue

        if has_trusted_mapping:
            continue

        material_row = _material_gap_row(action, mapping)
        if _nonnegative_int(action.get("recent_30d_sales") or action.get("recent30dSales")) > 0:
            material_row["priority_reason"] = "近30天已有销量，但本地素材映射不可信；优先采集素材以恢复可优化路径"
            blocked_revenue_products.append(material_row)
        else:
            material_row["priority_reason"] = "标题暂未命中品牌风险，但缺少可信本地素材映射；排入素材采集队列"
            open_missing_material_products.append(material_row)
        collection_briefs.append(material_row)

    blocked_revenue_products.sort(
        key=lambda row: (-_nonnegative_int(row.get("recent_30d_sales")), _nonnegative_int(row.get("action_id")))
    )
    open_missing_material_products.sort(key=lambda row: _nonnegative_int(row.get("action_id")))
    brand_risk_products.sort(key=lambda row: _nonnegative_int(row.get("action_id")))
    active_manual_gate_products.sort(key=lambda row: _nonnegative_int(row.get("action_id")))
    collection_briefs.sort(
        key=lambda row: (
            0 if row.get("action_id") in {item.get("action_id") for item in blocked_revenue_products} else 1,
            -_nonnegative_int(row.get("recent_30d_sales")),
            _nonnegative_int(row.get("action_id")),
        )
    )

    return {
        "plan_type": "material_gap_plan",
        "primary_focus": "collect_verified_materials",
        "do_not_reuse_unmatched_record": True,
        "summary": {
            "source_action_count": len(actions),
            "blocked_revenue_product_count": len(blocked_revenue_products),
            "brand_risk_product_count": len(brand_risk_products),
            "open_missing_material_product_count": len(open_missing_material_products),
            "active_manual_gate_product_count": len(active_manual_gate_products),
        },
        "blocked_revenue_products": blocked_revenue_products,
        "brand_risk_products": brand_risk_products,
        "open_missing_material_products": open_missing_material_products,
        "active_manual_gate_products": active_manual_gate_products,
        "collection_briefs": collection_briefs,
        "allowed_next_actions": [
            "只采集/导入/核验本地素材",
            "只读复核商品行、品牌字段和标题来源",
            "重新运行本地 Record 映射与发布前校验",
            "需要用户明确确认后才允许保存当前编辑页",
        ],
        "safety_gates": [
            "不调用抖店官方 API",
            "不调用外部 AI 或第三方模型",
            "品牌字段统一无品牌，标题不写品牌词",
            "不强行复用未匹配的本地 Record",
            "不点击立即优化、一键优化、标题托管或销量助推",
            "不保存、不发布、不投放、不付款",
        ],
        "ai_policy": dict(AI_POLICY),
    }


def _float_value(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _scenario_id(value: Mapping[str, Any], index: int) -> str:
    raw = str(value.get("scenario_id") or value.get("scenarioId") or value.get("name") or "").strip()
    return raw or f"scenario_{index}"


def _sourcing_scenario_result(scenario: Mapping[str, Any], index: int) -> Dict[str, Any]:
    sale_price = _money(scenario.get("sale_price") or scenario.get("salePrice") or 0)
    pair_count = max(_nonnegative_int(scenario.get("pair_count") or scenario.get("pairCount") or 1), 1)
    shipping_cost = _money(scenario.get("shipping_cost") or scenario.get("shippingCost") or 0)
    packaging_cost = _money(scenario.get("packaging_cost") or scenario.get("packagingCost") or 0)
    commission_rate = _rate(scenario.get("platform_commission_rate") or scenario.get("platformCommissionRate") or 0)
    platform_commission = _money(sale_price * commission_rate)
    promotion_cost = _money(scenario.get("promotion_cost") or scenario.get("promotionCost") or 0)
    refund_loss = _money(scenario.get("refund_loss") or scenario.get("refundLoss") or 0)
    target_unit_profit = _money(scenario.get("target_unit_profit") or scenario.get("targetUnitProfit") or 0)
    minimum_supplier_cost = _money(
        scenario.get("minimum_supplier_cost_per_pair")
        or scenario.get("minimumSupplierCostPerPair")
        or 0
    )
    fixed_costs = _money(
        shipping_cost
        + packaging_cost
        + platform_commission
        + promotion_cost
        + refund_loss
    )
    max_supplier_cost_total = _money(sale_price - fixed_costs - target_unit_profit)
    max_supplier_cost_per_pair = _money(max_supplier_cost_total / pair_count) if pair_count else 0

    supplier_cost_present = scenario.get("supplier_cost_per_pair") not in (None, "")
    supplier_cost_per_pair = (
        _money(scenario.get("supplier_cost_per_pair") or scenario.get("supplierCostPerPair") or 0)
        if supplier_cost_present
        else None
    )
    supplier_cost_verified = bool(scenario.get("supplier_cost_verified") or scenario.get("supplierCostVerified"))
    exact_material_verified = bool(scenario.get("exact_material_verified") or scenario.get("exactMaterialVerified"))
    no_brand_verified = bool(scenario.get("no_brand_verified") or scenario.get("noBrandVerified"))

    net_profit_per_order: Optional[float] = None
    daily_orders_for_500: Optional[int] = None
    if supplier_cost_per_pair is not None:
        goods_cost_total = _money(supplier_cost_per_pair * pair_count)
        net_profit_per_order = _money(sale_price - fixed_costs - goods_cost_total)
        daily_orders_for_500 = (
            math.ceil(DAILY_NET_PROFIT_TARGET / net_profit_per_order)
            if net_profit_per_order > 0
            else None
        )

    if max_supplier_cost_total <= 0:
        decision = "reject_price_structure"
        reason = "扣除运费、包装、佣金、推广/退款和目标单笔利润后，已无可用采购成本预算"
    elif minimum_supplier_cost and max_supplier_cost_per_pair < minimum_supplier_cost:
        decision = "reject_price_structure"
        reason = f"可承受单双采购成本 {max_supplier_cost_per_pair:.2f} 低于最低可采成本 {minimum_supplier_cost:.2f}"
    elif supplier_cost_per_pair is None:
        decision = "needs_supplier_quote"
        reason = "缺少供应商真实成本，不能判断是否值得采购"
    elif not supplier_cost_verified or not exact_material_verified or not no_brand_verified:
        decision = "needs_evidence"
        reason = "供应商成本、同款素材或无品牌口径尚未全部验证"
    elif net_profit_per_order is None or net_profit_per_order <= 0:
        decision = "reject_supplier_quote"
        reason = "按已填供应商成本测算单笔净利不为正"
    elif daily_orders_for_500 and daily_orders_for_500 > 120:
        decision = "candidate_for_test_order_not_scale"
        reason = "单笔净利为正，但达到 500 元日净利所需订单数过高，只能小单验证"
    else:
        decision = "candidate_for_test_order"
        reason = "同款、无品牌和供应商成本均已验证，且单笔净利可支撑小单测试"

    return {
        "scenario_id": _scenario_id(scenario, index),
        "sale_price": sale_price,
        "pair_count": pair_count,
        "shipping_cost": shipping_cost,
        "packaging_cost": packaging_cost,
        "platform_commission_rate": commission_rate,
        "platform_commission": platform_commission,
        "promotion_cost": promotion_cost,
        "refund_loss": refund_loss,
        "target_unit_profit": target_unit_profit,
        "minimum_supplier_cost_per_pair": minimum_supplier_cost,
        "fixed_costs_before_goods": fixed_costs,
        "max_supplier_cost_total": max_supplier_cost_total,
        "max_supplier_cost_per_pair": max_supplier_cost_per_pair,
        "supplier_cost_per_pair": supplier_cost_per_pair,
        "supplier_cost_verified": supplier_cost_verified,
        "exact_material_verified": exact_material_verified,
        "no_brand_verified": no_brand_verified,
        "net_profit_per_order": net_profit_per_order,
        "daily_orders_for_500": daily_orders_for_500,
        "decision": decision,
        "reason": reason,
    }


def build_sourcing_profit_gate(
    product: Mapping[str, Any],
    scenarios: Sequence[Mapping[str, Any]],
    target_net_profit: float = DAILY_NET_PROFIT_TARGET,
) -> Dict[str, Any]:
    """采购前利润闸。

    只根据本地可见价格、成本假设和供应商证据做规则测算；不下单、不付款、不改店铺。
    """

    product_row = dict(product or {})
    scenario_results = [
        _sourcing_scenario_result(scenario, index)
        for index, scenario in enumerate(scenarios or [], start=1)
        if isinstance(scenario, Mapping)
    ]
    viable = [
        item for item in scenario_results
        if item.get("decision") in {"candidate_for_test_order", "candidate_for_test_order_not_scale"}
    ]
    quote_needed = [item for item in scenario_results if item.get("decision") == "needs_supplier_quote"]
    rejected_low_price = any(
        item.get("decision") == "reject_price_structure"
        and _money(item.get("sale_price")) <= _money(product_row.get("observed_sale_price") or product_row.get("observedSalePrice") or 0)
        for item in scenario_results
    )

    if viable:
        recommended_mode = "verified_bundle_sample_order"
    elif quote_needed:
        recommended_mode = "supplier_quote_first"
    elif rejected_low_price:
        recommended_mode = "bundle_or_higher_aov_only"
    else:
        recommended_mode = "hold_until_material_and_cost_verified"

    return {
        "gate_type": "sourcing_profit_gate",
        "target_net_profit": _money(target_net_profit),
        "product": {
            "action_id": product_row.get("action_id") or product_row.get("actionId") or product_row.get("id"),
            "product_id": str(product_row.get("product_id") or product_row.get("productId") or ""),
            "title": str(product_row.get("title") or ""),
            "observed_sale_price": _money(product_row.get("observed_sale_price") or product_row.get("observedSalePrice") or 0),
            "recent_30d_sales": _nonnegative_int(product_row.get("recent_30d_sales") or product_row.get("recent30dSales")),
        },
        "recommended_sourcing_mode": recommended_mode,
        "safe_to_purchase_stock": False,
        "safe_to_auto_purchase": False,
        "scenarios": scenario_results,
        "allowed_next_actions": [
            "向供应商索取同款实物图、主图视频、SKU 图、材质成分和成本报价",
            "只允许小单测试，且必须先核验同款、无品牌、成本、运费和库存",
            "组合装或提高客单价后再计算 500 元日净利所需订单数",
        ],
        "safety_gates": [
            "不调用抖店官方 API",
            "不调用外部 AI 或第三方模型",
            "不自动下单采购、不付款",
            "不保存、不发布、不投放",
            "未验证同款素材和真实成本前不备货",
        ],
        "brand_policy": {
            "required_value": "无品牌",
            "title_use_brand_name_required": False,
            "reason": "用户无品牌资质，安全稳健优先",
        },
        "ai_policy": dict(AI_POLICY),
    }


def _supplier_target_cost_ceiling(sourcing_profit_gate: Mapping[str, Any]) -> float:
    ceilings: List[float] = []
    for scenario in sourcing_profit_gate.get("scenarios") or []:
        if not isinstance(scenario, Mapping):
            continue
        ceiling = _money(scenario.get("max_supplier_cost_per_pair") or scenario.get("maxSupplierCostPerPair") or 0)
        if ceiling > 0:
            ceilings.append(ceiling)
    return max(ceilings) if ceilings else 0


SOCK_FEATURE_TOKENS: Dict[str, tuple] = {
    "波点": ("波点", "圆点", "点点"),
    "中筒": ("中筒", "中统", "长筒"),
    "蕾丝花边": ("蕾丝", "花边"),
    "堆堆袜": ("堆堆",),
    "防臭": ("防臭", "抗菌"),
    "春夏薄款": ("春夏", "夏季", "薄款"),
    "甜美韩系": ("甜美", "韩系", "韩版"),
}


def _required_sock_features(title: str) -> List[str]:
    features: List[str] = []
    for label, tokens in SOCK_FEATURE_TOKENS.items():
        if any(token in title for token in tokens):
            features.append(label)
    return features or ["同款外观", "同款 SKU", "同款售卖单位"]


def _candidate_text(candidate: Mapping[str, Any]) -> str:
    values: List[str] = []
    for key in ("title", "description", "material_evidence", "materialEvidence", "source_brand_text", "sourceBrandText"):
        value = candidate.get(key)
        if value:
            values.append(str(value))
    colors = candidate.get("stock_colors") or candidate.get("stockColors")
    if isinstance(colors, Sequence) and not isinstance(colors, (str, bytes, bytearray)):
        values.extend(str(item) for item in colors)
    return " ".join(values)


def _feature_present(feature: str, text: str) -> bool:
    tokens = SOCK_FEATURE_TOKENS.get(feature, (feature,))
    scoped_negative_markers = (
        "未确认",
        "未提供",
        "未给",
        "未验证",
        "缺少",
        "没有",
        "不含",
        "不是",
        "非同款",
        "待确认",
    )
    direct_negative_prefixes = ("无",)
    for token in tokens:
        start = 0
        while True:
            index = text.find(token, start)
            if index < 0:
                break
            scoped_context = text[max(0, index - 48):index]
            direct_context = text[max(0, index - 6):index]
            scoped_negative = any(marker in scoped_context for marker in scoped_negative_markers)
            direct_negative = (
                any(marker in direct_context for marker in direct_negative_prefixes)
                and not any(safe_marker in direct_context for safe_marker in ("无品牌", "无牌"))
            )
            if not scoped_negative and not direct_negative:
                return True
            start = index + len(token)
    return False


def _evaluate_supplier_candidate(
    candidate: Mapping[str, Any],
    required_features: Sequence[str],
    target_ceiling: float,
) -> Dict[str, Any]:
    text = _candidate_text(candidate)
    matched_features = [feature for feature in required_features if _feature_present(feature, text)]
    missing_features = [feature for feature in required_features if feature not in matched_features]
    cost = _money(candidate.get("supplier_cost_per_pair") or candidate.get("supplierCostPerPair") or 0)
    cost_within_ceiling = bool(cost > 0 and target_ceiling > 0 and cost <= target_ceiling)
    no_brand_confirmed = bool(candidate.get("no_brand_confirmed") or candidate.get("noBrandConfirmed"))
    exact_material_confirmed = bool(candidate.get("exact_material_confirmed") or candidate.get("exactMaterialConfirmed"))
    shipping_cost_verified = bool(candidate.get("shipping_cost_verified") or candidate.get("shippingCostVerified"))
    moq_pairs = _nonnegative_int(candidate.get("moq_pairs") or candidate.get("moqPairs"))
    source_brand_text = str(candidate.get("source_brand_text") or candidate.get("sourceBrandText") or "").strip()
    material_evidence = str(candidate.get("material_evidence") or candidate.get("materialEvidence") or "").strip()

    risk_flags: List[str] = []
    if missing_features:
        risk_flags.append("missing_required_features")
    if source_brand_text or not no_brand_confirmed:
        risk_flags.append("brand_risk")
    if not cost_within_ceiling:
        risk_flags.append("cost_over_or_missing")
    if not exact_material_confirmed or not material_evidence:
        risk_flags.append("material_evidence_missing")
    if not shipping_cost_verified:
        risk_flags.append("shipping_cost_unverified")
    if moq_pairs <= 0 or moq_pairs > 30:
        risk_flags.append("moq_too_high_or_missing")

    score = 0
    if required_features:
        score += round((len(matched_features) / len(required_features)) * 35)
    if cost_within_ceiling:
        score += 20
    if no_brand_confirmed and not source_brand_text:
        score += 15
    if exact_material_confirmed and material_evidence:
        score += 15
    if shipping_cost_verified:
        score += 8
    if 0 < moq_pairs <= 30:
        score += 7

    if not risk_flags:
        decision = "sample_order_candidate"
    elif "missing_required_features" in risk_flags or "brand_risk" in risk_flags:
        decision = "reject_direct_reuse"
    elif "cost_over_or_missing" in risk_flags:
        decision = "needs_supplier_quote"
    else:
        decision = "needs_evidence"

    return {
        "candidate_id": candidate.get("candidate_id") or candidate.get("candidateId") or candidate.get("id"),
        "title": str(candidate.get("title") or ""),
        "supplier_cost_per_pair": cost,
        "target_max_supplier_cost_per_pair": target_ceiling,
        "cost_within_ceiling": cost_within_ceiling,
        "matched_features": matched_features,
        "missing_features": missing_features,
        "no_brand_confirmed": no_brand_confirmed,
        "exact_material_confirmed": exact_material_confirmed,
        "shipping_cost_verified": shipping_cost_verified,
        "material_evidence": material_evidence,
        "moq_pairs": moq_pairs,
        "stock_colors": _string_list(candidate.get("stock_colors") or candidate.get("stockColors")),
        "risk_flags": risk_flags,
        "score": score,
        "decision": decision,
    }


def build_supplier_quote_plan(
    product: Mapping[str, Any],
    sourcing_profit_gate: Mapping[str, Any],
    supplier_candidates: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    """供应商询价与同款评分计划。

    只生成询价清单和候选评分；不采购、不付款、不保存、不发布。
    """

    product_row = dict(product or {})
    title = str(product_row.get("title") or "").strip()
    product_id = str(product_row.get("product_id") or product_row.get("productId") or "").strip()
    required_features = _required_sock_features(title)
    target_ceiling = _supplier_target_cost_ceiling(sourcing_profit_gate)
    candidate_evaluations = [
        _evaluate_supplier_candidate(candidate, required_features, target_ceiling)
        for candidate in supplier_candidates or []
        if isinstance(candidate, Mapping)
    ]
    candidate_evaluations.sort(key=lambda item: (-_nonnegative_int(item.get("score")), str(item.get("candidate_id") or "")))
    purchase_ready = any(item.get("decision") == "sample_order_candidate" for item in candidate_evaluations)
    core_query = " ".join(feature for feature in ["波点中筒袜", "蕾丝花边", "堆堆袜", "防臭"] if feature)

    return {
        "plan_type": "supplier_quote_plan",
        "action_id": product_row.get("action_id") or product_row.get("actionId") or product_row.get("id"),
        "product_id": product_id,
        "title": title,
        "target_max_supplier_cost_per_pair": target_ceiling,
        "required_same_style_features": required_features,
        "search_queries": [
            core_query,
            "波点 蕾丝花边 中筒 袜子 女 春夏 薄款",
            "防臭 中筒 堆堆袜 女 波点 花边 供应商",
        ],
        "quote_questions": [
            "是否支持无品牌供货？发票/吊牌/包装/详情素材中能否不出现任何品牌词？",
            f"是否为同款：{'、'.join(required_features)}？请提供实拍主图、主图视频、SKU 图和细节图。",
            f"若做组合装，单双色采购成本能否低于 {target_ceiling:.2f} 元？请说明阶梯价、起订量和颜色库存。",
            "请提供材质成分凭证；防臭、抗菌、100%棉等功能/材质词必须有水洗标、吊牌、供应商资料或质检报告。",
            "请确认发货地、揽收时效、退换货规则、运费实价、缺货替换规则和补货周期。",
        ],
        "candidate_evaluations": candidate_evaluations,
        "has_purchase_ready_candidate": purchase_ready,
        "safe_to_auto_purchase": False,
        "allowed_next_actions": [
            "只允许询价、索要素材和核验证据",
            "候选达到 sample_order_candidate 后仍只允许人工确认小单测试",
            "把供应商报价导入采购利润闸复算，再决定是否备货",
        ],
        "safety_gates": [
            "不调用抖店官方 API",
            "不调用外部 AI 或第三方模型",
            "不自动下单采购、不付款",
            "不保存、不发布、不投放",
            "未验证无品牌、同款素材和真实成本前不备货",
        ],
        "brand_policy": {
            "required_value": "无品牌",
            "title_use_brand_name_required": False,
        },
        "ai_policy": dict(AI_POLICY),
    }


def _quote_profit_projection(
    scenario: Mapping[str, Any],
    supplier_cost_per_pair: float,
    target_net_profit: float,
) -> Dict[str, Any]:
    sale_price = _money(scenario.get("sale_price") or scenario.get("salePrice") or 0)
    pair_count = max(_nonnegative_int(scenario.get("pair_count") or scenario.get("pairCount") or 1), 1)
    fixed_costs = _money(scenario.get("fixed_costs_before_goods") or scenario.get("fixedCostsBeforeGoods") or 0)
    if fixed_costs <= 0:
        shipping_cost = _money(scenario.get("shipping_cost") or scenario.get("shippingCost") or 0)
        packaging_cost = _money(scenario.get("packaging_cost") or scenario.get("packagingCost") or 0)
        commission = _money(
            scenario.get("platform_commission")
            or scenario.get("platformCommission")
            or sale_price * _rate(scenario.get("platform_commission_rate") or scenario.get("platformCommissionRate") or 0)
        )
        promotion_cost = _money(scenario.get("promotion_cost") or scenario.get("promotionCost") or 0)
        refund_loss = _money(scenario.get("refund_loss") or scenario.get("refundLoss") or 0)
        fixed_costs = _money(shipping_cost + packaging_cost + commission + promotion_cost + refund_loss)
    goods_cost_total = _money(_money(supplier_cost_per_pair) * pair_count)
    net_profit_per_order = _money(sale_price - fixed_costs - goods_cost_total)
    daily_orders_for_500 = (
        math.ceil(_money(target_net_profit) / net_profit_per_order)
        if net_profit_per_order > 0
        else None
    )
    target_unit_profit = _money(scenario.get("target_unit_profit") or scenario.get("targetUnitProfit") or 0)
    if net_profit_per_order <= 0:
        decision = "reject_negative_profit"
    elif target_unit_profit and net_profit_per_order < target_unit_profit:
        decision = "positive_but_below_target_unit_profit"
    else:
        decision = "supports_profit_test"
    return {
        "scenario_id": _scenario_id(scenario, 1),
        "sale_price": sale_price,
        "pair_count": pair_count,
        "fixed_costs_before_goods": fixed_costs,
        "supplier_cost_per_pair": _money(supplier_cost_per_pair),
        "goods_cost_total": goods_cost_total,
        "net_profit_per_order": net_profit_per_order,
        "daily_orders_for_500": daily_orders_for_500,
        "target_unit_profit": target_unit_profit,
        "decision": decision,
    }


def build_supplier_quote_intake(
    product: Mapping[str, Any],
    sourcing_profit_gate: Mapping[str, Any],
    supplier_quote: Mapping[str, Any],
    target_net_profit: float = DAILY_NET_PROFIT_TARGET,
) -> Dict[str, Any]:
    """把供应商回传报价转成样品/备货判定。

    只做本地规则判断和利润测算；不采购、不付款、不保存、不发布、不投放。
    """

    product_row = dict(product or {})
    quote_row = dict(supplier_quote or {})
    title = str(product_row.get("title") or "").strip()
    product_id = str(product_row.get("product_id") or product_row.get("productId") or "").strip()
    required_features = _required_sock_features(title)
    target_ceiling = _supplier_target_cost_ceiling(sourcing_profit_gate)
    candidate_evaluation = _evaluate_supplier_candidate(quote_row, required_features, target_ceiling)
    supplier_cost = _money(candidate_evaluation.get("supplier_cost_per_pair") or 0)
    scenarios = [
        dict(scenario)
        for scenario in (sourcing_profit_gate.get("scenarios") or [])
        if isinstance(scenario, Mapping)
    ]
    profit_projections = [
        _quote_profit_projection(scenario, supplier_cost, target_net_profit)
        for scenario in scenarios
        if supplier_cost > 0
    ]
    profit_projections.sort(key=lambda item: (-_money(item.get("net_profit_per_order")), str(item.get("scenario_id") or "")))
    best_projection = profit_projections[0] if profit_projections else {}
    candidate_decision = str(candidate_evaluation.get("decision") or "")
    best_positive = _money(best_projection.get("net_profit_per_order", 0)) > 0

    if candidate_decision == "sample_order_candidate" and best_positive:
        decision = "ready_for_manual_sample_order"
        recommended_next_action = "只允许用户确认后人工小单测试；样品到货后再核验同款、无品牌包装和材质功能凭证"
    elif candidate_decision == "reject_direct_reuse":
        decision = "reject_quote"
        recommended_next_action = "拒绝直接复用该报价；继续寻找同款、无品牌、低 MOQ 且素材完整的供应商"
    else:
        decision = "needs_better_quote_or_evidence"
        recommended_next_action = "继续补供应商成本、运费、MOQ、同款实拍、主图视频、SKU 图、材质/功能证据和无品牌确认"

    moq_pairs = _nonnegative_int(candidate_evaluation.get("moq_pairs"))
    max_pairs = min(moq_pairs, 30) if decision == "ready_for_manual_sample_order" and moq_pairs > 0 else 0
    estimated_sample_cost = _money(max_pairs * supplier_cost) if max_pairs else 0.0
    stock_colors = _string_list(candidate_evaluation.get("stock_colors"))

    return {
        "intake_type": "supplier_quote_intake",
        "action_id": product_row.get("action_id") or product_row.get("actionId") or product_row.get("id"),
        "product_id": product_id,
        "title": title,
        "target_net_profit": _money(target_net_profit),
        "target_max_supplier_cost_per_pair": target_ceiling,
        "decision": decision,
        "recommended_next_action": recommended_next_action,
        "candidate_evaluation": candidate_evaluation,
        "profit_projections": profit_projections,
        "best_profit_projection": best_projection,
        "recommended_sample_order": {
            "enabled": decision == "ready_for_manual_sample_order",
            "max_pairs": max_pairs,
            "estimated_goods_cost": estimated_sample_cost,
            "stock_colors": stock_colors,
            "note": "只用于人工确认小单测试，不是自动采购或批量备货授权",
        },
        "requires_user_confirmation": decision == "ready_for_manual_sample_order",
        "safe_to_auto_purchase": False,
        "safe_to_bulk_stock": False,
        "allowed_next_actions": [
            "只记录供应商报价和证据",
            "只在人工确认后做小单样品测试",
            "样品到货后复核同款、无品牌包装、材质/功能证据和真实发货质量",
            "通过真实订单和退款售后数据复算 500 元日净利路径",
        ],
        "safety_gates": [
            "不调用抖店官方 API",
            "不调用外部 AI 或第三方模型",
            "品牌字段统一无品牌，标题不写品牌词",
            "不自动采购、不付款、不批量备货",
            "不保存、不发布、不投放",
        ],
        "brand_policy": {
            "required_value": "无品牌",
            "title_use_brand_name_required": False,
            "reason": "用户无品牌资质，安全稳健优先",
        },
        "ai_policy": dict(AI_POLICY),
    }


def _ops_stage_from_metrics(metrics: Mapping[str, Any]) -> str:
    exposure_count = _nonnegative_int(metrics.get("product_exposure_count"))
    click_count = _nonnegative_int(metrics.get("product_click_count"))
    orders_count = _nonnegative_int(metrics.get("orders_count"))
    if click_count > 0 and orders_count == 0:
        return "detail_conversion_bottleneck"
    if exposure_count > 0 and click_count == 0:
        return "card_click_bottleneck"
    if orders_count > 0:
        return "profit_validation"
    return "need_more_signal"


def _ops_goal_status(metrics: Mapping[str, Any], target_net_profit: float) -> str:
    net_profit_verified = bool(metrics.get("net_profit_verified", False))
    net_profit = _money(metrics.get("net_profit", 0))
    if not net_profit_verified:
        return "not_verified"
    if net_profit >= _money(target_net_profit):
        return "verified_achieved"
    return "verified_below_target"


def _plan_rows(plan: Mapping[str, Any], key: str) -> List[Dict[str, Any]]:
    rows = plan.get(key)
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes, bytearray)):
        return []
    return [dict(row) for row in rows if isinstance(row, Mapping)]


def _normalize_supplier_quote_plans(value: Any) -> List[Dict[str, Any]]:
    if isinstance(value, Mapping):
        return [dict(value)]
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [dict(item) for item in value if isinstance(item, Mapping)]
    return []


def _action_ids_from_rows(rows: Sequence[Mapping[str, Any]]) -> List[int]:
    ids: List[int] = []
    for row in rows:
        action_id = _nonnegative_int(row.get("action_id") or row.get("actionId") or row.get("id"))
        if action_id > 0 and action_id not in ids:
            ids.append(action_id)
    return ids


def _task_for_active_manual_gate(row: Mapping[str, Any], priority: int, stage: str) -> Dict[str, Any]:
    action_id = _nonnegative_int(row.get("action_id") or row.get("actionId") or row.get("id"))
    reason = "已有点击但未成交，当前进行中的编辑页安全闸是最近的转化承接动作"
    if stage != "detail_conversion_bottleneck":
        reason = "当前已有进行中的平台安全闸，必须先处理人工确认边界，避免切换动作造成误保存"
    return {
        "task_id": f"request_human_save_confirmation_action_{action_id}" if action_id else "request_human_save_confirmation",
        "task_type": "human_save_confirmation",
        "priority": priority,
        "action_id": action_id or row.get("action_id") or row.get("actionId") or row.get("id"),
        "product_id": str(row.get("product_id") or row.get("productId") or ""),
        "title": str(row.get("title") or ""),
        "reason": reason,
        "allowed_mode": "human_confirmed_single_save_only",
        "allowed_next_action": "用户明确确认后，才允许只保存当前编辑页这一项动作；保存后立即用临时首页 tab 复核经营快照",
        "requires_user_confirmation": True,
        "requires_supplier_evidence": False,
        "safe_to_auto_apply": False,
        "safety_gate": "ops_save_edit_human_gate",
        "forbidden_actions": [
            "未确认前不得保存",
            "不得发布商品",
            "不得投放或付款",
            "不得点击立即优化、一键优化或标题托管",
        ],
    }


def _task_for_supplier_quote(
    row: Mapping[str, Any],
    quote_plan: Mapping[str, Any],
    priority: int,
) -> Dict[str, Any]:
    action_id = _nonnegative_int(row.get("action_id") or row.get("actionId") or row.get("id"))
    recent_sales = _nonnegative_int(row.get("recent_30d_sales") or row.get("recent30dSales"))
    target_cost = _money(quote_plan.get("target_max_supplier_cost_per_pair") or quote_plan.get("targetMaxSupplierCostPerPair") or 0)
    return {
        "task_id": f"collect_supplier_quotes_action_{action_id}" if action_id else "collect_supplier_quotes",
        "task_type": "supplier_quote_collection",
        "priority": priority,
        "action_id": action_id or row.get("action_id") or row.get("actionId") or row.get("id"),
        "product_id": str(row.get("product_id") or row.get("productId") or ""),
        "title": str(row.get("title") or ""),
        "recent_30d_sales": recent_sales,
        "target_max_supplier_cost_per_pair": target_cost,
        "reason": "近30天已有销量，但同款素材、无品牌口径和供应商成本未形成采购就绪证据",
        "allowed_mode": "supplier_quote_and_evidence_only",
        "allowed_next_action": "只向供应商询价、索要同款实拍/主图视频/SKU 图/材质凭证，并回填采购利润闸复算",
        "requires_user_confirmation": False,
        "requires_supplier_evidence": True,
        "safe_to_auto_apply": False,
        "has_purchase_ready_candidate": bool(quote_plan.get("has_purchase_ready_candidate")),
        "forbidden_actions": [
            "不得自动采购或付款",
            "不得用未匹配素材发布或保存",
            "不得把来源品牌写入标题或属性",
        ],
    }


def _group_task(
    task_id: str,
    task_type: str,
    priority: int,
    rows: Sequence[Mapping[str, Any]],
    allowed_mode: str,
    allowed_next_action: str,
    reason: str,
) -> Dict[str, Any]:
    return {
        "task_id": task_id,
        "task_type": task_type,
        "priority": priority,
        "action_ids": _action_ids_from_rows(rows),
        "product_ids": [str(row.get("product_id") or row.get("productId") or "") for row in rows],
        "count": len(rows),
        "reason": reason,
        "allowed_mode": allowed_mode,
        "allowed_next_action": allowed_next_action,
        "requires_user_confirmation": False,
        "requires_supplier_evidence": task_type == "collect_missing_materials",
        "safe_to_auto_apply": False,
        "forbidden_actions": [
            "不得自动保存、发布、投放或付款",
            "不得点击立即优化、一键优化、标题托管或销量助推",
            "不得写入任何非无品牌品牌词",
        ],
    }


def build_ops_execution_queue(
    metrics: Mapping[str, Any],
    product_issue_actions: Sequence[Mapping[str, Any]],
    material_gap_plan: Optional[Mapping[str, Any]] = None,
    supplier_quote_plan: Optional[Any] = None,
    conversion_experiment_plan: Optional[Mapping[str, Any]] = None,
    target_net_profit: float = DAILY_NET_PROFIT_TARGET,
) -> Dict[str, Any]:
    """生成当天运营执行队列。

    本函数只做本地规则排序和安全闸汇总，不保存、不发布、不投放、不采购。
    """

    metric_row = dict(metrics or {})
    actions = [dict(action) for action in product_issue_actions or [] if isinstance(action, Mapping)]
    stage = str((conversion_experiment_plan or {}).get("stage") or _ops_stage_from_metrics(metric_row))
    gap_plan = (
        dict(material_gap_plan)
        if isinstance(material_gap_plan, Mapping)
        else build_material_gap_plan(actions, [])
    )
    quote_plans = _normalize_supplier_quote_plans(supplier_quote_plan)
    quote_by_action = {
        _nonnegative_int(plan.get("action_id") or plan.get("actionId")): plan
        for plan in quote_plans
        if _nonnegative_int(plan.get("action_id") or plan.get("actionId")) > 0
    }

    tasks: List[Dict[str, Any]] = []
    priority = 1

    active_rows = _plan_rows(gap_plan, "active_manual_gate_products")
    if not active_rows:
        active_rows = [
            action for action in actions
            if str(action.get("action_status") or action.get("actionStatus") or "") == "in_progress"
        ]
    for row in sorted(active_rows, key=lambda item: _nonnegative_int(item.get("action_id") or item.get("id"))):
        tasks.append(_task_for_active_manual_gate(row, priority, stage))
        priority += 1

    blocked_revenue_rows = _plan_rows(gap_plan, "blocked_revenue_products")
    blocked_revenue_rows.sort(
        key=lambda item: (
            -_nonnegative_int(item.get("recent_30d_sales") or item.get("recent30dSales")),
            _nonnegative_int(item.get("action_id") or item.get("id")),
        )
    )
    for row in blocked_revenue_rows:
        action_id = _nonnegative_int(row.get("action_id") or row.get("actionId") or row.get("id"))
        quote_plan = quote_by_action.get(action_id, {})
        if quote_plan and bool(quote_plan.get("has_purchase_ready_candidate")):
            continue
        tasks.append(_task_for_supplier_quote(row, quote_plan, priority))
        priority += 1

    brand_risk_rows = _plan_rows(gap_plan, "brand_risk_products")
    if brand_risk_rows:
        action_ids = _action_ids_from_rows(brand_risk_rows)
        tasks.append(
            _group_task(
                task_id="brand_risk_readonly_check_action_" + "_".join(str(item) for item in action_ids),
                task_type="readonly_brand_risk_check",
                priority=priority,
                rows=brand_risk_rows,
                allowed_mode="readonly_only",
                allowed_next_action="只读确认线上品牌字段为无品牌、标题区使用品牌名关闭，并核对标题来源品牌残留",
                reason="标题或来源信息存在品牌残留风险，不能进入素材复用、保存或优化动作",
            )
        )
        priority += 1

    open_material_rows = _plan_rows(gap_plan, "open_missing_material_products")
    if open_material_rows:
        action_ids = _action_ids_from_rows(open_material_rows)
        tasks.append(
            _group_task(
                task_id="open_missing_material_queue_" + "_".join(str(item) for item in action_ids),
                task_type="collect_missing_materials",
                priority=priority,
                rows=open_material_rows,
                allowed_mode="collect_local_materials_only",
                allowed_next_action="只采集或导入经人工确认的本地素材、成本、运费、库存和无品牌凭证",
                reason="标题暂未命中品牌风险，但缺少可信本地 Record 和素材映射",
            )
        )
        priority += 1

    if not tasks:
        tasks.append({
            "task_id": "sync_next_readonly_snapshot",
            "task_type": "readonly_metrics_sync",
            "priority": priority,
            "reason": "当前没有可执行的素材或保存闸任务，先继续只读同步经营快照",
            "allowed_mode": "readonly_only",
            "allowed_next_action": "使用临时首页 tab 读取下一次经营快照，不改店铺",
            "requires_user_confirmation": False,
            "requires_supplier_evidence": False,
            "safe_to_auto_apply": False,
            "forbidden_actions": ["不得保存、发布、投放、付款或采购"],
        })

    review_metrics = {
        "snapshot_date": str(metric_row.get("snapshot_date") or date.today().isoformat()),
        "orders_count": _nonnegative_int(metric_row.get("orders_count")),
        "product_click_count": _nonnegative_int(metric_row.get("product_click_count")),
        "product_exposure_count": _nonnegative_int(metric_row.get("product_exposure_count")),
        "search_exposure_count": _nonnegative_int(metric_row.get("search_exposure_count")),
        "net_profit": _money(metric_row.get("net_profit", 0)),
        "net_profit_verified": bool(metric_row.get("net_profit_verified", False)),
        "promotion_cost": _money(metric_row.get("promotion_cost", 0)),
    }
    brand_policy = {
        "required_value": "无品牌",
        "title_use_brand_name_required": False,
        "keyword_brand_comparison_allowed": False,
        "reason": "用户无品牌资质，安全稳健优先",
    }

    return {
        "plan_type": "ops_execution_queue",
        "target_net_profit": _money(target_net_profit),
        "goal_status": _ops_goal_status(metric_row, target_net_profit),
        "current_stage": stage,
        "paid_ads_paused": True,
        "safe_to_auto_apply": False,
        "next_snapshot_required": True,
        "review_metrics": review_metrics,
        "primary_queue": sorted(tasks, key=lambda item: (_nonnegative_int(item.get("priority")), str(item.get("task_id") or ""))),
        "safety_gates": [
            "不调用抖店官方 API",
            "不调用外部 AI 或第三方模型",
            "品牌字段统一无品牌，标题不写品牌词",
            "不自动保存、不发布、不投放、不付款",
            "不自动采购、不备货",
            "登录、验证码、付款、投放扣费、最终不可逆确认保留人工安全闸",
        ],
        "brand_policy": brand_policy,
        "no_brand_policy": brand_policy,
        "ai_policy": dict(AI_POLICY),
    }


def _portfolio_orders_from_profit_ladder(evidence: Mapping[str, Any]) -> Optional[int]:
    ladder = evidence.get("profit_ladder_to_500")
    if not isinstance(ladder, Mapping):
        return None
    for key in (
        "target_case_minimum_daily_orders",
        "target_cost_minimum_daily_orders",
        "best_case_minimum_daily_orders",
        "minimum_daily_orders_for_500",
    ):
        value = _nonnegative_int(ladder.get(key))
        if value > 0:
            return value
    return None


def _portfolio_lane_for_action(row: Mapping[str, Any], stage: str) -> Dict[str, Any]:
    action = dict(row or {})
    evidence = _action_evidence(action)
    action_id = _nonnegative_int(action.get("action_id") or action.get("actionId") or action.get("id"))
    title = str(action.get("title") or "")
    note = str(action.get("action_note") or action.get("actionNote") or "")
    status = str(action.get("action_status") or action.get("actionStatus") or "")
    recent_sales = _nonnegative_int(action.get("recent_30d_sales") or action.get("recent30dSales"))
    lower_title = title.lower()
    lower_note = note.lower()

    save_gate = evidence.get("save_edit_human_gate") if isinstance(evidence.get("save_edit_human_gate"), Mapping) else {}
    profit_orders = _portfolio_orders_from_profit_ladder(evidence)
    has_active_save_gate = (
        status == "in_progress"
        or bool(save_gate.get("ready_for_human_save_confirmation"))
        or "等待用户确认保存" in note
    )
    has_brand_risk = (
        "kikisocks" in lower_title
        or "songmu" in lower_title
        or "淞木" in title
        or "品牌残留" in note
        or ("品牌风险" in note and "无品牌" not in note)
    )
    has_material_mapping_gap = (
        "record" in lower_note
        or "素材映射" in note
        or "未找到可信" in note
        or "unmatched" in lower_note
    )

    if has_active_save_gate:
        role = "primary_conversion_candidate"
        readiness = "needs_human_save_confirmation"
        allowed_next_action = "等待用户确认保存当前编辑页；保存后立即只读同步经营快照"
        safety_gate = "ops_save_edit_human_gate"
        priority = 1
    elif has_brand_risk:
        role = "brand_risk_candidate"
        readiness = "readonly_brand_risk_check"
        allowed_next_action = "只读确认线上品牌字段为无品牌、标题区使用品牌名关闭，并清理来源品牌残留"
        safety_gate = "ops_no_brand_remediation_plan"
        priority = 3
    elif status == "blocked" and (recent_sales > 0 or has_material_mapping_gap):
        role = "revenue_foundation_candidate"
        readiness = "needs_supplier_and_material_evidence"
        allowed_next_action = "只采集供应商报价、同款素材、无品牌供货和成本证据，不采购不备货"
        safety_gate = "ops_supplier_quote_plan"
        priority = 2
    else:
        role = "material_collection_candidate"
        readiness = "needs_material_collection"
        allowed_next_action = "只采集本地素材、规格图、售卖单位、成本、库存和无品牌证据"
        safety_gate = "ops_material_gap_plan"
        priority = 4

    # 硬安全闸：上面的分支不会产出 validated_for_scale，任何 lane 都不允许由本地规则
    # 自动判定为可付费放量，必须走人工评审。
    validated_for_scale = False
    return {
        "action_id": action_id,
        "product_id": str(action.get("product_id") or action.get("productId") or ""),
        "title": title,
        "recent_30d_sales": recent_sales,
        "action_status": status,
        "role": role,
        "readiness": readiness,
        "stage": stage,
        "solo_daily_orders_for_500": profit_orders,
        "ready_for_paid_scale": validated_for_scale,
        "safe_to_auto_apply": False,
        "safe_to_auto_upload": False,
        "requires_user_confirmation": readiness == "needs_human_save_confirmation",
        "requires_supplier_evidence": readiness == "needs_supplier_and_material_evidence",
        "allowed_next_action": allowed_next_action,
        "safety_gate": safety_gate,
        "priority": priority,
    }


def build_portfolio_path_to_500(
    metrics: Mapping[str, Any],
    product_issue_actions: Sequence[Mapping[str, Any]],
    target_net_profit: float = DAILY_NET_PROFIT_TARGET,
) -> Dict[str, Any]:
    """把多个商品待办合并成到 500 元日净利的组合路径。

    该函数只做本地规则排序和目标拆解，不保存、不发布、不投放、不采购，也不调用外部服务。
    """

    metric_row = dict(metrics or {})
    stage = _ops_stage_from_metrics(metric_row)
    current_net_profit = _money(metric_row.get("net_profit", 0))
    net_profit_verified = bool(metric_row.get("net_profit_verified", False))
    goal_status = (
        "achieved_verified"
        if net_profit_verified and current_net_profit >= _money(target_net_profit)
        else "not_achieved"
    )

    lanes = [
        _portfolio_lane_for_action(action, stage)
        for action in (product_issue_actions or [])
        if isinstance(action, Mapping)
    ]
    lanes = sorted(lanes, key=lambda lane: (lane["priority"], -_nonnegative_int(lane.get("recent_30d_sales")), lane["action_id"]))
    validated_scale_lane_count = sum(1 for lane in lanes if bool(lane.get("ready_for_paid_scale")))
    ready_for_paid_scale = bool(
        goal_status != "achieved_verified"
        and validated_scale_lane_count > 0
        and net_profit_verified
    )

    blockers: List[str] = []
    if goal_status != "achieved_verified":
        blockers.append("今日经营净利尚未验证达到500元")
    if any(lane["readiness"] == "needs_human_save_confirmation" for lane in lanes):
        blockers.append("等待用户确认保存当前编辑页")
    if validated_scale_lane_count == 0:
        blockers.append("没有可放量的已验证利润通道")
    if any(lane["readiness"] == "needs_supplier_and_material_evidence" for lane in lanes):
        blockers.append("有销量候选仍缺同款素材、无品牌供货和供应商成本证据")

    if lanes and lanes[0]["readiness"] == "needs_human_save_confirmation":
        next_control_point = {
            "action_id": lanes[0]["action_id"],
            "safety_gate": "ops_save_edit_human_gate",
            "required_confirmation": "用户明确确认后，只允许保存当前编辑页这一项动作",
            "after_confirmation": "保存后立即只读核对品牌=无品牌、使用品牌名=false，并同步下一次经营快照",
        }
    elif lanes:
        next_control_point = {
            "action_id": lanes[0]["action_id"],
            "safety_gate": lanes[0]["safety_gate"],
            "required_confirmation": "不触发平台写入；先补证据",
            "after_confirmation": lanes[0]["allowed_next_action"],
        }
    else:
        next_control_point = {
            "action_id": None,
            "safety_gate": "ops_sync_shop_metrics",
            "required_confirmation": "无",
            "after_confirmation": "继续只读同步经营快照和商品诊断",
        }

    brand_policy = {
        "required_value": "无品牌",
        "title_use_brand_name_required": False,
        "keyword_brand_comparison_allowed": False,
        "reason": "用户无品牌资质，安全稳健优先",
    }

    return {
        "plan_type": "portfolio_path_to_500",
        "target_net_profit": _money(target_net_profit),
        "goal_status": goal_status,
        "stage": stage,
        "current_state": {
            "snapshot_id": _nonnegative_int(metric_row.get("id") or metric_row.get("snapshot_id") or metric_row.get("snapshotId")),
            "snapshot_date": str(metric_row.get("snapshot_date") or date.today().isoformat()),
            "net_profit": current_net_profit,
            "net_profit_verified": net_profit_verified,
            "orders_count": _nonnegative_int(metric_row.get("orders_count")),
            "product_exposure_count": _nonnegative_int(metric_row.get("product_exposure_count")),
            "product_click_count": _nonnegative_int(metric_row.get("product_click_count")),
            "search_exposure_count": _nonnegative_int(metric_row.get("search_exposure_count")),
            "promotion_cost": _money(metric_row.get("promotion_cost", 0)),
        },
        "portfolio_lanes": lanes,
        "validated_scale_lane_count": validated_scale_lane_count,
        "ready_for_paid_scale": ready_for_paid_scale,
        "paid_ads_paused": not ready_for_paid_scale,
        "safe_to_auto_apply": False,
        "next_control_point": next_control_point,
        "blockers": list(dict.fromkeys(blockers)),
        "safety_gates": [
            "不调用抖店官方 API",
            "不调用外部 AI 或第三方模型",
            "品牌字段统一无品牌，标题不写品牌词",
            "不自动保存、不发布、不投放、不付款",
            "不自动采购、不批量备货",
            "登录、验证码、付款、投放扣费、最终不可逆确认保留人工安全闸",
        ],
        "brand_policy": brand_policy,
        "no_brand_policy": brand_policy,
        "ai_policy": dict(AI_POLICY),
    }


def _save_gate_status(gate: Mapping[str, Any], saved_confirmed: bool) -> str:
    """人工保存安全闸的三态判定，供保存前后两个复盘接口共用。"""

    ready_for_human_save = bool(gate.get("ready_for_human_save_confirmation"))
    safe_to_auto_save = bool(gate.get("safe_to_auto_save"))
    if saved_confirmed:
        return "save_confirmed_by_human"
    if ready_for_human_save and not safe_to_auto_save:
        return "awaiting_human_save_confirmation"
    return "save_gate_not_ready"


def build_first_order_decision_matrix(
    baseline_metrics: Mapping[str, Any],
    current_metrics: Mapping[str, Any],
    action: Optional[Mapping[str, Any]] = None,
    save_gate: Optional[Mapping[str, Any]] = None,
    target_net_profit: float = DAILY_NET_PROFIT_TARGET,
    saved_confirmed: bool = False,
) -> Dict[str, Any]:
    """生成保存当前编辑页后的首单复盘决策矩阵。

    该函数只做本地规则判断，不保存、不发布、不投放、不付款，也不调用外部服务。
    """

    baseline = dict(baseline_metrics or {})
    current = dict(current_metrics or {})
    action_row = dict(action or {})
    gate = dict(save_gate or {})
    precondition_status = _save_gate_status(gate, saved_confirmed)

    baseline_state = {
        "snapshot_id": _nonnegative_int(baseline.get("id") or baseline.get("snapshot_id") or baseline.get("snapshotId")),
        "product_exposure_count": _nonnegative_int(baseline.get("product_exposure_count")),
        "product_click_count": _nonnegative_int(baseline.get("product_click_count")),
        "orders_count": _nonnegative_int(baseline.get("orders_count")),
        "net_profit": _money(baseline.get("net_profit", 0)),
        "net_profit_verified": bool(baseline.get("net_profit_verified", False)),
    }
    current_state = {
        "snapshot_id": _nonnegative_int(current.get("id") or current.get("snapshot_id") or current.get("snapshotId")),
        "product_exposure_count": _nonnegative_int(current.get("product_exposure_count")),
        "product_click_count": _nonnegative_int(current.get("product_click_count")),
        "orders_count": _nonnegative_int(current.get("orders_count")),
        "net_profit": _money(current.get("net_profit", 0)),
        "net_profit_verified": bool(current.get("net_profit_verified", False)),
    }
    delta = {
        "product_exposure_count": current_state["product_exposure_count"] - baseline_state["product_exposure_count"],
        "product_click_count": current_state["product_click_count"] - baseline_state["product_click_count"],
        "orders_count": current_state["orders_count"] - baseline_state["orders_count"],
        "net_profit": _money(current_state["net_profit"] - baseline_state["net_profit"]),
    }

    blockers: List[str] = []
    next_actions: List[str] = []
    requires_profit_validation = False

    if not saved_confirmed:
        decision = "wait_for_human_save"
        next_actions.append("等待用户确认保存当前编辑页")
        blockers.append("等待用户确认保存当前编辑页")
    elif current_state["orders_count"] > 0 and not current_state["net_profit_verified"]:
        decision = "profit_validation_required"
        requires_profit_validation = True
        next_actions.append("同步订单明细、成本、运费、佣金、推广费、退款和售后损失")
        blockers.append("net_profit_verified=true 后才允许评估放量")
    elif current_state["net_profit_verified"] and current_state["net_profit"] >= _money(target_net_profit):
        decision = "target_verified"
        next_actions.append("记录达标快照，复核订单、售后和推广消耗后再考虑稳定放量")
    elif delta["product_click_count"] > 0 and current_state["orders_count"] == 0:
        decision = "conversion_bottleneck_after_save"
        next_actions.append("复核详情页前半段、SKU、售价、运费和售后承诺")
        next_actions.append("补真实材质/售卖单位证据后再判断是否上传规格图或详情图")
        blockers.append("订单仍为0，不能进入付费放量")
    elif delta["product_exposure_count"] > 0 and delta["product_click_count"] <= 0:
        decision = "card_click_bottleneck_after_save"
        next_actions.append("复核商品卡首图、标题关键词、价格展示和主图视频首帧")
        blockers.append("曝光增加但点击未增加，不能进入付费放量")
    else:
        decision = "need_more_signal_after_save"
        next_actions.append("继续使用临时首页 tab 只读同步下一次经营快照")
        blockers.append("保存后曝光、点击和订单信号不足")

    ready_for_paid_scale = bool(decision == "target_verified")
    if not ready_for_paid_scale and "未证明真实净利达标，付费投放继续暂停" not in blockers:
        blockers.append("未证明真实净利达标，付费投放继续暂停")

    brand_policy = {
        "required_value": "无品牌",
        "title_use_brand_name_required": False,
        "keyword_brand_comparison_allowed": False,
        "reason": "用户无品牌资质，安全稳健优先",
    }

    return {
        "plan_type": "first_order_decision_matrix",
        "target_net_profit": _money(target_net_profit),
        "goal_status": "not_achieved" if decision != "target_verified" else "achieved_verified",
        "precondition_status": precondition_status,
        "decision": decision,
        "action_id": _nonnegative_int(action_row.get("id") or action_row.get("action_id") or action_row.get("actionId")),
        "product_id": str(action_row.get("product_id") or action_row.get("productId") or ""),
        "product_title": str(action_row.get("title") or ""),
        "baseline": baseline_state,
        "current": current_state,
        "delta": delta,
        "requires_user_confirmation_before_save": not saved_confirmed,
        "safe_to_auto_save": False,
        "safe_to_auto_apply": False,
        "paid_ads_paused": not ready_for_paid_scale,
        "ready_for_paid_scale": ready_for_paid_scale,
        "requires_profit_validation": requires_profit_validation,
        "next_actions": next_actions,
        "blockers": list(dict.fromkeys(blockers)),
        "decision_branches": [
            {
                "if": "未确认保存",
                "then": "等待用户明确确认保存当前编辑页；不自动保存",
            },
            {
                "if": "订单 > 0 且 net_profit_verified=false",
                "then": "同步订单、成本、运费、佣金、推广、退款和售后损失",
            },
            {
                "if": "点击增加但订单仍为0",
                "then": "复核详情页、SKU、售价、运费、售后和信任承接",
            },
            {
                "if": "曝光增加但点击未增加",
                "then": "回到商品卡首图、标题关键词、价格展示和主图视频首帧",
            },
        ],
        "knowledge_basis": [
            "抖音电商学习中心：商品运营、搜索运营、卖出首单和商品搜索优化路径",
            "商品信息一致性规则：标题、主图、属性、规格和商详必须与真实商品一致",
            "当前店铺数据：有搜索曝光和商品点击，但订单仍为0",
        ],
        "safety_gates": [
            "不调用抖店官方 API",
            "不调用外部 AI 或第三方模型",
            "品牌字段统一无品牌，标题不写品牌词",
            "不自动保存、不发布、不投放、不付款",
            "不自动采购、不批量备货",
        ],
        "brand_policy": brand_policy,
        "no_brand_policy": brand_policy,
        "ai_policy": dict(AI_POLICY),
    }


def build_post_save_conversion_monitor(
    metrics: Mapping[str, Any],
    action: Optional[Mapping[str, Any]] = None,
    save_gate: Optional[Mapping[str, Any]] = None,
    conversion_experiment_plan: Optional[Mapping[str, Any]] = None,
    target_net_profit: float = DAILY_NET_PROFIT_TARGET,
    saved_confirmed: bool = False,
) -> Dict[str, Any]:
    """生成用户保存后的首单与净利复盘闸。

    本函数只做本地规则决策，不保存、不发布、不投放、不付款，也不调用外部服务。
    """

    metric_row = dict(metrics or {})
    action_row = dict(action or {})
    gate = dict(save_gate or {})
    if not gate:
        action_evidence = action_row.get("evidence")
        if not isinstance(action_evidence, Mapping):
            evidence_json = action_row.get("evidence_json")
            if evidence_json:
                try:
                    parsed_evidence = json.loads(str(evidence_json))
                    action_evidence = parsed_evidence if isinstance(parsed_evidence, Mapping) else {}
                except Exception:
                    action_evidence = {}
        if isinstance(action_evidence, Mapping) and isinstance(action_evidence.get("save_edit_human_gate"), Mapping):
            gate = dict(action_evidence.get("save_edit_human_gate") or {})
    stage = str((conversion_experiment_plan or {}).get("stage") or _ops_stage_from_metrics(metric_row))
    orders_count = _nonnegative_int(metric_row.get("orders_count"))
    if orders_count > 0:
        stage = "profit_validation"

    pre_save_status = _save_gate_status(gate, saved_confirmed)

    net_profit_verified = bool(metric_row.get("net_profit_verified", False))
    requires_profit_validation = orders_count > 0 and not net_profit_verified
    ready_for_paid_scale = (
        orders_count > 0
        and net_profit_verified
        and _money(metric_row.get("net_profit", 0)) > 0
    )

    blockers: List[str] = []
    if not saved_confirmed:
        blockers.append("等待用户确认保存当前编辑页")
    if requires_profit_validation:
        blockers.append("net_profit_verified=true 后才允许评估放量")
    if not ready_for_paid_scale:
        blockers.append("未证明首单转化和真实净利，不能进入付费放量")

    brand_policy = {
        "required_value": "无品牌",
        "title_use_brand_name_required": False,
        "keyword_brand_comparison_allowed": False,
        "reason": "用户无品牌资质，安全稳健优先",
    }

    return {
        "plan_type": "post_save_conversion_monitor",
        "target_net_profit": _money(target_net_profit),
        "goal_status": _ops_goal_status(metric_row, target_net_profit),
        "stage": stage,
        "action_id": _nonnegative_int(action_row.get("id") or action_row.get("action_id") or action_row.get("actionId")),
        "product_id": str(action_row.get("product_id") or action_row.get("productId") or ""),
        "product_title": str(action_row.get("title") or ""),
        "pre_save_status": pre_save_status,
        "requires_user_confirmation_before_save": not saved_confirmed,
        "safe_to_auto_save": False,
        "safe_to_auto_apply": False,
        "paid_ads_paused": not ready_for_paid_scale,
        "ready_for_paid_scale": ready_for_paid_scale,
        "requires_profit_validation": requires_profit_validation,
        "baseline": {
            "snapshot_id": _nonnegative_int(metric_row.get("id") or metric_row.get("snapshot_id") or metric_row.get("snapshotId")),
            "snapshot_date": str(metric_row.get("snapshot_date") or date.today().isoformat()),
            "product_exposure_count": _nonnegative_int(metric_row.get("product_exposure_count")),
            "product_click_count": _nonnegative_int(metric_row.get("product_click_count")),
            "orders_count": orders_count,
            "net_profit": _money(metric_row.get("net_profit", 0)),
            "net_profit_verified": net_profit_verified,
            "promotion_cost": _money(metric_row.get("promotion_cost", 0)),
        },
        "checkpoints": [
            {
                "checkpoint": "immediate_after_save",
                "action": "用户确认保存后，立即只读核对当前页未误触发布、投放、付款或标题托管",
                "success_signal": "页面仍是目标商品，品牌=无品牌，使用品牌名关闭，无付费动作",
            },
            {
                "checkpoint": "next_snapshot",
                "action": "使用临时首页 tab 读取下一次经营快照",
                "success_signal": "orders_count >= 1 时进入真实净利核算；否则继续按曝光、点击、订单漏斗定位",
            },
            {
                "checkpoint": "profit_validation",
                "action": "同步订单明细、成本、运费、佣金、推广费、退款和售后损失",
                "success_signal": "net_profit_verified=true 且经营净利口径完整",
            },
        ],
        "next_snapshot_metrics": [
            "product_exposure_count",
            "product_click_count",
            "search_exposure_count",
            "orders_count",
            "gross_sales",
            "promotion_cost",
            "refund_amount",
            "after_sale_amount",
            "net_profit",
            "net_profit_verified",
        ],
        "decision_rules": [
            {
                "if": "orders_count >= 1",
                "then": "同步订单明细、成本、运费、佣金、推广费、退款和售后损失，计算真实经营净利",
            },
            {
                "if": "product_click_count 增加但 orders_count 仍为 0",
                "then": "复核价格、SKU、运费、详情页前半段和售后承诺，不做付费放量",
            },
            {
                "if": "曝光和点击保存后仍持平",
                "then": "回到商品卡、搜索词和素材问题排查；继续暂停付费投放",
            },
        ],
        "allowed_next_actions": [
            "等待用户确认保存当前编辑页",
            "保存后只读同步经营快照",
            "出现订单后再核算真实净利",
        ],
        "blockers": blockers,
        "safety_gates": [
            "不调用抖店官方 API",
            "不调用外部 AI 或第三方模型",
            "品牌字段统一无品牌，标题不写品牌词",
            "不自动保存、不发布、不投放、不付款",
            "登录、验证码、付款、投放扣费、最终不可逆确认保留人工安全闸",
        ],
        "brand_policy": brand_policy,
        "no_brand_policy": brand_policy,
        "ai_policy": dict(AI_POLICY),
    }


def _normalize_product_issues(value: Any) -> List[Dict[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return []
    products: List[Dict[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        product_id = str(item.get("product_id") or item.get("productId") or "").strip()
        title = str(item.get("title") or "").strip()
        issues = _string_list(item.get("issues"))
        if not product_id or not title or not issues:
            continue
        products.append({
            "product_id": product_id,
            "title": title,
            "quality_score": _nonnegative_int(item.get("quality_score")),
            "recent_30d_sales": _nonnegative_int(item.get("recent_30d_sales")),
            "issues": issues,
        })
    return sorted(
        products,
        key=lambda row: (
            -int(row.get("recent_30d_sales") or 0),
            int(row.get("quality_score") or 0),
            str(row.get("product_id") or ""),
        ),
    )


def build_diagnostic_action_plan(signals: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    signals = dict(signals or {})
    missing_main_video_count = _nonnegative_int(signals.get("missing_main_video_count"))
    missing_spec_image_count = _nonnegative_int(signals.get("missing_spec_image_count"))
    missing_live_replay_count = _nonnegative_int(signals.get("missing_live_replay_count"))
    attribute_optimization_count = _nonnegative_int(signals.get("attribute_optimization_count"))
    risk_product_count = _nonnegative_int(signals.get("risk_product_count"))
    opportunity_keywords = _string_list(signals.get("opportunity_keywords"))
    refund_reasons = signals.get("refund_reasons") if isinstance(signals.get("refund_reasons"), Mapping) else {}
    product_issues = _normalize_product_issues(signals.get("product_issues"))

    actions: List[str] = []
    if opportunity_keywords:
        actions.append(
            f"围绕机会词 {'、'.join(opportunity_keywords[:4])} 选择或优化袜子商品，标题只保留真实属性词"
        )
    if missing_main_video_count > 0:
        actions.append(f"优先补齐 {missing_main_video_count} 个缺主图视频商品，先处理有曝光、已有点击或近30天销量基础的商品")
    if missing_spec_image_count > 0:
        actions.append(f"补齐 {missing_spec_image_count} 个缺规格图商品，明确 1 双、均码、颜色和默认发货规则")
    if attribute_optimization_count > 0:
        actions.append(f"复核 {attribute_optimization_count} 个属性优化项，优先补材质、厚薄、适用季节和适用性别")
    if missing_live_replay_count > 0:
        actions.append(f"记录 {missing_live_replay_count} 个缺讲解回放商品；当前先不为低客单商品强行做直播依赖")
    if risk_product_count > 0:
        actions.append(f"只读核对 {risk_product_count} 个风险商品来源，避免最终发布前留下商品素材或规则风险")
    if product_issues:
        top_rows = product_issues[:3]
        for row in top_rows:
            issue_text = "、".join(row["issues"][:2])
            title = str(row["title"])
            if len(title) > 28:
                title = title[:28] + "..."
            actions.append(
                f"优先处理商品 {row['product_id']}（{title}，近30天销量 {row['recent_30d_sales']}）：{issue_text}"
            )

    wrong_order_count = _nonnegative_int(refund_reasons.get("多拍/错拍/不想要"))
    if wrong_order_count > 0:
        actions.append(
            f"售后中多拍/错拍/不想要 {wrong_order_count} 条，优先简化 SKU 选择并在详情页写清 1 双和默认发货"
        )

    material_issue_count = (
        missing_main_video_count
        + missing_spec_image_count
        + attribute_optimization_count
        + risk_product_count
    )
    if material_issue_count > 0:
        primary_focus = "product_material_quality"
    elif wrong_order_count > 0:
        primary_focus = "wrong_order_reduction"
    elif opportunity_keywords:
        primary_focus = "search_keyword_opportunity"
    else:
        primary_focus = "monitoring"
        actions.append("暂无新的商品诊断信号，继续只读同步经营数据和商品状态")

    return {
        "primary_focus": primary_focus,
        "paid_ads_ready": bool(material_issue_count == 0 and wrong_order_count == 0),
        "actions": actions,
        "specific_issue_products": product_issues,
        "signals": {
            "missing_main_video_count": missing_main_video_count,
            "missing_spec_image_count": missing_spec_image_count,
            "missing_live_replay_count": missing_live_replay_count,
            "attribute_optimization_count": attribute_optimization_count,
            "risk_product_count": risk_product_count,
            "opportunity_keywords": opportunity_keywords,
            "refund_reasons": dict(refund_reasons),
            "product_issues": product_issues,
        },
    }


def build_growth_bottleneck_plan(
    metrics: Mapping[str, Any],
    top_candidate: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    product_exposure_count = max(int(metrics.get("product_exposure_count", 0) or 0), 0)
    product_click_count = max(int(metrics.get("product_click_count", 0) or 0), 0)
    search_exposure_count = max(int(metrics.get("search_exposure_count", 0) or 0), 0)
    orders_count = max(int(metrics.get("orders_count", 0) or 0), 0)
    gross_sales = _money(metrics.get("gross_sales", 0))
    product_click_rate = (
        _money((product_click_count / product_exposure_count) * 100) if product_exposure_count > 0 else None
    )
    candidate = dict(top_candidate or {})
    recommended_sale_price = _money(candidate.get("recommended_sale_price", 0))

    next_review_metrics = [
        "product_exposure_count",
        "product_click_count",
        "product_click_rate",
        "orders_count",
        "gross_sales",
        "refund_amount",
        "promotion_cost",
    ]
    if search_exposure_count > 0:
        next_review_metrics.insert(2, "search_exposure_count")

    if product_exposure_count > 0 and product_click_count == 0:
        title_action = "标题关键词保留女款、浅口、船袜、春夏、薄款、短袜、均码等搜索意图词，去掉无关堆词"
        if search_exposure_count > 0:
            title_action = (
                f"已有 {search_exposure_count} 个搜索曝光，"
                "标题关键词保留女款、浅口、船袜、春夏、薄款、短袜、均码等搜索意图词，去掉无关堆词"
            )
        price_action = "确认商品卡价格展示和 SKU 口径一致，突出 1 双、均码，避免用户以为是多双组合"
        if recommended_sale_price > 0:
            price_action = f"确认商品卡价格展示为售价 {recommended_sale_price} 元且与 SKU 口径一致，突出 1 双、均码，避免用户以为是多双组合"

        return {
            "stage": "card_click_bottleneck",
            "diagnosis": f"当前为商品卡点击瓶颈：{product_exposure_count} 曝光 0 点击，优先证明商品卡能吸引点击。",
            "paid_ads_paused": True,
            "primary_metric": "product_click_count",
            "next_review_metrics": next_review_metrics,
            "priority_actions": [
                _bottleneck_action(
                    "首图",
                    "首图优先展示上脚效果、颜色差异和 1 双信息，避免只放平铺图或无购买信息的素材",
                    "下一次经营快照 product_click_count > 0 或 product_click_rate > 0",
                ),
                _bottleneck_action(
                    "主图视频",
                    "主图视频首帧先给上脚效果，再展示颜色、刺绣和叠放细节，承接当前有曝光无点击的问题",
                    "平台素材验收通过后，观察同等曝光下点击人数是否从 0 变为正数",
                ),
                _bottleneck_action(
                    "标题关键词",
                    title_action,
                    "搜索曝光继续存在且商品点击人数转正",
                ),
                _bottleneck_action(
                    "价格展示",
                    price_action,
                    "点击转正后再评估是否需要组合装或更高客单价",
                ),
            ],
        }

    if product_click_count > 0 and orders_count == 0:
        return {
            "stage": "detail_conversion_bottleneck",
            "diagnosis": f"当前为详情承接瓶颈：已有 {product_click_count} 点击但 0 成交，优先证明点击能转订单。",
            "paid_ads_paused": True,
            "primary_metric": "orders_count",
            "next_review_metrics": next_review_metrics,
            "priority_actions": [
                _bottleneck_action(
                    "详情页",
                    "详情页前半段补足上脚场景、材质厚薄、适穿鞋型和洗护说明，减少进店后犹豫",
                    "下一次经营快照 orders_count > 0",
                ),
                _bottleneck_action(
                    "SKU",
                    "SKU 名称继续明确 1 双、均码和颜色，避免多拍、错拍、不想要类售后",
                    "售后原因中多拍/错拍/不想要占比下降",
                ),
                _bottleneck_action(
                    "运费与售价",
                    "复核运费、售价和退换说明，避免低客单商品因履约成本倒挂导致用户放弃",
                    "点击到成交转化率转正，且单笔经营净利仍为正",
                ),
            ],
        }

    if orders_count > 0 or gross_sales > 0:
        return {
            "stage": "profit_validation",
            "diagnosis": "已经出现成交信号，下一步核算真实净利和售后损失，避免只看成交金额。",
            "paid_ads_paused": False,
            "primary_metric": "net_profit",
            "next_review_metrics": next_review_metrics + ["net_profit", "net_profit_verified"],
            "priority_actions": [
                _bottleneck_action(
                    "利润账本",
                    "同步订单明细、商品成本、运费、平台佣金、推广费、退款和售后损失，核算经营净利",
                    "net_profit_verified=true 且净利口径完整",
                ),
                _bottleneck_action(
                    "补货",
                    "只按真实销量和同日补货能力补货，不因单日曝光扩大库存",
                    "补货后不出现断货或库存积压",
                ),
            ],
        }

    return {
        "stage": "need_more_signal",
        "diagnosis": "当前缺少曝光、点击和成交信号，先保证商品可发布、素材完整并继续只读同步经营数据。",
        "paid_ads_paused": True,
        "primary_metric": "product_exposure_count",
        "next_review_metrics": next_review_metrics,
        "priority_actions": [
            _bottleneck_action(
                "上新准备",
                "先完成本地发布前校验、平台素材预检和安全闸，不做最终发布或付费投放",
                "validate_product_for_upload ready=true，预检不触发最终发布",
            )
        ],
    }


STAGE_EXPERIMENT_SPEC: Dict[str, tuple] = {
    "detail_conversion_bottleneck": (
        "detail_conversion_first_order",
        (
            "已有点击但未成交，先补详情承接和 SKU 口径，验证点击能否转为首单；"
            "未验证首单前不做付费放量。"
        ),
        "orders_count",
    ),
    "card_click_bottleneck": (
        "product_card_first_click",
        "已有曝光但无点击，先修商品卡首图、标题关键词和价格口径，验证能否获得点击。",
        "product_click_count",
    ),
    "profit_validation": (
        "unit_profit_validation",
        "已有订单信号，优先核算真实单笔净利、退款和售后损失，再决定是否放量。",
        "net_profit",
    ),
    "need_more_signal": (
        "listing_signal_collection",
        "当前信号不足，先保持素材和合规基建，继续只读同步经营快照。",
        "product_exposure_count",
    ),
}


def build_conversion_experiment_plan(
    metrics: Mapping[str, Any],
    detail_audit: Optional[Mapping[str, Any]] = None,
    profit_plan: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """把当前曝光、点击、订单和详情页审计转成一次可验收的本地实验计划。

    该函数只做本地规则决策，不保存、不发布、不投放，也不调用外部服务。
    """

    exposure_count = _nonnegative_int(metrics.get("product_exposure_count"))
    click_count = _nonnegative_int(metrics.get("product_click_count"))
    orders_count = _nonnegative_int(metrics.get("orders_count"))
    snapshot_date = str(metrics.get("snapshot_date") or date.today().isoformat())
    audit = dict(detail_audit or {})
    flags = set(_string_list(audit.get("evidence_flags") or []))
    detail_summary = audit.get("detail_summary") if isinstance(audit.get("detail_summary"), Mapping) else {}
    sku_summary = audit.get("sku_summary") if isinstance(audit.get("sku_summary"), Mapping) else {}
    brand_gate = audit.get("brand_gate") if isinstance(audit.get("brand_gate"), Mapping) else {}
    profit = profit_plan if isinstance(profit_plan, Mapping) else {}
    unit_economics = profit.get("unit_economics") if isinstance(profit.get("unit_economics"), Mapping) else {}
    target_orders = profit.get("target_orders") if isinstance(profit.get("target_orders"), Mapping) else {}
    scale_readiness = profit.get("scale_readiness") if isinstance(profit.get("scale_readiness"), Mapping) else {}

    stage = _ops_stage_from_metrics(metrics)
    experiment_name, hypothesis, primary_metric = STAGE_EXPERIMENT_SPEC[stage]

    experiment_tasks: List[str] = []
    if "main_video_pending_save" in flags:
        experiment_tasks.append("主图视频已在编辑页待保存；仅在用户明确确认后保存当前编辑页")
    elif "main_video_not_confirmed" in flags:
        experiment_tasks.append("先补主图视频素材并通过上传截停安全闸")
    if "guide_short_title_empty" in flags or _nonnegative_int(detail_summary.get("guide_short_title_length")) == 0:
        experiment_tasks.append("补无品牌导购短标题，突出小雏菊、碎花、春夏、镂空网眼和中筒袜")
    if "important_attributes_incomplete" in flags:
        filled = _nonnegative_int(detail_summary.get("important_attributes_filled"))
        total = _nonnegative_int(detail_summary.get("important_attributes_total"))
        if total:
            experiment_tasks.append(f"补齐真实重点属性：当前 {filled}/{total}，优先季节、图案、风格、功能")
        else:
            experiment_tasks.append("补齐真实重点属性，优先季节、图案、风格、功能")
    if "material_components_incomplete" in flags:
        experiment_tasks.append("材质成分只按水洗标、吊牌或供应商真实百分比补充")
    if "spec_image_needed" in flags or bool(detail_summary.get("spec_image_prompt_visible")):
        colors = "、".join(str(item) for item in (sku_summary.get("color_values") or []) if str(item))
        sizes = "、".join(str(item) for item in (sku_summary.get("size_values") or []) if str(item))
        spec_text = "补规格图，写清颜色、均码和真实售卖单位"
        if colors or sizes:
            spec_text += f"；当前颜色={colors or '未读到'}，尺码={sizes or '未读到'}"
        experiment_tasks.append(spec_text)
    if not experiment_tasks:
        experiment_tasks.append("继续只读观察下一次经营快照，不做平台动作")

    blockers: List[str] = []
    if audit and not bool(audit.get("page_verified")):
        blockers.append("当前页面未核对为目标商品编辑页")
    if audit and not bool(brand_gate.get("ready")):
        blockers.append("品牌闸未确认无品牌或使用品牌名状态")
    if not bool(scale_readiness.get("ready_for_paid_scale", False)):
        blockers.append("未证明首单转化和真实净利，不能进入付费放量")

    unit_profit = _money(unit_economics.get("net_profit_per_order", 0))
    minimum_daily_orders = target_orders.get("minimum_daily_orders")

    return {
        "stage": stage,
        "experiment_name": experiment_name,
        "hypothesis": hypothesis,
        "snapshot_date": snapshot_date,
        "primary_metric": primary_metric,
        "baseline": {
            "product_exposure_count": exposure_count,
            "product_click_count": click_count,
            "orders_count": orders_count,
            "net_profit_verified": bool(metrics.get("net_profit_verified", False)),
        },
        "success_criteria": {
            "minimum_orders": 1 if stage == "detail_conversion_bottleneck" else None,
            "minimum_clicks": 1 if stage == "card_click_bottleneck" else None,
            "net_profit_verified_required": stage == "profit_validation",
            "review_after_next_snapshot": True,
        },
        "experiment_tasks": experiment_tasks,
        "allowed_next_actions": [
            "只生成本地实验计划和素材清单",
            "用户明确确认后，才允许保存当前编辑页这一项动作",
            "保存后用临时首页 tab 复核经营快照，观察 orders_count 是否转正",
        ],
        "blockers": blockers,
        "paid_ads_paused": True,
        "safe_to_auto_apply": False,
        "unit_economics_reference": {
            "net_profit_per_order": unit_profit,
            "minimum_daily_orders_for_500": minimum_daily_orders,
        },
        "safety_gates": [
            "不调用抖店官方 API",
            "不调用外部 AI 或第三方模型",
            "品牌字段统一无品牌，标题不写品牌词",
            "不自动保存当前编辑页",
            "不发布商品",
            "不投放、不付款",
        ],
        "ai_policy": dict(AI_POLICY),
    }


def _detail_snapshot_text_blob(snapshot: Mapping[str, Any]) -> str:
    values: List[str] = []
    for key in ("body_text", "bodyText", "brand_text", "brandText"):
        value = snapshot.get(key)
        if value:
            values.append(str(value))
    for key in ("visible_fields", "visibleFields", "visible_controls", "visibleControls"):
        raw_items = snapshot.get(key)
        if not isinstance(raw_items, Sequence) or isinstance(raw_items, (str, bytes)):
            continue
        for item in raw_items:
            if isinstance(item, Mapping):
                value = item.get("text") or item.get("value") or item.get("field_id") or item.get("fieldId")
            else:
                value = item
            if value:
                values.append(str(value))
    return re.sub(r"\s+", " ", " ".join(values)).strip()


def _progress_pair_from_text(text: str, label: str) -> Optional[tuple[int, int]]:
    match = re.search(rf"{re.escape(label)}\s*([0-9]+)\s*/\s*([0-9]+)", text)
    if not match:
        return None
    return max(int(match.group(1)), 0), max(int(match.group(2)), 0)


def _detail_image_pair_from_text(text: str) -> Optional[tuple[int, int]]:
    match = re.search(r"商详图片\s*[（(]\s*([0-9]+)\s*/\s*([0-9]+)\s*[）)]", text)
    if not match:
        return None
    return max(int(match.group(1)), 0), max(int(match.group(2)), 0)


def _extract_between(text: str, start: str, end: str) -> str:
    start_index = text.find(start)
    if start_index < 0:
        return ""
    start_index += len(start)
    end_index = text.find(end, start_index)
    if end_index < 0:
        end_index = len(text)
    return text[start_index:end_index].strip()


def _choice_values_from_section(section: str) -> List[str]:
    stop_words = {
        "添加规格图",
        "批量上传规格图",
        "下移",
        "上移",
        "自定义排序",
        "添加规格类型",
        "规格预览",
    }
    values: List[str] = []
    for token in re.split(r"\s+", section):
        clean = token.strip(" ，,;；*")
        if not clean or clean in stop_words or "/" in clean or clean.endswith("）") or clean.endswith(")"):
            continue
        if clean.startswith("请选择") or clean.startswith("输入"):
            continue
        values.append(clean)
    return list(dict.fromkeys(values))


def _stock_values_from_text(text: str, color_values: Sequence[str], size_values: Sequence[str]) -> List[int]:
    stocks: List[int] = []
    sizes = [str(item) for item in size_values if str(item)]
    for color in [str(item) for item in color_values if str(item)]:
        size_pattern = r"(?:" + "|".join(re.escape(item) for item in sizes) + r")" if sizes else r"\S+"
        pattern = rf"{re.escape(color)}\s+{size_pattern}\s+￥\s*[0-9]+(?:\.[0-9]+)?\s+增\s+减\s+([0-9]+)"
        match = re.search(pattern, text)
        if match:
            stocks.append(max(int(match.group(1)), 0))
    if stocks:
        return stocks
    return [max(int(item), 0) for item in re.findall(r"￥\s*[0-9]+(?:\.[0-9]+)?\s+增\s+减\s+([0-9]+)", text)]


def _forbidden_controls_from_text(text: str) -> List[str]:
    controls: List[str] = []
    for label in ("发布商品", "保存草稿", "填写检查"):
        if label in text:
            controls.append(label)
    if re.search(r"(?<!草稿)保存(?!草稿)", text):
        controls.append("保存")
    return list(dict.fromkeys(controls))


def _derive_detail_snapshot_fields(page_snapshot: Mapping[str, Any]) -> Dict[str, Any]:
    snapshot = dict(page_snapshot or {})
    text = _detail_snapshot_text_blob(snapshot)
    if not text:
        return snapshot

    url = str(snapshot.get("url") or "")
    if "product_id_in_url" not in snapshot and "productIdInUrl" not in snapshot:
        snapshot["product_id_in_url"] = "product_id=" in url and "/g/create" in url

    main_video_field = snapshot.get("main_video_field") if isinstance(snapshot.get("main_video_field"), Mapping) else {}
    if "main_video_success_card" not in snapshot and "mainVideoSuccessCard" not in snapshot:
        snapshot["main_video_success_card"] = bool(
            main_video_field.get("has_success_card")
            or main_video_field.get("has_video_asset_sign")
            or main_video_field.get("has_video_tag")
        )
    if (
        "main_video_unsaved" not in snapshot
        and "mainVideoUnsaved" not in snapshot
        and snapshot.get("main_video_success_card")
    ):
        snapshot["main_video_unsaved"] = any(label in text for label in ("发布商品", "保存草稿", "填写检查"))

    short_title = _progress_pair_from_text(text, "导购短标题")
    if short_title and "guide_short_title_length" not in snapshot and "guideShortTitleLength" not in snapshot:
        snapshot["guide_short_title_length"] = short_title[0]

    important = _progress_pair_from_text(text, "重要属性")
    if important:
        snapshot.setdefault("important_attributes_filled", important[0])
        snapshot.setdefault("important_attributes_total", important[1])

    material = _progress_pair_from_text(text, "材质成分")
    if material:
        snapshot.setdefault("material_components_filled", material[0])
        snapshot.setdefault("material_components_total", material[1])

    detail_images = _detail_image_pair_from_text(text)
    if detail_images:
        snapshot.setdefault("detail_image_count", detail_images[0])
        snapshot.setdefault("detail_image_capacity", detail_images[1])

    snapshot.setdefault("spec_image_prompt_visible", "发布规格图" in text or "规格图" in text)

    if "color_values" not in snapshot and "colorValues" not in snapshot:
        color_section = _extract_between(text, "*颜色分类", "请选择/输入颜色分类")
        snapshot["color_values"] = _choice_values_from_section(color_section)
    if "size_values" not in snapshot and "sizeValues" not in snapshot:
        size_section = _extract_between(text, "*码数", "请选择/输入码数")
        snapshot["size_values"] = _choice_values_from_section(size_section)

    color_values = [str(item) for item in (snapshot.get("color_values") or snapshot.get("colorValues") or []) if str(item)]
    size_values = [str(item) for item in (snapshot.get("size_values") or snapshot.get("sizeValues") or []) if str(item)]
    if "sku_stock_values" not in snapshot and "skuStockValues" not in snapshot:
        snapshot["sku_stock_values"] = _stock_values_from_text(text, color_values, size_values)

    if "freight_template" not in snapshot and "freightTemplate" not in snapshot and "包邮" in text:
        snapshot["freight_template"] = "包邮"
    if "after_sale_policy" not in snapshot and "afterSalePolicy" not in snapshot and "7天无理由退货" in text:
        snapshot["after_sale_policy"] = "7天无理由退货"
    if "forbidden_controls_visible" not in snapshot and "forbiddenControlsVisible" not in snapshot:
        snapshot["forbidden_controls_visible"] = _forbidden_controls_from_text(text)

    return snapshot


def build_detail_conversion_audit(
    metrics: Mapping[str, Any],
    page_snapshot: Mapping[str, Any],
) -> Dict[str, Any]:
    product_click_count = _nonnegative_int(metrics.get("product_click_count"))
    orders_count = _nonnegative_int(metrics.get("orders_count"))
    stage = "detail_conversion_bottleneck" if product_click_count > 0 and orders_count == 0 else "monitoring"
    page_snapshot = _derive_detail_snapshot_fields(page_snapshot)

    brand_text = str(page_snapshot.get("brand_text") or page_snapshot.get("brandText") or "")
    title_use_brand_name_checked = page_snapshot.get("title_use_brand_name_checked")
    brand_ready = _snapshot_confirms_no_brand_field(page_snapshot) and title_use_brand_name_checked is False
    page_verified = bool(page_snapshot.get("product_id_in_url") or page_snapshot.get("productIdInUrl"))

    color_values = [str(item) for item in (page_snapshot.get("color_values") or page_snapshot.get("colorValues") or []) if str(item)]
    size_values = [str(item) for item in (page_snapshot.get("size_values") or page_snapshot.get("sizeValues") or []) if str(item)]
    sku_stock_values = [
        _nonnegative_int(item)
        for item in (page_snapshot.get("sku_stock_values") or page_snapshot.get("skuStockValues") or [])
    ]

    evidence_flags: List[str] = []
    safe_next_actions: List[str] = []

    if not page_verified:
        evidence_flags.append("product_page_not_verified")
    if not brand_ready:
        evidence_flags.append("brand_gate_not_ready")

    if bool(page_snapshot.get("main_video_success_card") or page_snapshot.get("mainVideoSuccessCard")):
        if bool(page_snapshot.get("main_video_unsaved") or page_snapshot.get("mainVideoUnsaved")):
            evidence_flags.append("main_video_pending_save")
            safe_next_actions.append("主图视频已在编辑页成功上传但未保存；不自动保存，只能等待用户确认后保存当前编辑页")
    else:
        evidence_flags.append("main_video_not_confirmed")
        safe_next_actions.append("先补齐主图视频素材并通过上传截停安全闸，再考虑保存")

    guide_short_title_length = _nonnegative_int(
        page_snapshot.get("guide_short_title_length") or page_snapshot.get("guideShortTitleLength")
    )
    if guide_short_title_length == 0:
        evidence_flags.append("guide_short_title_empty")
        safe_next_actions.append("导购短标题为空；后续可补 24 字以内的无品牌场景短标题，但必须另走保存安全闸")

    important_filled = _nonnegative_int(
        page_snapshot.get("important_attributes_filled") or page_snapshot.get("importantAttributesFilled")
    )
    important_total = _nonnegative_int(
        page_snapshot.get("important_attributes_total") or page_snapshot.get("importantAttributesTotal")
    )
    if important_total and important_filled < important_total:
        evidence_flags.append("important_attributes_incomplete")
        safe_next_actions.append(f"重要属性当前 {important_filled}/{important_total}，优先补厚度、适用季节、风格等真实属性")

    material_filled = _nonnegative_int(
        page_snapshot.get("material_components_filled") or page_snapshot.get("materialComponentsFilled")
    )
    material_total = _nonnegative_int(
        page_snapshot.get("material_components_total") or page_snapshot.get("materialComponentsTotal")
    )
    if material_total and material_filled < material_total:
        evidence_flags.append("material_components_incomplete")
        safe_next_actions.append(f"材质成分当前 {material_filled}/{material_total}，需要按真实水洗标/商品信息补齐")

    spec_image_prompt_visible = bool(
        page_snapshot.get("spec_image_prompt_visible") or page_snapshot.get("specImagePromptVisible")
    )
    if spec_image_prompt_visible:
        evidence_flags.append("spec_image_needed")
        safe_next_actions.append("规格图仍有平台提示；优先补颜色、均码、1双口径的规格图，降低错拍")

    detail_count = _nonnegative_int(page_snapshot.get("detail_image_count") or page_snapshot.get("detailImageCount"))
    detail_capacity = _nonnegative_int(page_snapshot.get("detail_image_capacity") or page_snapshot.get("detailImageCapacity"))
    freight_template = str(page_snapshot.get("freight_template") or page_snapshot.get("freightTemplate") or "")
    after_sale_policy = str(page_snapshot.get("after_sale_policy") or page_snapshot.get("afterSalePolicy") or "")

    if freight_template:
        evidence_flags.append("freight_template_observed")
    if after_sale_policy:
        evidence_flags.append("after_sale_policy_observed")

    forbidden_controls = []
    for item in (
        page_snapshot.get("forbidden_controls_visible")
        or page_snapshot.get("forbiddenControlsVisible")
        or []
    ):
        text = str(item)
        if "减库存" in text:
            continue
        forbidden_controls.append(text)
    if forbidden_controls:
        evidence_flags.append("forbidden_controls_visible")

    safe_next_actions.append("继续暂停付费投放，直到点击能转化为订单且单笔净利为正")

    return {
        "stage": stage,
        "page_verified": page_verified,
        "safe_to_auto_save": False,
        "brand_gate": {
            "ready": brand_ready,
            "required_value": "无品牌",
            "title_use_brand_name_required": False,
            "observed_brand_text": brand_text,
            "title_use_brand_name_checked": title_use_brand_name_checked,
        },
        "evidence_flags": list(dict.fromkeys(evidence_flags)),
        "sku_summary": {
            "color_count": len(color_values),
            "color_values": color_values,
            "size_values": size_values,
            "total_stock_observed": sum(sku_stock_values),
            "sku_stock_values": sku_stock_values,
        },
        "detail_summary": {
            "guide_short_title_length": guide_short_title_length,
            "important_attributes_filled": important_filled,
            "important_attributes_total": important_total,
            "material_components_filled": material_filled,
            "material_components_total": material_total,
            "detail_image_count": detail_count,
            "detail_image_capacity": detail_capacity,
            "spec_image_prompt_visible": spec_image_prompt_visible,
        },
        "fulfillment_summary": {
            "freight_template": freight_template,
            "after_sale_policy": after_sale_policy,
        },
        "forbidden_controls_visible": forbidden_controls,
        "safe_next_actions": safe_next_actions,
        "ai_policy": dict(AI_POLICY),
    }


def build_detail_improvement_suggestions(product_title: str, audit: Mapping[str, Any]) -> Dict[str, Any]:
    title = str(product_title or "")
    clean_title = audit_no_brand_title_text(title)["sanitized_title"]
    sku_summary = audit.get("sku_summary") if isinstance(audit.get("sku_summary"), Mapping) else {}
    fulfillment = audit.get("fulfillment_summary") if isinstance(audit.get("fulfillment_summary"), Mapping) else {}

    short_parts: List[str] = []
    for token in ("小雏菊", "碎花", "春夏", "薄款", "镂空", "网眼", "中筒袜", "船袜", "短袜"):
        if token in clean_title and token not in short_parts:
            short_parts.append(token)
    if "袜" not in "".join(short_parts):
        short_parts.append("袜子")
    guide_short_title = "".join(short_parts)[:24]
    if not guide_short_title:
        guide_short_title = clean_title[:24]

    attribute_suggestions: List[Dict[str, Any]] = []
    if "春夏" in clean_title:
        attribute_suggestions.append({
            "field": "适用季节",
            "suggested_value": "春夏",
            "evidence": "商品标题包含春夏",
            "requires_manual_evidence": False,
        })
    if "小雏菊" in clean_title or "碎花" in clean_title:
        attribute_suggestions.append({
            "field": "图案",
            "suggested_value": "小雏菊/碎花",
            "evidence": "商品标题包含小雏菊或碎花",
            "requires_manual_evidence": False,
        })
    if "甜美" in clean_title:
        attribute_suggestions.append({
            "field": "风格",
            "suggested_value": "甜美",
            "evidence": "商品标题包含甜美",
            "requires_manual_evidence": False,
        })
    if "透气" in clean_title or "网眼" in clean_title or "镂空" in clean_title:
        attribute_suggestions.append({
            "field": "功能",
            "suggested_value": "透气",
            "evidence": "商品标题或页面属性包含透气/网眼/镂空",
            "requires_manual_evidence": False,
        })

    attribute_suggestions.extend([
        {
            "field": "厚度",
            "suggested_value": None,
            "evidence": "当前页面读数不能证明薄款或常规厚度",
            "requires_manual_evidence": True,
        },
        {
            "field": "材质成分",
            "suggested_value": None,
            "evidence": "材质百分比必须以水洗标、吊牌或供应商真实数据为准",
            "requires_manual_evidence": True,
        },
    ])

    color_values = [str(item) for item in (sku_summary.get("color_values") or []) if str(item)]
    size_values = [str(item) for item in (sku_summary.get("size_values") or []) if str(item)]
    freight_template = str(fulfillment.get("freight_template") or "")
    after_sale_policy = str(fulfillment.get("after_sale_policy") or "")
    spec_lines = []
    if color_values:
        spec_lines.append(f"颜色：{'、'.join(color_values)}")
    if size_values:
        spec_lines.append(f"尺码：{'、'.join(size_values)}")
    if freight_template:
        spec_lines.append(f"运费：{freight_template}")
    if after_sale_policy:
        spec_lines.append(f"售后：{after_sale_policy}")

    return {
        "stage": audit.get("stage") or "monitoring",
        "safe_to_auto_apply": False,
        "guide_short_title": {
            "text": guide_short_title,
            "char_count": len(guide_short_title),
            "policy": "无品牌，不写品牌词",
        },
        "attribute_suggestions": attribute_suggestions,
        "spec_image_brief": {
            "lines": spec_lines,
            "requires_sell_unit_confirmation": True,
            "sell_unit_note": "当前页面读数未明确证明售卖单位为 1 双；规格图和详情页写入前需确认真实发货口径",
        },
        "safety_gates": [
            "只生成本地建议，不自动填表",
            "不保存当前编辑页",
            "不发布商品",
            "不投放、不付款",
            "材质百分比和售卖单位必须有真实证据后再写入",
        ],
        "ai_policy": dict(AI_POLICY),
    }


def build_conversion_asset_pack(
    product: Mapping[str, Any],
    audit: Optional[Mapping[str, Any]] = None,
    suggestions: Optional[Mapping[str, Any]] = None,
    metrics: Optional[Mapping[str, Any]] = None,
    target_net_profit: float = DAILY_NET_PROFIT_TARGET,
) -> Dict[str, Any]:
    """生成无品牌详情首屏和规格图本地素材包。

    这里只做本地素材文案和审核规则，不上传、不保存、不发布、不投放，也不调用外部 AI。
    """

    product_row = dict(product or {})
    audit_row = dict(audit or {})
    metric_row = dict(metrics or {})
    suggestion_row = dict(suggestions or {})
    title = str(product_row.get("title") or product_row.get("product_title") or product_row.get("productTitle") or "")
    clean_title = audit_no_brand_title_text(title)["sanitized_title"].strip()
    if not suggestion_row and audit_row:
        suggestion_row = build_detail_improvement_suggestions(clean_title or title, audit_row)

    guide = suggestion_row.get("guide_short_title") if isinstance(suggestion_row.get("guide_short_title"), Mapping) else {}
    guide_short_title = str(guide.get("text") or "").strip()
    if not guide_short_title:
        fallback_suggestions = build_detail_improvement_suggestions(clean_title or title, audit_row)
        guide = fallback_suggestions.get("guide_short_title") if isinstance(fallback_suggestions.get("guide_short_title"), Mapping) else {}
        guide_short_title = str(guide.get("text") or "").strip()
    guide_short_title = audit_no_brand_title_text(guide_short_title)["sanitized_title"].strip()[:24]

    sku_summary = audit_row.get("sku_summary") if isinstance(audit_row.get("sku_summary"), Mapping) else {}
    detail_summary = audit_row.get("detail_summary") if isinstance(audit_row.get("detail_summary"), Mapping) else {}
    fulfillment = audit_row.get("fulfillment_summary") if isinstance(audit_row.get("fulfillment_summary"), Mapping) else {}
    brand_gate = audit_row.get("brand_gate") if isinstance(audit_row.get("brand_gate"), Mapping) else {}
    colors = [str(item) for item in (sku_summary.get("color_values") or []) if str(item)]
    sizes = [str(item) for item in (sku_summary.get("size_values") or []) if str(item)]
    sale_price = _money(product_row.get("sale_price") or product_row.get("price") or 0)
    stage = str(audit_row.get("stage") or suggestion_row.get("stage") or _ops_stage_from_metrics(metric_row))

    visible_claims: List[str] = []
    if guide_short_title:
        visible_claims.append(guide_short_title)
    if any(token in clean_title for token in ("小雏菊", "碎花")):
        visible_claims.append("小雏菊碎花图案")
    if any(token in clean_title for token in ("春夏", "夏")):
        visible_claims.append("春夏穿搭")
    if any(token in clean_title for token in ("镂空", "网眼", "透气")):
        visible_claims.append("镂空网眼透气")
    if any(token in clean_title for token in ("中筒", "堆堆")):
        visible_claims.append("中筒堆堆袜型")
    if any(token in clean_title for token in ("甜美", "木耳边")):
        visible_claims.append("甜美木耳边")
    visible_claims = list(dict.fromkeys([line for line in visible_claims if line]))

    color_line = f"颜色：{'、'.join(colors)}" if colors else "颜色：待从 SKU 核对"
    size_line = f"尺码：{'、'.join(sizes)}" if sizes else "尺码：待从 SKU 核对"
    spec_lines = [color_line, size_line, "售卖单位：待人工确认后写入"]
    if sale_price > 0:
        spec_lines.append(f"当前 SKU 售价：{sale_price} 元")
    freight_template = str(fulfillment.get("freight_template") or "")
    after_sale_policy = str(fulfillment.get("after_sale_policy") or "")
    if freight_template:
        spec_lines.append(f"运费：{freight_template}")
    if after_sale_policy:
        spec_lines.append(f"售后：{after_sale_policy}")

    detail_lines = list(visible_claims[:5])
    if colors:
        detail_lines.append(f"{len(colors)} 色可选")
    if sizes:
        detail_lines.append(f"尺码：{'、'.join(sizes)}")

    manual_evidence_required = [
        "售卖单位必须以实际发货口径确认后再写入",
        "材质成分必须以水洗标、吊牌或供应商真实百分比确认",
        "厚度、无骨、防臭、抗菌、纯棉等承诺必须有真实凭证后再写入",
    ]
    if _nonnegative_int(detail_summary.get("important_attributes_total")) and (
        _nonnegative_int(detail_summary.get("important_attributes_filled"))
        < _nonnegative_int(detail_summary.get("important_attributes_total"))
    ):
        manual_evidence_required.append("重要属性未补齐前，素材不得承诺未核验属性")

    ready_for_upload = False
    brand_policy = {
        "required_value": "无品牌",
        "title_use_brand_name_required": False,
        "keyword_brand_comparison_allowed": False,
        "reason": "用户无品牌资质，安全稳健优先",
    }

    return {
        "plan_type": "conversion_asset_pack",
        "target_net_profit": _money(target_net_profit),
        "stage": stage,
        "goal_status": _ops_goal_status(metric_row, target_net_profit) if metric_row else "unknown",
        "product_context": {
            "action_id": _nonnegative_int(product_row.get("action_id") or product_row.get("id")),
            "product_id": str(product_row.get("product_id") or product_row.get("productId") or ""),
            "title": clean_title or title,
            "sale_price": sale_price,
            "brand": "无品牌",
        },
        "baseline": {
            "snapshot_id": _nonnegative_int(metric_row.get("id") or metric_row.get("snapshot_id") or metric_row.get("snapshotId")),
            "product_exposure_count": _nonnegative_int(metric_row.get("product_exposure_count")),
            "product_click_count": _nonnegative_int(metric_row.get("product_click_count")),
            "orders_count": _nonnegative_int(metric_row.get("orders_count")),
            "net_profit_verified": bool(metric_row.get("net_profit_verified", False)),
        },
        "copy_blocks": {
            "guide_short_title": guide_short_title,
            "detail_first_screen_lines": detail_lines,
            "spec_image_lines": spec_lines,
        },
        "draft_assets": [
            {
                "asset_id": "detail_first_screen_no_brand",
                "asset_type": "detail_image",
                "status": "local_draft_only",
                "ready_for_upload": ready_for_upload,
                "visible_lines": detail_lines,
                "source": "商品标题、SKU 颜色尺码、页面只读审计",
                "forbidden_claims": ["品牌词", "未核验材质成分", "未核验功能承诺", "平台自动优化文案"],
            },
            {
                "asset_id": "spec_image_no_brand",
                "asset_type": "spec_image",
                "status": "local_draft_only",
                "ready_for_upload": ready_for_upload,
                "visible_lines": spec_lines,
                "source": "SKU 颜色尺码、售价、运费和售后页面读数",
                "forbidden_claims": ["品牌词", "未确认售卖单位", "未核验材质成分", "未核验功能承诺"],
            },
        ],
        "manual_evidence_required": manual_evidence_required,
        "allowed_next_actions": [
            "本地审核素材文案和图片草案",
            "补供应商或实物凭证后再判断是否可上传",
            "用户确认后才允许进入浏览器上传截停流程",
        ],
        "safe_to_auto_apply": False,
        "safe_to_auto_upload": False,
        "paid_ads_paused": True,
        "brand_gate": {
            "ready": bool(brand_gate.get("ready", False)),
            "required_value": "无品牌",
            "title_use_brand_name_required": False,
        },
        "safety_gates": [
            "不调用抖店官方 API",
            "不调用外部 AI 或第三方模型",
            "品牌字段统一无品牌，标题和素材不写品牌词",
            "不自动上传、不保存、不发布、不投放、不付款",
            "售卖单位、材质、厚度和功能承诺必须先有真实证据",
        ],
        "brand_policy": brand_policy,
        "no_brand_policy": brand_policy,
        "ai_policy": dict(AI_POLICY),
    }


def _candidate_unit_profit(candidate: Mapping[str, Any]) -> float:
    evaluation = candidate.get("evaluation") if isinstance(candidate.get("evaluation"), Mapping) else {}
    return _money(evaluation.get("net_profit_per_order", 0))


def build_profit_ramp_plan(
    metrics: Mapping[str, Any],
    candidates: Iterable[Mapping[str, Any]] = (),
) -> Dict[str, Any]:
    """把 500 元日净利目标拆成订单、点击和曝光要求。

    该函数只做本地规则测算。没有真实转化率时，流量估算只作为验证门槛，不作为投放依据。
    """

    candidate_rows = list(candidates or [])
    top_candidate = candidate_rows[0] if candidate_rows else {}
    current_net_profit = _money(metrics.get("net_profit", 0))
    net_profit_verified = bool(metrics.get("net_profit_verified", "net_profit" in metrics))
    current_orders = max(int(metrics.get("orders_count", 0) or 0), 0)
    product_exposure_count = max(int(metrics.get("product_exposure_count", 0) or 0), 0)
    product_click_count = max(int(metrics.get("product_click_count", 0) or 0), 0)
    search_exposure_count = max(int(metrics.get("search_exposure_count", 0) or 0), 0)
    promotion_cost = _money(metrics.get("promotion_cost", 0))

    unit_profit_source = "missing"
    unit_profit = _money(metrics.get("net_profit_per_order", 0))
    if unit_profit > 0:
        unit_profit_source = "metrics"
    else:
        unit_profit = _candidate_unit_profit(top_candidate) if top_candidate else 0
        if unit_profit > 0:
            unit_profit_source = "top_candidate"

    minimum_daily_orders = math.ceil(DAILY_NET_PROFIT_TARGET / unit_profit) if unit_profit > 0 else None
    remaining_orders = (
        max(int(minimum_daily_orders or 0) - current_orders, 0) if minimum_daily_orders is not None else None
    )

    click_rate = (product_click_count / product_exposure_count) if product_exposure_count > 0 else None
    observed_click_to_order_rate = (
        current_orders / product_click_count if product_click_count > 0 and current_orders > 0 else None
    )
    assumption_click_to_order_rate = observed_click_to_order_rate or 0.02
    estimated_clicks_for_target = (
        math.ceil((minimum_daily_orders or 0) / assumption_click_to_order_rate)
        if minimum_daily_orders is not None and assumption_click_to_order_rate > 0
        else None
    )
    estimated_exposures_for_target = (
        math.ceil((estimated_clicks_for_target or 0) / click_rate)
        if estimated_clicks_for_target is not None and click_rate and click_rate > 0
        else None
    )

    if unit_profit <= 0:
        stage = "unit_economics_missing"
    elif product_click_count > 0 and current_orders == 0:
        stage = "detail_conversion_bottleneck"
    elif product_exposure_count > 0 and product_click_count == 0:
        stage = "card_click_bottleneck"
    elif net_profit_verified and current_net_profit >= DAILY_NET_PROFIT_TARGET:
        stage = "target_verified"
    elif current_orders > 0:
        stage = "unit_economics_validation"
    else:
        stage = "traffic_and_listing_validation"

    paid_ads_paused = bool(
        stage in {"unit_economics_missing", "detail_conversion_bottleneck", "card_click_bottleneck"}
        or not net_profit_verified
        or current_orders == 0
    )
    ready_for_paid_scale = bool(
        unit_profit > 0
        and current_orders > 0
        and not paid_ads_paused
        and promotion_cost <= current_net_profit
    )

    actions: List[str] = []
    if unit_profit <= 0:
        actions.append("先核算至少 1 个候选商品的单笔经营净利，再计算 500 元目标需要多少订单")
    elif minimum_daily_orders:
        actions.append(f"按单笔净利 {unit_profit} 元测算，日净利 500 元至少需要 {minimum_daily_orders} 单")

    if stage == "detail_conversion_bottleneck":
        actions.append("已有点击但 0 成交，优先修详情页前半段、SKU 口径、运费、退换说明和主图视频")
    elif stage == "card_click_bottleneck":
        actions.append("已有曝光但点击不足，优先修首图、标题关键词、价格展示和主图视频首帧")
    elif stage == "unit_economics_validation":
        actions.append("已有订单信号后再复核真实运费、佣金、售后损失和推广费，确认单笔净利没有倒挂")
    elif stage == "traffic_and_listing_validation":
        actions.append("先完成上新预检和素材完整度，不投放、不付款、不最终发布，等待真实曝光和点击信号")

    if paid_ads_paused:
        actions.append("当前暂停付费放量；未证明点击能成交且单笔净利为正前，不用投放买流量")
    if search_exposure_count > 0:
        actions.append("已有搜索曝光，标题和详情页要围绕真实袜子场景词承接，但继续遵守无品牌规则")

    return {
        "target_net_profit": DAILY_NET_PROFIT_TARGET,
        "stage": stage,
        "current_state": {
            "snapshot_date": str(metrics.get("snapshot_date") or date.today().isoformat()),
            "net_profit": current_net_profit,
            "net_profit_verified": net_profit_verified,
            "orders_count": current_orders,
            "product_exposure_count": product_exposure_count,
            "product_click_count": product_click_count,
            "search_exposure_count": search_exposure_count,
            "promotion_cost": promotion_cost,
        },
        "unit_economics": {
            "net_profit_per_order": unit_profit,
            "source": unit_profit_source,
            "candidate_record_id": top_candidate.get("record_id") if isinstance(top_candidate, Mapping) else None,
            "candidate_title": top_candidate.get("title") if isinstance(top_candidate, Mapping) else "",
        },
        "target_orders": {
            "minimum_daily_orders": minimum_daily_orders,
            "current_orders": current_orders,
            "remaining_orders_to_target": remaining_orders,
        },
        "traffic_estimate": {
            "observed_product_click_rate_percent": _money(click_rate * 100) if click_rate is not None else None,
            "observed_click_to_order_rate_percent": (
                _money(observed_click_to_order_rate * 100) if observed_click_to_order_rate is not None else None
            ),
            "assumption_click_to_order_rate_percent": _money(assumption_click_to_order_rate * 100),
            "assumption_only": observed_click_to_order_rate is None,
            "estimated_clicks_for_target": estimated_clicks_for_target,
            "estimated_exposures_for_target": estimated_exposures_for_target,
        },
        "scale_readiness": {
            "ready_for_paid_scale": ready_for_paid_scale,
            "reason": (
                "订单、净利和投放成本已具备放量验证条件"
                if ready_for_paid_scale
                else "尚未证明订单转化和真实净利，继续暂停付费放量"
            ),
        },
        "paid_ads_paused": paid_ads_paused,
        "actions": actions,
        "safety_gates": [
            "不调用抖店官方 API",
            "不调用外部 AI 或第三方模型",
            "品牌字段统一无品牌",
            "最终发布、付款和投放扣费保留人工安全闸",
        ],
        "ai_policy": dict(AI_POLICY),
    }


def build_profit_ladder_to_500(
    metrics: Mapping[str, Any],
    product: Mapping[str, Any],
    cost_scenarios: Sequence[Mapping[str, Any]],
    target_net_profit: float = DAILY_NET_PROFIT_TARGET,
) -> Dict[str, Any]:
    """按不同采购成本测算单品到 500 元日净利的订单阶梯。"""

    metric_row = dict(metrics or {})
    product_row = dict(product or {})
    exposure_count = _nonnegative_int(metric_row.get("product_exposure_count"))
    click_count = _nonnegative_int(metric_row.get("product_click_count"))
    orders_count = _nonnegative_int(metric_row.get("orders_count"))
    stage = _ops_stage_from_metrics(metric_row)
    sale_price = _money(product_row.get("sale_price") or product_row.get("price") or 0)
    shipping_cost = _money(product_row.get("shipping_cost", 0))
    packaging_cost = _money(product_row.get("packaging_cost", 0))
    platform_commission_rate = _rate(product_row.get("platform_commission_rate", 0))
    promotion_cost = _money(product_row.get("promotion_cost", metric_row.get("promotion_cost", 0)))
    refund_loss = _money(product_row.get("refund_loss", 0))
    after_sale_loss = _money(product_row.get("after_sale_loss", 0))

    ladder: List[Dict[str, Any]] = []
    for index, scenario in enumerate(cost_scenarios or []):
        scenario_row = dict(scenario or {})
        scenario_id = str(scenario_row.get("scenario_id") or scenario_row.get("id") or f"scenario_{index + 1}")
        goods_cost = _money(scenario_row.get("goods_cost", scenario_row.get("goods_cost_per_order", 0)))
        profit = calculate_operating_profit(
            OperatingCostInput(
                sale_price=sale_price,
                goods_cost=goods_cost,
                shipping_cost=shipping_cost,
                packaging_cost=packaging_cost,
                platform_commission_rate=platform_commission_rate,
                promotion_cost=promotion_cost,
                refund_loss=refund_loss,
                after_sale_loss=after_sale_loss,
            )
        )
        minimum_orders = math.ceil(_money(target_net_profit) / profit.net_profit) if profit.net_profit > 0 else None
        if profit.net_profit <= 0:
            decision = "reject_unprofitable"
        elif minimum_orders and minimum_orders > 200:
            decision = "volume_too_heavy"
        elif orders_count <= 0:
            decision = "first_order_validation_required"
        else:
            decision = "profit_candidate"
        ladder.append({
            "scenario_id": scenario_id,
            "label": str(scenario_row.get("label") or scenario_id),
            "goods_cost": goods_cost,
            "sale_price": profit.sale_price,
            "cost_total": profit.cost_total,
            "platform_commission": profit.platform_commission,
            "net_profit_per_order": profit.net_profit,
            "net_margin_percent": profit.net_margin,
            "minimum_daily_orders_for_500": minimum_orders,
            "decision": decision,
        })

    requires_first_order_validation = orders_count <= 0
    paid_ads_paused = bool(
        requires_first_order_validation
        or stage in {"detail_conversion_bottleneck", "card_click_bottleneck", "need_more_signal"}
        or not bool(metric_row.get("net_profit_verified", False))
    )
    ready_for_paid_scale = bool(
        not paid_ads_paused
        and orders_count > 0
        and bool(metric_row.get("net_profit_verified", False))
    )

    actions: List[str] = []
    if click_count > 0 and orders_count == 0:
        actions.append("已有点击但 0 订单，先修详情页、SKU、价格和运费承接，不投放")
    elif exposure_count > 0 and click_count == 0:
        actions.append("已有曝光但 0 点击，先修首图、标题关键词和商品卡价格展示，不投放")
    else:
        actions.append("先获取真实曝光、点击和订单信号，再评估放量")
    actions.append("逐项确认供应商成本、运费、包装、佣金、退款和售后损失后，再使用阶梯表")
    actions.append("未出现首单且经营净利未核验前，不投放、不采购、不批量备货")

    brand_policy = {
        "required_value": "无品牌",
        "title_use_brand_name_required": False,
        "keyword_brand_comparison_allowed": False,
        "reason": "用户无品牌资质，安全稳健优先",
    }

    return {
        "plan_type": "profit_ladder_to_500",
        "target_net_profit": _money(target_net_profit),
        "stage": stage,
        "product_context": {
            "action_id": _nonnegative_int(product_row.get("action_id") or product_row.get("id")),
            "product_id": str(product_row.get("product_id") or product_row.get("productId") or ""),
            "title": str(product_row.get("title") or ""),
            "sale_price": sale_price,
            "shipping_cost": shipping_cost,
            "packaging_cost": packaging_cost,
            "platform_commission_rate": platform_commission_rate,
            "promotion_cost": promotion_cost,
            "refund_loss": refund_loss,
            "after_sale_loss": after_sale_loss,
        },
        "current_state": {
            "snapshot_id": _nonnegative_int(metric_row.get("id") or metric_row.get("snapshot_id") or metric_row.get("snapshotId")),
            "snapshot_date": str(metric_row.get("snapshot_date") or date.today().isoformat()),
            "orders_count": orders_count,
            "product_exposure_count": exposure_count,
            "product_click_count": click_count,
            "net_profit": _money(metric_row.get("net_profit", 0)),
            "net_profit_verified": bool(metric_row.get("net_profit_verified", False)),
            "promotion_cost": _money(metric_row.get("promotion_cost", 0)),
        },
        "ladder": ladder,
        "requires_cost_confirmation": True,
        "requires_first_order_validation": requires_first_order_validation,
        "paid_ads_paused": paid_ads_paused,
        "ready_for_paid_scale": ready_for_paid_scale,
        "actions": actions,
        "safety_gates": [
            "不调用抖店官方 API",
            "不调用外部 AI 或第三方模型",
            "品牌字段统一无品牌，标题不写品牌词",
            "不自动保存、不发布、不投放、不付款",
            "不自动采购、不批量备货",
        ],
        "brand_policy": brand_policy,
        "no_brand_policy": brand_policy,
        "ai_policy": dict(AI_POLICY),
    }


OBSERVED_SHOP_METRIC_KEYS = (
    "net_profit",
    "gross_sales",
    "orders_count",
    "product_exposure_count",
    "product_click_count",
    "search_exposure_count",
    "refund_amount",
    "after_sale_amount",
    "promotion_cost",
    "experience_score",
)


def merge_observed_shop_metrics(
    metrics: Mapping[str, Any],
    previous_snapshot: Optional[Mapping[str, Any] | Sequence[Mapping[str, Any]]] = None,
) -> Dict[str, Any]:
    """Merge visible-page metrics with the previous snapshot for fields absent from the current page.

    CDP reads only visible text. Some dashboard modules are lazy-loaded, so absence of a label is not evidence of zero.
    Explicitly observed zeros stay zero; only missing fields may inherit the last snapshot value.
    """

    current = copy.deepcopy(dict(metrics or {}))
    if isinstance(previous_snapshot, Mapping):
        previous_snapshots = [dict(previous_snapshot)]
    elif isinstance(previous_snapshot, Sequence) and not isinstance(previous_snapshot, (str, bytes)):
        previous_snapshots = [dict(item) for item in previous_snapshot if isinstance(item, Mapping)]
    else:
        previous_snapshots = []
    raw_payload = current.get("raw_payload") if isinstance(current.get("raw_payload"), Mapping) else {}
    observed_metric_keys = raw_payload.get("observed_metric_keys")
    if isinstance(observed_metric_keys, Sequence) and not isinstance(observed_metric_keys, (str, bytes)):
        observed = {str(key) for key in observed_metric_keys}
    else:
        observed = {key for key in OBSERVED_SHOP_METRIC_KEYS if key in current}

    def previous_raw_payload(row: Mapping[str, Any]) -> Dict[str, Any]:
        raw = row.get("raw_payload") if isinstance(row.get("raw_payload"), Mapping) else None
        if raw is not None:
            return dict(raw)
        raw_json = row.get("raw_payload_json")
        if isinstance(raw_json, str) and raw_json.strip():
            try:
                parsed = json.loads(raw_json)
            except Exception:
                return {}
            if isinstance(parsed, Mapping):
                return dict(parsed)
        return {}

    def previous_has_trustworthy_value(row: Mapping[str, Any], key: str) -> bool:
        if row.get(key) in (None, ""):
            return False
        raw = previous_raw_payload(row)
        observed_keys = raw.get("observed_metric_keys")
        merged_keys = raw.get("merged_missing_metric_keys")
        has_observed_list = isinstance(observed_keys, Sequence) and not isinstance(observed_keys, (str, bytes))
        has_merged_list = isinstance(merged_keys, Sequence) and not isinstance(merged_keys, (str, bytes))
        if has_observed_list:
            observed_set = {str(item) for item in observed_keys}
            merged_set = {str(item) for item in merged_keys} if has_merged_list else set()
            return key in observed_set or key in merged_set
        return True

    previous_used: Optional[Mapping[str, Any]] = None
    merged_missing: List[str] = []
    for key in OBSERVED_SHOP_METRIC_KEYS:
        if key in observed or key in current:
            continue
        for previous in previous_snapshots:
            if not previous_has_trustworthy_value(previous, key):
                continue
            current[key] = previous.get(key)
            merged_missing.append(key)
            if previous_used is None:
                previous_used = previous
            break

    next_raw_payload = copy.deepcopy(dict(raw_payload))
    next_raw_payload["observed_metric_keys"] = sorted(observed)
    next_raw_payload["merged_missing_metric_keys"] = merged_missing
    if merged_missing:
        next_raw_payload["merged_from_previous_snapshot_id"] = previous_used.get("id") if previous_used else None
        note = str(current.get("notes") or "")
        suffix = f" 缺失字段沿用上一快照: {', '.join(merged_missing)}。"
        current["notes"] = note + suffix if note else suffix.strip()
    current["raw_payload"] = next_raw_payload
    return current


def build_daily_plan(metrics: Mapping[str, Any]) -> Dict[str, Any]:
    net_profit = _money(metrics.get("net_profit", 0))
    net_profit_verified = bool(metrics.get("net_profit_verified", "net_profit" in metrics))
    orders_count = int(metrics.get("orders_count", 0) or 0)
    product_exposure_count = max(int(metrics.get("product_exposure_count", 0) or 0), 0)
    product_click_count = max(int(metrics.get("product_click_count", 0) or 0), 0)
    search_exposure_count = max(int(metrics.get("search_exposure_count", 0) or 0), 0)
    product_click_rate = (
        _money((product_click_count / product_exposure_count) * 100) if product_exposure_count > 0 else None
    )
    ready_products = int(metrics.get("ready_products", 0) or 0)
    blocked_products = int(metrics.get("blocked_products", 0) or 0)
    low_stock_products = int(metrics.get("low_stock_products", 0) or 0)
    profit_gap = _money(max(DAILY_NET_PROFIT_TARGET - net_profit, 0)) if net_profit_verified else None
    actions: List[str] = []

    if product_exposure_count > 0 and product_click_count == 0:
        actions.append(
            f"已有 {product_exposure_count} 个商品曝光但点击为 0，暂停付费投放，优先优化首图、主图视频、标题关键词和价格展示"
        )
    elif product_click_count > 0 and orders_count == 0:
        actions.append(
            f"已有 {product_click_count} 个商品点击但成交为 0，优先复核详情页承接、SKU 清晰度、运费和售价"
        )
    if blocked_products > 0:
        actions.append(f"优先处理 {blocked_products} 个发布阻塞商品")
    if ready_products > 0:
        actions.append(f"从 {ready_products} 个可发布商品中选择高净利款低预算试卖")
    if low_stock_products > 0:
        actions.append(f"复核 {low_stock_products} 个低库存商品，按实销补货")
    if not net_profit_verified:
        actions.append("还没有可核算净利，先同步订单明细、商品成本、运费、退款和推广消耗")
    elif profit_gap and profit_gap > 0:
        actions.append(f"当前距日净利目标还差 {profit_gap} 元，优先提升高净利 SKU 的成交")
    if not actions:
        actions.append("保持只读复盘，等待新的订单或商品数据")

    market_context = build_market_context(metrics)
    diagnostic_signals = _diagnostic_signals_from_metrics(metrics)
    diagnostic_action_plan = build_diagnostic_action_plan(diagnostic_signals)
    if diagnostic_signals:
        actions.extend(diagnostic_action_plan["actions"])
    growth_bottleneck_plan = build_growth_bottleneck_plan(metrics)

    profit_ramp_plan = build_profit_ramp_plan(metrics)

    return {
        "snapshot_date": str(metrics.get("snapshot_date") or date.today().isoformat()),
        "target_net_profit": DAILY_NET_PROFIT_TARGET,
        "net_profit": net_profit,
        "net_profit_verified": net_profit_verified,
        "profit_gap": profit_gap,
        "orders_count": orders_count,
        "gross_sales": _money(metrics.get("gross_sales", 0)),
        "product_exposure_count": product_exposure_count,
        "product_click_count": product_click_count,
        "product_click_rate": product_click_rate,
        "search_exposure_count": search_exposure_count,
        "promotion_cost": _money(metrics.get("promotion_cost", 0)),
        "refund_amount": _money(metrics.get("refund_amount", 0)),
        "after_sale_amount": _money(metrics.get("after_sale_amount", 0)),
        "experience_score": metrics.get("experience_score"),
        "ready_products": ready_products,
        "blocked_products": blocked_products,
        "low_stock_products": low_stock_products,
        "actions": actions,
        "market_context": market_context,
        "diagnostic_action_plan": diagnostic_action_plan,
        "growth_bottleneck_plan": growth_bottleneck_plan,
        "profit_ramp_plan": profit_ramp_plan,
        "ai_policy": dict(AI_POLICY),
    }


def build_daily_review(metrics: Mapping[str, Any], candidates: Iterable[Mapping[str, Any]]) -> Dict[str, Any]:
    daily_plan = build_daily_plan(metrics)
    net_profit_verified = bool(daily_plan.get("net_profit_verified"))
    verified_net_profit_achieved = bool(
        net_profit_verified and float(daily_plan.get("net_profit") or 0) >= DAILY_NET_PROFIT_TARGET
    )
    goal_status = "achieved" if verified_net_profit_achieved else "not_verified" if not net_profit_verified else "below_target"
    candidate_rows = list(candidates or [])
    top_candidate = candidate_rows[0] if candidate_rows else None
    actions = list(daily_plan.get("actions") or [])

    if top_candidate:
        evaluation = top_candidate.get("evaluation") if isinstance(top_candidate.get("evaluation"), dict) else {}
        stock_plan = top_candidate.get("stock_plan") if isinstance(top_candidate.get("stock_plan"), dict) else {}
        record_id = top_candidate.get("record_id")
        recommended_sale_price = _money(top_candidate.get("recommended_sale_price", 0))
        net_profit_per_order = _money(evaluation.get("net_profit_per_order", 0))
        target_orders = evaluation.get("target_daily_orders")
        total_stock = stock_plan.get("total_recommended_stock")
        actions.append(
            f"候选商品 {record_id} 建议售价 {recommended_sale_price} 元，单笔净利约 {net_profit_per_order} 元"
        )
        if target_orders:
            actions.append(f"按当前测算，达成 500 元日净利需要约 {target_orders} 单，先做低预算验证")
        if total_stock:
            actions.append(f"上架前试卖备货 {total_stock} 件，避免无销量信号时压库存")
        for warning in top_candidate.get("warnings") or []:
            actions.append(str(warning))
    else:
        actions.append("本地暂无可评估商品候选，需要先采集或导入袜子商品")

    market_context = build_market_context(metrics)
    growth_bottleneck_plan = build_growth_bottleneck_plan(metrics, top_candidate)
    profit_ramp_plan = build_profit_ramp_plan(metrics, candidate_rows)
    daily_plan["market_context"] = market_context
    daily_plan["growth_bottleneck_plan"] = growth_bottleneck_plan
    daily_plan["profit_ramp_plan"] = profit_ramp_plan

    return {
        "snapshot_date": daily_plan.get("snapshot_date"),
        "target_net_profit": DAILY_NET_PROFIT_TARGET,
        "goal_status": goal_status,
        "verified_net_profit_achieved": verified_net_profit_achieved,
        "daily_plan": daily_plan,
        "top_candidate": top_candidate,
        "candidate_count": len(candidate_rows),
        "actions": actions,
        "market_context": market_context,
        "growth_bottleneck_plan": growth_bottleneck_plan,
        "profit_ramp_plan": profit_ramp_plan,
        "ai_policy": dict(AI_POLICY),
    }


def enforce_no_external_ai_settings(settings: Mapping[str, Any]) -> Dict[str, Any]:
    sanitized = copy.deepcopy(dict(settings or {}))
    sanitized["model_configs"] = []
    sanitized["ai_policy"] = dict(AI_POLICY)
    return sanitized


def _compact_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _snapshot_text_values(snapshot: Mapping[str, Any]) -> List[str]:
    values: List[str] = []
    for key in ("url", "title", "body_text", "brand_text"):
        value = _compact_text(snapshot.get(key))
        if value:
            values.append(value)
    for key in ("title_values", "brand_texts"):
        raw_items = snapshot.get(key)
        if isinstance(raw_items, Sequence) and not isinstance(raw_items, (str, bytes)):
            for item in raw_items:
                value = _compact_text(item)
                if value:
                    values.append(value)
    for key in ("visible_fields", "field_items", "visible_controls", "control_items"):
        raw_items = snapshot.get(key)
        if not isinstance(raw_items, Sequence) or isinstance(raw_items, (str, bytes)):
            continue
        for item in raw_items:
            if isinstance(item, Mapping):
                for field_key in ("field_id", "text", "value", "label"):
                    value = _compact_text(item.get(field_key))
                    if value:
                        values.append(value)
            else:
                value = _compact_text(item)
                if value:
                    values.append(value)
    return values


def _text_confirms_explicit_no_brand_field(value: Any) -> bool:
    text = _compact_text(value)
    if "无品牌" not in text:
        return False
    return bool(re.search(r"(^|[|；;，,\s])\*?\s*品牌\s*[:：]?\s*无品牌($|[|；;，,\s])", text))


def _split_brand_text_candidates(value: Any) -> List[str]:
    raw = str(value or "")
    if not raw.strip():
        return []
    return [item for item in re.split(r"\s*\|\s*|\r?\n", raw) if item.strip()]


def _snapshot_confirms_no_brand_field(snapshot: Mapping[str, Any]) -> bool:
    """Only accept evidence that explicitly belongs to the brand field.

    The publish/edit page also contains title controls such as "使用品牌名"; full-page
    text can therefore include both "品牌" and "无品牌" without proving that the
    category attribute brand field is actually set to "无品牌".
    """

    for key in ("brand_text", "brandText"):
        for item in _split_brand_text_candidates(snapshot.get(key)):
            if _text_confirms_explicit_no_brand_field(item):
                return True

    for key in ("brand_texts", "brandTexts"):
        raw_items = snapshot.get(key)
        if not isinstance(raw_items, Sequence) or isinstance(raw_items, (str, bytes)):
            continue
        for raw_item in raw_items:
            for item in _split_brand_text_candidates(raw_item):
                if _text_confirms_explicit_no_brand_field(item):
                    return True

    for key in ("visible_fields", "field_items", "visibleFields", "fieldItems"):
        raw_items = snapshot.get(key)
        if not isinstance(raw_items, Sequence) or isinstance(raw_items, (str, bytes)):
            continue
        for raw_item in raw_items:
            if isinstance(raw_item, Mapping):
                field_id = _compact_text(raw_item.get("field_id") or raw_item.get("fieldId"))
                label = _compact_text(raw_item.get("label"))
                text = _compact_text(raw_item.get("text"))
                value = _compact_text(raw_item.get("value"))
                if field_id == "品牌" or label == "品牌":
                    if "无品牌" in " ".join(item for item in (text, value, label) if item):
                        return True
                if _text_confirms_explicit_no_brand_field(" ".join(item for item in (field_id, label, text, value) if item)):
                    return True
            elif _text_confirms_explicit_no_brand_field(raw_item):
                return True

    return False


def _add_preflight_blocker(blockers: List[Dict[str, str]], code: str, message: str) -> None:
    blockers.append({"code": code, "message": message})


def build_publish_preflight_safety(
    page_snapshot: Optional[Mapping[str, Any]] = None,
    expected_product_id: str = "",
    expected_title: str = "",
    candidate_video_path: str = "",
) -> Dict[str, Any]:
    """Build a local safety gate before any platform-side upload/save/publish action."""

    snapshot = dict(page_snapshot or {})
    text_values = _snapshot_text_values(snapshot)
    text_blob = " ".join(text_values)
    text_blob_lower = text_blob.lower()
    url = str(snapshot.get("url") or "").strip()
    url_lower = url.lower()
    blockers: List[Dict[str, str]] = []
    warnings: List[str] = []

    if "jinritemai.com" not in url_lower:
        _add_preflight_blocker(blockers, "not_fxg_page", "当前浏览器页面不是抖店页面")
    if "/login" in url_lower or "login/common" in url_lower:
        _add_preflight_blocker(blockers, "fxg_login_page", "当前浏览器仍在登录页")

    expected_product_id = str(expected_product_id or "").strip()
    if expected_product_id and expected_product_id not in url and expected_product_id not in text_blob:
        _add_preflight_blocker(
            blockers,
            "not_expected_product_page",
            f"当前页面不能证明是目标商品 {expected_product_id}",
        )

    expected_title = _compact_text(expected_title)
    if expected_title:
        title_values = [_compact_text(item) for item in snapshot.get("title_values") or []]
        title_matched = expected_title in text_blob or any(expected_title == item for item in title_values)
        if not title_matched:
            _add_preflight_blocker(blockers, "title_not_confirmed", "当前页面未确认目标商品标题")

    brand_confirmed = _snapshot_confirms_no_brand_field(snapshot)
    if not brand_confirmed:
        _add_preflight_blocker(blockers, "brand_not_confirmed_no_brand", "当前页面未确认品牌为无品牌")

    checked_value = snapshot.get("title_use_brand_name_checked")
    if checked_value is True:
        _add_preflight_blocker(blockers, "title_use_brand_name_enabled", "标题区使用品牌名处于勾选状态")
    elif checked_value is None:
        _add_preflight_blocker(blockers, "title_use_brand_name_unknown", "当前页面无法确认使用品牌名是否关闭")

    candidate_video_path = str(candidate_video_path or "").strip()
    candidate_video_exists = False
    if candidate_video_path:
        candidate_video_exists = Path(candidate_video_path).is_file()
        if not candidate_video_exists:
            _add_preflight_blocker(blockers, "candidate_video_missing", "候选主图视频文件不存在")
    else:
        warnings.append("未提供候选主图视频路径；本次只能做页面安全预检")

    risky_keywords = (
        "保存",
        "发布商品",
        "保存草稿",
        "填写检查",
        "立即优化",
        "一键优化",
        "开启AI自动生成",
        "AI智能识图填写",
        "销量助推",
        "投放",
        "付款",
    )
    risky_controls: List[str] = []
    for raw_item in snapshot.get("visible_controls") or snapshot.get("control_items") or []:
        if isinstance(raw_item, Mapping):
            item_text = _compact_text(raw_item.get("text") or raw_item.get("value") or raw_item.get("label"))
        else:
            item_text = _compact_text(raw_item)
        if not item_text:
            continue
        for keyword in risky_keywords:
            if keyword in item_text and keyword not in risky_controls:
                risky_controls.append(keyword)

    interfering_overlays: List[str] = []
    for raw_item in snapshot.get("visible_overlays") or snapshot.get("overlay_items") or []:
        if isinstance(raw_item, Mapping):
            overlay_text = _compact_text(raw_item.get("text") or raw_item.get("label"))
        else:
            overlay_text = _compact_text(raw_item)
        if overlay_text:
            interfering_overlays.append(overlay_text[:160])
    if interfering_overlays:
        _add_preflight_blocker(
            blockers,
            "interfering_overlay_visible",
            "当前页面存在可见引导或弹层，需先关闭后再做上传预检",
        )

    ready_for_upload_preflight = not blockers
    return {
        "ready_for_upload_preflight": ready_for_upload_preflight,
        "safe_to_save_or_publish": False,
        "blockers": blockers,
        "warnings": warnings,
        "page": {
            "url": url,
            "title": snapshot.get("title") or "",
        },
        "expected_product_id": expected_product_id,
        "expected_title": expected_title,
        "candidate_video_path": candidate_video_path,
        "candidate_video_exists": candidate_video_exists,
        "risky_controls_visible": risky_controls,
        "interfering_overlays": interfering_overlays,
        "allowed_next_actions": [
            "仅允许在人工安全闸下上传素材并截停在保存/发布前"
        ] if ready_for_upload_preflight else [
            "先修复 blockers，再进入素材上传预检"
        ],
        "forbidden_actions": [
            "保存",
            "保存草稿",
            "发布商品",
            "填写检查",
            "平台 AI 自动生成",
            "投放",
            "付款",
        ],
        "brand_policy": {
            "required_value": "无品牌",
            "title_use_brand_name_required": False,
            "reason": "当前无品牌资质，安全稳健优先",
        },
        "ai_policy": dict(AI_POLICY),
    }


def build_main_video_upload_stop_gate(
    preflight: Optional[Mapping[str, Any]] = None,
    *,
    upload_attempted: bool = False,
    upload_result: Optional[Mapping[str, Any]] = None,
    post_upload_snapshot: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Build the safety gate for uploading only the main video, then stopping before save/publish."""

    preflight_data = dict(preflight or {})
    blockers: List[Dict[str, str]] = []
    warnings: List[str] = []

    if not preflight_data.get("ready_for_upload_preflight"):
        _add_preflight_blocker(blockers, "preflight_not_ready", "上传前安全预检未通过")

    if preflight_data.get("safe_to_save_or_publish") is not False:
        _add_preflight_blocker(blockers, "save_publish_gate_not_locked", "保存/发布安全闸未锁定")

    if not preflight_data.get("candidate_video_path") or not preflight_data.get("candidate_video_exists"):
        _add_preflight_blocker(blockers, "candidate_video_not_confirmed", "候选主图视频未确认存在")

    brand_policy = preflight_data.get("brand_policy") if isinstance(preflight_data.get("brand_policy"), Mapping) else {}
    if (
        brand_policy.get("required_value") != "无品牌"
        or brand_policy.get("title_use_brand_name_required") is not False
    ):
        _add_preflight_blocker(blockers, "brand_policy_not_no_brand", "品牌策略必须固定为无品牌且不使用标题品牌名")

    snapshot = dict(post_upload_snapshot or {})
    post_url = str(snapshot.get("url") or "").lower()
    if upload_attempted and post_url:
        if "jinritemai.com" not in post_url:
            _add_preflight_blocker(blockers, "post_upload_left_fxg_page", "上传后页面离开抖店域名")
        if "/login" in post_url or "login/common" in post_url:
            _add_preflight_blocker(blockers, "post_upload_login_page", "上传后页面进入登录页")

    if upload_attempted and snapshot:
        post_text_blob = " ".join(_snapshot_text_values(snapshot))
        if "品牌" in post_text_blob and "无品牌" not in post_text_blob:
            _add_preflight_blocker(blockers, "post_upload_brand_not_no_brand", "上传后页面品牌状态不是无品牌")
        if snapshot.get("title_use_brand_name_checked") is True:
            _add_preflight_blocker(blockers, "post_upload_title_brand_enabled", "上传后标题区使用品牌名被勾选")

    if upload_attempted and not upload_result:
        warnings.append("已标记上传尝试，但缺少上传结果详情")

    ready_to_attempt_upload = not blockers
    return {
        "ready_to_attempt_upload": ready_to_attempt_upload,
        "upload_attempted": bool(upload_attempted),
        "allowed_platform_mutation": "main_video_upload_only",
        "save_publish_performed": False,
        "no_save": True,
        "no_publish": True,
        "no_ad_or_payment": True,
        "blockers": blockers,
        "warnings": warnings,
        "preflight": preflight_data,
        "upload_result": dict(upload_result or {}),
        "post_upload_page": {
            "url": snapshot.get("url") or "",
            "title": snapshot.get("title") or "",
        },
        "brand_policy": {
            "required_value": "无品牌",
            "title_use_brand_name_required": False,
            "reason": "当前无品牌资质，安全稳健优先",
        },
        "forbidden_actions": [
            "保存",
            "保存草稿",
            "发布商品",
            "填写检查",
            "平台 AI 自动生成",
            "投放",
            "付款",
        ],
        "ai_policy": dict(AI_POLICY),
    }


def _compact_issue_action_for_evidence(issue_action: Optional[Mapping[str, Any]] = None) -> Optional[Dict[str, Any]]:
    if not isinstance(issue_action, Mapping):
        return None
    return {
        key: value
        for key, value in dict(issue_action).items()
        if key not in {"evidence", "evidence_json"}
    }


def build_publish_preflight_evidence(
    preflight: Mapping[str, Any],
    *,
    record: Optional[Mapping[str, Any]] = None,
    issue_action: Optional[Mapping[str, Any]] = None,
    existing_evidence: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Build ledger evidence for a read-only preflight without downgrading prior upload evidence."""

    existing = copy.deepcopy(dict(existing_evidence or {}))
    preserved_upload = bool(
        existing.get("mutation_type") == "main_video_upload_only"
        or isinstance(existing.get("upload_result"), Mapping)
    )

    if preserved_upload:
        evidence = existing
        evidence["latest_preflight"] = dict(preflight or {})
    else:
        evidence = {
            "preflight": dict(preflight or {}),
            "shop_mutation": False,
            "no_upload": True,
        }

    evidence["record"] = dict(record or {}) if isinstance(record, Mapping) else record
    evidence["issue_action"] = _compact_issue_action_for_evidence(issue_action)
    evidence["no_save"] = True
    evidence["no_publish"] = True
    evidence["no_ad_or_payment"] = True
    return evidence


def build_save_edit_human_gate(
    preflight: Optional[Mapping[str, Any]] = None,
    *,
    upload_evidence: Optional[Mapping[str, Any]] = None,
    page_snapshot: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a save-readiness gate that still requires human confirmation."""

    preflight_data = dict(preflight or {})
    evidence = dict(upload_evidence or {})
    snapshot = dict(page_snapshot or {})
    main_video_field = (
        snapshot.get("main_video_field")
        if isinstance(snapshot.get("main_video_field"), Mapping)
        else {}
    )
    blockers: List[Dict[str, str]] = []

    if not preflight_data.get("ready_for_upload_preflight"):
        _add_preflight_blocker(blockers, "preflight_not_ready", "保存前页面安全预检未通过")

    if preflight_data.get("safe_to_save_or_publish") is not False:
        _add_preflight_blocker(blockers, "auto_save_gate_not_locked", "自动保存安全闸必须保持关闭")

    brand_policy = preflight_data.get("brand_policy") if isinstance(preflight_data.get("brand_policy"), Mapping) else {}
    if (
        brand_policy.get("required_value") != "无品牌"
        or brand_policy.get("title_use_brand_name_required") is not False
    ):
        _add_preflight_blocker(blockers, "brand_policy_not_no_brand", "保存前品牌策略必须固定为无品牌")

    upload_result = evidence.get("upload_result") if isinstance(evidence.get("upload_result"), Mapping) else {}
    if evidence.get("mutation_type") != "main_video_upload_only":
        _add_preflight_blocker(blockers, "main_video_upload_evidence_missing", "账本缺少主图视频上传截停证据")
    if not upload_result.get("upload_triggered") or not upload_result.get("upload_confirmed"):
        _add_preflight_blocker(blockers, "main_video_upload_not_confirmed", "主图视频上传未确认完成")

    if not main_video_field.get("exists"):
        _add_preflight_blocker(blockers, "main_video_field_missing", "页面缺少主图视频区域")
    if main_video_field.get("upload_busy"):
        _add_preflight_blocker(blockers, "main_video_upload_busy", "主图视频仍处于上传中")
    if not main_video_field.get("has_success_card"):
        _add_preflight_blocker(blockers, "main_video_success_card_missing", "页面未确认主图视频成功素材卡")

    page_url = str(snapshot.get("url") or "").lower()
    if page_url:
        if "jinritemai.com" not in page_url:
            _add_preflight_blocker(blockers, "not_fxg_page", "当前页面不是抖店页面")
        if "/login" in page_url or "login/common" in page_url:
            _add_preflight_blocker(blockers, "fxg_login_page", "当前页面仍在登录页")

    return {
        "ready_for_human_save_confirmation": not blockers,
        "safe_to_auto_save": False,
        "requires_human_confirmation": True,
        "allowed_next_action": "human_confirm_save_current_edit_page" if not blockers else "fix_blockers_before_save_confirmation",
        "blockers": blockers,
        "preflight": preflight_data,
        "upload_evidence_summary": {
            "mutation_type": evidence.get("mutation_type") or "",
            "upload_triggered": bool(upload_result.get("upload_triggered")),
            "upload_confirmed": bool(upload_result.get("upload_confirmed")),
        },
        "page": {
            "url": snapshot.get("url") or "",
            "title": snapshot.get("title") or "",
        },
        "main_video_field": dict(main_video_field),
        "no_publish": True,
        "no_ad_or_payment": True,
        "forbidden_actions": [
            "自动保存",
            "发布商品",
            "保存草稿",
            "填写检查",
            "平台 AI 自动生成",
            "投放",
            "付款",
        ],
        "brand_policy": {
            "required_value": "无品牌",
            "title_use_brand_name_required": False,
            "reason": "当前无品牌资质，安全稳健优先",
        },
        "ai_policy": dict(AI_POLICY),
    }


class OpsLedger:
    """本地运营账本。"""

    def __init__(self, db_path: Optional[Path | str] = None) -> None:
        if db_path is None:
            db_path = resolve_ops_ledger_path()
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        conn = self._connect()
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def initialize_schema(self) -> None:
        with self._connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ops_daily_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    snapshot_date TEXT NOT NULL,
                    target_net_profit REAL NOT NULL DEFAULT 500,
                    net_profit REAL NOT NULL DEFAULT 0,
                    net_profit_verified INTEGER NOT NULL DEFAULT 0,
                    gross_sales REAL NOT NULL DEFAULT 0,
                    orders_count INTEGER NOT NULL DEFAULT 0,
                    product_exposure_count INTEGER NOT NULL DEFAULT 0,
                    product_click_count INTEGER NOT NULL DEFAULT 0,
                    search_exposure_count INTEGER NOT NULL DEFAULT 0,
                    refund_amount REAL NOT NULL DEFAULT 0,
                    after_sale_amount REAL NOT NULL DEFAULT 0,
                    promotion_cost REAL NOT NULL DEFAULT 0,
                    experience_score REAL,
                    source TEXT NOT NULL DEFAULT 'manual',
                    status TEXT NOT NULL DEFAULT 'partial',
                    notes TEXT,
                    raw_payload_json TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )
            self._ensure_daily_snapshot_columns(conn)
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ops_product_profit_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    record_id INTEGER NOT NULL,
                    snapshot_date TEXT NOT NULL,
                    title TEXT,
                    sale_price REAL NOT NULL DEFAULT 0,
                    goods_cost REAL NOT NULL DEFAULT 0,
                    net_profit_per_order REAL NOT NULL DEFAULT 0,
                    expected_daily_net_profit REAL NOT NULL DEFAULT 0,
                    decision TEXT NOT NULL,
                    rationale TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ops_stock_plans (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    record_id INTEGER NOT NULL,
                    sku_count INTEGER NOT NULL,
                    per_sku_stock INTEGER NOT NULL,
                    total_recommended_stock INTEGER NOT NULL,
                    risk_level TEXT NOT NULL,
                    rationale TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ops_browser_metric_audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    metric_name TEXT NOT NULL,
                    metric_value TEXT,
                    source TEXT NOT NULL DEFAULT 'browser',
                    page_url TEXT,
                    status TEXT NOT NULL DEFAULT 'observed',
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ops_strategy_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    snapshot_date TEXT NOT NULL,
                    product_count INTEGER NOT NULL DEFAULT 0,
                    excellent_product_count INTEGER NOT NULL DEFAULT 0,
                    missing_main_video_count INTEGER NOT NULL DEFAULT 0,
                    missing_spec_image_count INTEGER NOT NULL DEFAULT 0,
                    missing_live_replay_count INTEGER NOT NULL DEFAULT 0,
                    attribute_optimization_count INTEGER NOT NULL DEFAULT 0,
                    risk_product_count INTEGER NOT NULL DEFAULT 0,
                    opportunity_keywords_json TEXT NOT NULL DEFAULT '[]',
                    refund_reasons_json TEXT NOT NULL DEFAULT '{}',
                    source TEXT NOT NULL DEFAULT 'browser',
                    status TEXT NOT NULL DEFAULT 'strategy_signals_observed',
                    raw_payload_json TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ops_product_issue_actions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    strategy_snapshot_id INTEGER NOT NULL,
                    product_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    quality_score INTEGER NOT NULL DEFAULT 0,
                    recent_30d_sales INTEGER NOT NULL DEFAULT 0,
                    issues_json TEXT NOT NULL DEFAULT '[]',
                    priority_rank INTEGER NOT NULL,
                    action_status TEXT NOT NULL DEFAULT 'open',
                    action_note TEXT,
                    evidence_json TEXT NOT NULL DEFAULT '{}',
                    resolved_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            self._ensure_product_issue_action_columns(conn)
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ops_product_issue_action_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    action_id INTEGER NOT NULL,
                    old_status TEXT NOT NULL,
                    new_status TEXT NOT NULL,
                    note TEXT,
                    evidence_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ops_product_record_mappings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    action_id INTEGER,
                    product_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    record_id INTEGER,
                    record_title TEXT,
                    record_path TEXT,
                    confidence REAL NOT NULL DEFAULT 0,
                    match_status TEXT NOT NULL,
                    reason TEXT,
                    evidence_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                )
                """
            )

    def _ensure_daily_snapshot_columns(self, conn: sqlite3.Connection) -> None:
        columns = {str(row["name"]) for row in conn.execute("PRAGMA table_info(ops_daily_snapshots)").fetchall()}
        migrations = [
            ("net_profit_verified", "ALTER TABLE ops_daily_snapshots ADD COLUMN net_profit_verified INTEGER NOT NULL DEFAULT 0"),
            ("orders_count", "ALTER TABLE ops_daily_snapshots ADD COLUMN orders_count INTEGER NOT NULL DEFAULT 0"),
            ("product_exposure_count", "ALTER TABLE ops_daily_snapshots ADD COLUMN product_exposure_count INTEGER NOT NULL DEFAULT 0"),
            ("product_click_count", "ALTER TABLE ops_daily_snapshots ADD COLUMN product_click_count INTEGER NOT NULL DEFAULT 0"),
            ("search_exposure_count", "ALTER TABLE ops_daily_snapshots ADD COLUMN search_exposure_count INTEGER NOT NULL DEFAULT 0"),
            ("refund_amount", "ALTER TABLE ops_daily_snapshots ADD COLUMN refund_amount REAL NOT NULL DEFAULT 0"),
            ("after_sale_amount", "ALTER TABLE ops_daily_snapshots ADD COLUMN after_sale_amount REAL NOT NULL DEFAULT 0"),
            ("experience_score", "ALTER TABLE ops_daily_snapshots ADD COLUMN experience_score REAL"),
            ("raw_payload_json", "ALTER TABLE ops_daily_snapshots ADD COLUMN raw_payload_json TEXT"),
        ]
        for column, statement in migrations:
            if column not in columns:
                conn.execute(statement)

    def _ensure_product_issue_action_columns(self, conn: sqlite3.Connection) -> None:
        columns = {str(row["name"]) for row in conn.execute("PRAGMA table_info(ops_product_issue_actions)").fetchall()}
        migrations = [
            ("action_note", "ALTER TABLE ops_product_issue_actions ADD COLUMN action_note TEXT"),
            ("evidence_json", "ALTER TABLE ops_product_issue_actions ADD COLUMN evidence_json TEXT NOT NULL DEFAULT '{}'"),
            ("resolved_at", "ALTER TABLE ops_product_issue_actions ADD COLUMN resolved_at TEXT"),
        ]
        for column, statement in migrations:
            if column not in columns:
                conn.execute(statement)

    def save_daily_snapshot(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        created_at = datetime.now().isoformat(timespec="seconds")
        has_net_profit = "net_profit" in payload
        raw_payload = payload.get("raw_payload")
        if raw_payload is None:
            raw_payload_json = ""
        elif isinstance(raw_payload, str):
            raw_payload_json = raw_payload
        else:
            raw_payload_json = json.dumps(raw_payload, ensure_ascii=False, sort_keys=True)
        row = {
            "snapshot_date": str(payload.get("snapshot_date") or date.today().isoformat()),
            "target_net_profit": _money(payload.get("target_net_profit", DAILY_NET_PROFIT_TARGET)),
            "net_profit": _money(payload.get("net_profit", 0)),
            "net_profit_verified": 1 if bool(payload.get("net_profit_verified", has_net_profit)) else 0,
            "gross_sales": _money(payload.get("gross_sales", 0)),
            "orders_count": max(int(payload.get("orders_count", 0) or 0), 0),
            "product_exposure_count": max(int(payload.get("product_exposure_count", 0) or 0), 0),
            "product_click_count": max(int(payload.get("product_click_count", 0) or 0), 0),
            "search_exposure_count": max(int(payload.get("search_exposure_count", 0) or 0), 0),
            "refund_amount": _money(payload.get("refund_amount", 0)),
            "after_sale_amount": _money(payload.get("after_sale_amount", 0)),
            "promotion_cost": _money(payload.get("promotion_cost", 0)),
            "experience_score": None if payload.get("experience_score") in (None, "") else _money(payload.get("experience_score")),
            "source": str(payload.get("source") or "manual"),
            "status": str(payload.get("status") or "partial"),
            "notes": str(payload.get("notes") or ""),
            "raw_payload_json": raw_payload_json,
            "created_at": created_at,
        }
        with self._connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO ops_daily_snapshots (
                    snapshot_date, target_net_profit, net_profit, net_profit_verified,
                    gross_sales, orders_count, product_exposure_count,
                    product_click_count, search_exposure_count, refund_amount,
                    after_sale_amount, promotion_cost, experience_score, source, status, notes,
                    raw_payload_json, created_at
                ) VALUES (
                    :snapshot_date, :target_net_profit, :net_profit, :net_profit_verified,
                    :gross_sales, :orders_count, :product_exposure_count,
                    :product_click_count, :search_exposure_count, :refund_amount,
                    :after_sale_amount, :promotion_cost, :experience_score, :source, :status, :notes,
                    :raw_payload_json, :created_at
                )
                """,
                row,
            )
            row["id"] = int(cursor.lastrowid)
        row["net_profit_verified"] = bool(row["net_profit_verified"])
        return row

    def list_daily_snapshots(self, limit: int = 20) -> List[Dict[str, Any]]:
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM ops_daily_snapshots
                ORDER BY snapshot_date DESC, id DESC
                LIMIT ?
                """,
                (max(int(limit or 20), 1),),
            ).fetchall()
        result = [dict(row) for row in rows]
        for row in result:
            row["net_profit_verified"] = bool(row.get("net_profit_verified"))
        return result

    def save_product_evaluation(self, evaluation: ProductEvaluation) -> Dict[str, Any]:
        created_at = datetime.now().isoformat(timespec="seconds")
        row = {
            "record_id": evaluation.record_id,
            "snapshot_date": date.today().isoformat(),
            "title": evaluation.title,
            "sale_price": _money(evaluation.profit.get("sale_price", 0)),
            "goods_cost": _money(evaluation.profit.get("goods_cost", 0)),
            "net_profit_per_order": evaluation.net_profit_per_order,
            "expected_daily_net_profit": evaluation.expected_daily_net_profit,
            "decision": evaluation.decision,
            "rationale": evaluation.rationale,
            "created_at": created_at,
        }
        with self._connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO ops_product_profit_snapshots (
                    record_id, snapshot_date, title, sale_price, goods_cost,
                    net_profit_per_order, expected_daily_net_profit, decision,
                    rationale, created_at
                ) VALUES (
                    :record_id, :snapshot_date, :title, :sale_price, :goods_cost,
                    :net_profit_per_order, :expected_daily_net_profit, :decision,
                    :rationale, :created_at
                )
                """,
                row,
            )
            row["id"] = int(cursor.lastrowid)
        return row

    def save_stock_plan(self, stock_plan: StockPlan) -> Dict[str, Any]:
        created_at = datetime.now().isoformat(timespec="seconds")
        row = {
            "record_id": stock_plan.record_id,
            "sku_count": stock_plan.sku_count,
            "per_sku_stock": stock_plan.per_sku_stock,
            "total_recommended_stock": stock_plan.total_recommended_stock,
            "risk_level": stock_plan.risk_level,
            "rationale": stock_plan.rationale,
            "created_at": created_at,
        }
        with self._connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO ops_stock_plans (
                    record_id, sku_count, per_sku_stock, total_recommended_stock,
                    risk_level, rationale, created_at
                ) VALUES (
                    :record_id, :sku_count, :per_sku_stock, :total_recommended_stock,
                    :risk_level, :rationale, :created_at
                )
                """,
                row,
            )
            row["id"] = int(cursor.lastrowid)
        return row

    def save_browser_metric_audit(self, metrics: Iterable[Mapping[str, Any]]) -> List[Dict[str, Any]]:
        created_at = datetime.now().isoformat(timespec="seconds")
        saved: List[Dict[str, Any]] = []
        with self._connection() as conn:
            for metric in metrics:
                row = {
                    "metric_name": str(metric.get("metric_name") or metric.get("name") or ""),
                    "metric_value": str(metric.get("metric_value") or metric.get("value") or ""),
                    "source": str(metric.get("source") or "browser"),
                    "page_url": str(metric.get("page_url") or metric.get("url") or ""),
                    "status": str(metric.get("status") or "observed"),
                    "created_at": created_at,
                }
                cursor = conn.execute(
                    """
                    INSERT INTO ops_browser_metric_audit (
                        metric_name, metric_value, source, page_url, status, created_at
                    ) VALUES (
                        :metric_name, :metric_value, :source, :page_url, :status, :created_at
                    )
                    """,
                    row,
                )
                row["id"] = int(cursor.lastrowid)
                saved.append(row)
        return saved

    def save_strategy_snapshot(self, signals: Mapping[str, Any]) -> Dict[str, Any]:
        created_at = datetime.now().isoformat(timespec="seconds")
        opportunity_keywords = _string_list(signals.get("opportunity_keywords"))
        refund_reasons = signals.get("refund_reasons") if isinstance(signals.get("refund_reasons"), Mapping) else {}
        product_issues = _normalize_product_issues(signals.get("product_issues"))
        raw_payload = signals.get("raw_payload")
        if raw_payload is None:
            raw_payload_json = ""
        elif isinstance(raw_payload, str):
            raw_payload_json = raw_payload
        else:
            raw_payload_json = json.dumps(raw_payload, ensure_ascii=False, sort_keys=True)

        snapshot = {
            "snapshot_date": str(signals.get("snapshot_date") or date.today().isoformat()),
            "product_count": _nonnegative_int(signals.get("product_count")),
            "excellent_product_count": _nonnegative_int(signals.get("excellent_product_count")),
            "missing_main_video_count": _nonnegative_int(signals.get("missing_main_video_count")),
            "missing_spec_image_count": _nonnegative_int(signals.get("missing_spec_image_count")),
            "missing_live_replay_count": _nonnegative_int(signals.get("missing_live_replay_count")),
            "attribute_optimization_count": _nonnegative_int(signals.get("attribute_optimization_count")),
            "risk_product_count": _nonnegative_int(signals.get("risk_product_count")),
            "opportunity_keywords_json": json.dumps(opportunity_keywords, ensure_ascii=False),
            "refund_reasons_json": json.dumps(dict(refund_reasons), ensure_ascii=False, sort_keys=True),
            "source": str(signals.get("source") or "browser"),
            "status": str(signals.get("status") or "strategy_signals_observed"),
            "raw_payload_json": raw_payload_json,
            "created_at": created_at,
        }
        product_issue_actions: List[Dict[str, Any]] = []
        with self._connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO ops_strategy_snapshots (
                    snapshot_date, product_count, excellent_product_count,
                    missing_main_video_count, missing_spec_image_count,
                    missing_live_replay_count, attribute_optimization_count,
                    risk_product_count, opportunity_keywords_json,
                    refund_reasons_json, source, status, raw_payload_json, created_at
                ) VALUES (
                    :snapshot_date, :product_count, :excellent_product_count,
                    :missing_main_video_count, :missing_spec_image_count,
                    :missing_live_replay_count, :attribute_optimization_count,
                    :risk_product_count, :opportunity_keywords_json,
                    :refund_reasons_json, :source, :status, :raw_payload_json, :created_at
                )
                """,
                snapshot,
            )
            snapshot["id"] = int(cursor.lastrowid)

            for index, issue in enumerate(product_issues, start=1):
                row = {
                    "strategy_snapshot_id": snapshot["id"],
                    "product_id": issue["product_id"],
                    "title": issue["title"],
                    "quality_score": _nonnegative_int(issue.get("quality_score")),
                    "recent_30d_sales": _nonnegative_int(issue.get("recent_30d_sales")),
                    "issues_json": json.dumps(issue.get("issues") or [], ensure_ascii=False),
                    "priority_rank": index,
                    "action_status": "open",
                    "created_at": created_at,
                    "updated_at": created_at,
                }
                action_cursor = conn.execute(
                    """
                    INSERT INTO ops_product_issue_actions (
                        strategy_snapshot_id, product_id, title, quality_score,
                        recent_30d_sales, issues_json, priority_rank,
                        action_status, created_at, updated_at
                    ) VALUES (
                        :strategy_snapshot_id, :product_id, :title, :quality_score,
                        :recent_30d_sales, :issues_json, :priority_rank,
                        :action_status, :created_at, :updated_at
                    )
                    """,
                    row,
                )
                row["id"] = int(action_cursor.lastrowid)
                row["issues"] = list(issue.get("issues") or [])
                product_issue_actions.append(row)

        snapshot["opportunity_keywords"] = opportunity_keywords
        snapshot["refund_reasons"] = dict(refund_reasons)
        return {
            "snapshot": snapshot,
            "product_issue_actions": product_issue_actions,
        }

    def list_strategy_snapshots(self, limit: int = 20) -> List[Dict[str, Any]]:
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM ops_strategy_snapshots
                ORDER BY id DESC
                LIMIT ?
                """,
                (max(int(limit or 20), 1),),
            ).fetchall()
        result = [dict(row) for row in rows]
        for row in result:
            row["opportunity_keywords"] = _json_list(row.get("opportunity_keywords_json"))
            row["refund_reasons"] = _json_dict(row.get("refund_reasons_json"))
        return result

    def list_product_issue_actions(self, limit: int = 20, action_status: Optional[str] = None) -> List[Dict[str, Any]]:
        status = str(action_status or "").strip()
        sql = """
            SELECT * FROM ops_product_issue_actions
            {where_clause}
            ORDER BY strategy_snapshot_id DESC, priority_rank ASC, id ASC
            LIMIT ?
        """
        params: List[Any] = []
        where_clause = ""
        if status:
            where_clause = "WHERE action_status = ?"
            params.append(status)
        params.append(max(int(limit or 20), 1))
        with self._connection() as conn:
            rows = conn.execute(sql.format(where_clause=where_clause), tuple(params)).fetchall()
        result = [dict(row) for row in rows]
        for row in result:
            row["issues"] = _json_list(row.get("issues_json"))
            row["evidence"] = _json_dict(row.get("evidence_json"))
        return result

    def update_product_issue_action(
        self,
        action_id: int,
        action_status: str,
        note: str = "",
        evidence: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Any]:
        allowed_statuses = {"open", "in_progress", "done", "blocked", "skipped"}
        resolved_status = str(action_status or "").strip()
        if resolved_status not in allowed_statuses:
            raise ValueError(f"invalid action_status: {action_status}")
        now = datetime.now().isoformat(timespec="seconds")
        evidence_json = json.dumps(dict(evidence or {}), ensure_ascii=False, sort_keys=True)
        resolved_at = now if resolved_status in {"done", "skipped"} else None
        with self._connection() as conn:
            current = conn.execute(
                "SELECT * FROM ops_product_issue_actions WHERE id = ?",
                (int(action_id),),
            ).fetchone()
            if current is None:
                raise ValueError(f"product issue action not found: {action_id}")
            old_status = str(current["action_status"] or "")
            conn.execute(
                """
                UPDATE ops_product_issue_actions
                SET action_status = ?,
                    action_note = ?,
                    evidence_json = ?,
                    resolved_at = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (resolved_status, str(note or ""), evidence_json, resolved_at, now, int(action_id)),
            )
            conn.execute(
                """
                INSERT INTO ops_product_issue_action_events (
                    action_id, old_status, new_status, note, evidence_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (int(action_id), old_status, resolved_status, str(note or ""), evidence_json, now),
            )
            updated = conn.execute(
                "SELECT * FROM ops_product_issue_actions WHERE id = ?",
                (int(action_id),),
            ).fetchone()
        row = dict(updated)
        row["issues"] = _json_list(row.get("issues_json"))
        row["evidence"] = _json_dict(row.get("evidence_json"))
        return row

    def list_product_issue_action_events(
        self,
        action_id: Optional[int] = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        params: List[Any] = []
        where_clause = ""
        if action_id is not None:
            where_clause = "WHERE action_id = ?"
            params.append(int(action_id))
        params.append(max(int(limit or 20), 1))
        with self._connection() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM ops_product_issue_action_events
                {where_clause}
                ORDER BY id DESC
                LIMIT ?
                """,
                tuple(params),
            ).fetchall()
        result = [dict(row) for row in rows]
        for row in result:
            row["evidence"] = _json_dict(row.get("evidence_json"))
        return result

    def save_product_record_mappings(self, mappings: Iterable[Mapping[str, Any]]) -> List[Dict[str, Any]]:
        created_at = datetime.now().isoformat(timespec="seconds")
        saved: List[Dict[str, Any]] = []
        with self._connection() as conn:
            for mapping in mappings:
                evidence = mapping.get("evidence") if isinstance(mapping.get("evidence"), Mapping) else {}
                row = {
                    "action_id": None if mapping.get("action_id") in (None, "") else int(mapping.get("action_id")),
                    "product_id": str(mapping.get("product_id") or ""),
                    "title": str(mapping.get("title") or ""),
                    "record_id": None if mapping.get("record_id") in (None, "") else int(mapping.get("record_id")),
                    "record_title": str(mapping.get("record_title") or ""),
                    "record_path": str(mapping.get("record_path") or ""),
                    "confidence": float(mapping.get("confidence") or 0),
                    "match_status": str(mapping.get("match_status") or "unmatched"),
                    "reason": str(mapping.get("reason") or ""),
                    "evidence_json": json.dumps(dict(evidence), ensure_ascii=False, sort_keys=True),
                    "created_at": created_at,
                }
                cursor = conn.execute(
                    """
                    INSERT INTO ops_product_record_mappings (
                        action_id, product_id, title, record_id, record_title,
                        record_path, confidence, match_status, reason,
                        evidence_json, created_at
                    ) VALUES (
                        :action_id, :product_id, :title, :record_id, :record_title,
                        :record_path, :confidence, :match_status, :reason,
                        :evidence_json, :created_at
                    )
                    """,
                    row,
                )
                row["id"] = int(cursor.lastrowid)
                row["evidence"] = dict(evidence)
                saved.append(row)
        return saved

    def list_product_record_mappings(
        self,
        limit: int = 20,
        match_status: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        status = str(match_status or "").strip()
        where_clause = ""
        params: List[Any] = []
        if status:
            where_clause = "WHERE match_status = ?"
            params.append(status)
        params.append(max(int(limit or 20), 1))
        with self._connection() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM ops_product_record_mappings
                {where_clause}
                ORDER BY id DESC
                LIMIT ?
                """,
                tuple(params),
            ).fetchall()
        result = [dict(row) for row in rows]
        for row in result:
            row["evidence"] = _json_dict(row.get("evidence_json"))
        return result


@lru_cache(maxsize=None)
def _cached_ops_ledger(db_path: str) -> OpsLedger:
    return OpsLedger(db_path)


def get_ops_ledger() -> OpsLedger:
    """取运营账本（按 db 路径缓存实例）。

    原来这里是裸的 `return OpsLedger()`：每次调用都重跑一遍
    `initialize_schema()`（ops_engine.py:4690-4834，8 条 CREATE TABLE IF NOT EXISTS
    + 2 次 PRAGMA table_info 迁移检查 + 一次连接开关）。而 app.py 里有 37 个调用点，
    其中若干路由（如 1415/1426、1455/1471、1649/1655）一次请求里连着调两次
    —— 等于每个 /api/ops/* 请求白跑两遍建表。

    OpsLedger 本身不持有连接（`_connection()` 每次开关），所以复用实例是安全的；
    缓存键是账本绝对路径，测试传自定义路径时不会串味。
    """
    return _cached_ops_ledger(str(resolve_ops_ledger_path()))

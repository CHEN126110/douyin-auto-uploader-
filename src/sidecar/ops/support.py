# -*- coding: utf-8 -*-
"""运营接口共用的请求解析与本地数据读取。

不依赖浏览器，也不依赖 Flask 应用实例；需要数据库模型的函数由调用方显式传入 ``record_model``。
"""
import json

from flask import request

from src.config import settings_manager
from src.ops_engine import (
    ProductCandidateInput,
    build_product_candidate_list,
    extract_sku_goods_costs,
    get_ops_ledger,
)


def ops_request_data():
    return request.get_json(silent=True) or {}


def ops_float(data, key, default=0):
    try:
        value = data.get(key, default) if isinstance(data, dict) else default
        if value in ('', None):
            return float(default)
        return float(value)
    except Exception:
        return float(default)


def ops_int(data, key, default=0):
    try:
        value = data.get(key, default) if isinstance(data, dict) else default
        if value in ('', None):
            return int(default)
        return int(float(value))
    except Exception:
        return int(default)


def ops_pricing_defaults():
    defaults = {
        'shipping_cost': 0.0,
        'packaging_cost': 0.0,
        'platform_commission_rate': 0.0,
    }
    try:
        settings = settings_manager.get_settings()
        for item in (settings.cost_items or []):
            if not isinstance(item, dict):
                continue
            name = str(item.get('name') or '')
            cost_type = str(item.get('cost_type') or '')
            try:
                value = float(item.get('value') or 0)
            except Exception:
                value = 0.0
            if cost_type == 'fixed' and '运费' in name:
                defaults['shipping_cost'] = value
            elif cost_type == 'fixed' and '包装' in name:
                defaults['packaging_cost'] = value
            elif cost_type == 'percentage' and ('佣金' in name or '平台' in name):
                defaults['platform_commission_rate'] = value / 100 if value > 1 else value
    except Exception:
        pass
    return defaults


def ops_record_context(record_model, record_id):
    if not record_id:
        return None, [], None
    try:
        record = record_model.get_by_id(record_id)
    except Exception:
        return None, [], None
    try:
        sku_list = json.loads(record.content or '[]')
        if not isinstance(sku_list, list):
            sku_list = []
    except Exception:
        sku_list = []
    return record, sku_list, {
        'record_id': record.id,
        'name': record.name,
        'title': record.title,
        'status': record.status,
        'repo': record.repo,
        'clazz': record.clazz,
        'sku_count': len(sku_list),
        'source_url': record.source_url,
    }


def ops_first_sku_price(sku_list):
    for sku in sku_list:
        if not isinstance(sku, dict):
            continue
        try:
            price = float(sku.get('price') or 0)
        except Exception:
            price = 0
        if price > 0:
            return price
    return 0.0


def ops_sku_prices(sku_list):
    return extract_sku_goods_costs(sku_list or [])


def ops_current_sku_prices(sku_list):
    prices = []
    for sku in sku_list or []:
        if not isinstance(sku, dict):
            continue
        price = ops_float(sku, 'price', 0)
        if price > 0:
            prices.append(price)
    return prices


def ops_build_local_product_candidates(record_model, data):
    limit = max(min(ops_int(data, 'limit', 20), 100), 1)
    defaults = ops_pricing_defaults()
    shipping_cost = ops_float(data, 'shipping_cost', defaults['shipping_cost'])
    packaging_cost = ops_float(data, 'packaging_cost', defaults['packaging_cost'])
    platform_commission_rate = ops_float(data, 'platform_commission_rate', defaults['platform_commission_rate'])
    target_net_margin = ops_float(data, 'target_net_margin', ops_float(data, 'targetNetMargin', 0.30))
    expected_daily_orders = ops_int(data, 'expected_daily_orders', ops_int(data, 'expectedDailyOrders', 0))
    promotion_cost = ops_float(data, 'promotion_cost', ops_float(data, 'promotionCost', 0))
    records = (
        record_model.select()
        .order_by(record_model.id.desc())
        .limit(limit)
    )
    candidate_inputs = []
    record_contexts = []
    for record in records:
        try:
            sku_list = json.loads(record.content or '[]')
            if not isinstance(sku_list, list):
                sku_list = []
        except Exception:
            sku_list = []
        record_contexts.append({
            'record_id': record.id,
            'name': record.name,
            'title': record.title,
            'status': record.status,
            'repo': record.repo,
            'clazz': record.clazz,
            'sku_count': len(sku_list),
            'source_url': record.source_url,
        })
        candidate_inputs.append(ProductCandidateInput(
            record_id=record.id,
            title=str(record.title or record.name or ''),
            sku_prices=ops_sku_prices(sku_list),
            current_sku_prices=ops_current_sku_prices(sku_list),
            shipping_cost=shipping_cost,
            packaging_cost=packaging_cost,
            platform_commission_rate=platform_commission_rate,
            promotion_cost=promotion_cost,
            target_net_margin=target_net_margin,
            expected_daily_orders=expected_daily_orders,
        ))
    return {
        'candidates': build_product_candidate_list(candidate_inputs),
        'records': record_contexts,
        'cost_defaults': {
            'shipping_cost': shipping_cost,
            'packaging_cost': packaging_cost,
            'platform_commission_rate': platform_commission_rate,
            'promotion_cost': promotion_cost,
            'target_net_margin': target_net_margin,
        },
    }


def ops_local_record_mapping_rows(record_model):
    rows = []
    for record in record_model.select().order_by(record_model.id.asc()):
        rows.append({
            'record_id': int(record.id),
            'title': record.title or '',
            'name': record.name or '',
            'path': record.path or '',
            'source_url': getattr(record, 'source_url', '') or '',
        })
    return rows


def ops_find_product_issue_action(action_id):
    if not action_id:
        return None
    try:
        for item in get_ops_ledger().list_product_issue_actions(limit=200):
            if int(item.get('id') or 0) == int(action_id):
                return item
    except Exception:
        return None
    return None


def ops_product_from_action(data):
    """解析请求里的 product；缺失时按 action_id 回查运营账本补齐。为空返回 None。"""
    product = data.get('product') if isinstance(data.get('product'), dict) else {}
    action_id = ops_int(data, 'action_id', ops_int(data, 'actionId', 0))
    if not product and action_id:
        actions = get_ops_ledger().list_product_issue_actions(limit=500)
        for action in actions:
            if int(action.get('id') or 0) == action_id:
                product = {
                    'action_id': action.get('id'),
                    'product_id': action.get('product_id'),
                    'title': action.get('title'),
                    'recent_30d_sales': action.get('recent_30d_sales'),
                }
                break
    if not product:
        return None
    return product

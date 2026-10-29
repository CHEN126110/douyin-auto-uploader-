# -*- coding: utf-8 -*-
"""运营闭环：采购、供应商与无品牌整改类接口（/api/ops/*）。"""
import traceback

from flask import request

from src.ops_engine import (
    AI_POLICY,
    DAILY_NET_PROFIT_TARGET,
    build_material_gap_plan,
    build_no_brand_remediation_plan,
    build_no_brand_title_audit,
    build_sourcing_profit_gate,
    build_supplier_quote_intake,
    build_supplier_quote_plan,
    get_ops_ledger,
)
from ..responses import api_error, api_ok
from .support import (
    ops_float,
    ops_int,
    ops_product_from_action,
    ops_request_data,
)


def register_ops_sourcing_routes(routes):
    """注册采购、供应商与无品牌整改类接口。"""

    @routes.get('/api/ops/no-brand-title-audit')
    def ops_no_brand_title_audit():
        try:
            limit = ops_int(request.args, 'limit', 200)
            action_status = str(request.args.get('action_status') or request.args.get('actionStatus') or '').strip()
            actions = get_ops_ledger().list_product_issue_actions(
                limit=max(min(limit, 500), 1),
                action_status=action_status or None,
            )
            return api_ok('无品牌标题审计完成', data={
                'audit': build_no_brand_title_audit(actions),
                'source_action_count': len(actions),
                'ai_policy': dict(AI_POLICY),
            })
        except Exception as exc:
            traceback.print_exc()
            return api_error(f'无品牌标题审计失败: {str(exc)}')

    @routes.post('/api/ops/no-brand-remediation-plan')
    def ops_no_brand_remediation_plan():
        try:
            data = ops_request_data()
            limit = max(min(ops_int(data, 'limit', 200), 500), 1)
            action_status = str(data.get('action_status') or data.get('actionStatus') or '').strip()
            actions = data.get('product_issue_actions') if isinstance(data.get('product_issue_actions'), list) else None
            if actions is None:
                actions = get_ops_ledger().list_product_issue_actions(
                    limit=limit,
                    action_status=action_status or None,
                )
            plan = build_no_brand_remediation_plan(actions)
            return api_ok('无品牌整改计划已生成', data={
                'no_brand_remediation_plan': plan,
                'source_action_count': len(actions),
                'actions_source': 'request' if isinstance(data.get('product_issue_actions'), list) else 'ledger',
                'ai_policy': dict(AI_POLICY),
            })
        except Exception as exc:
            traceback.print_exc()
            return api_error(f'无品牌整改计划生成失败: {str(exc)}')

    @routes.post('/api/ops/material-gap-plan')
    def ops_material_gap_plan():
        try:
            data = ops_request_data()
            limit = max(min(ops_int(data, 'limit', 100), 500), 1)
            action_status = str(data.get('action_status') or data.get('actionStatus') or '').strip()
            ledger = get_ops_ledger()

            actions = data.get('product_issue_actions') if isinstance(data.get('product_issue_actions'), list) else None
            if actions is None:
                actions = ledger.list_product_issue_actions(
                    limit=limit,
                    action_status=action_status or None,
                )

            mappings = data.get('product_record_mappings') if isinstance(data.get('product_record_mappings'), list) else None
            if mappings is None:
                mappings = ledger.list_product_record_mappings(limit=limit)

            no_brand_audit = data.get('no_brand_audit') or data.get('noBrandAudit')
            if not isinstance(no_brand_audit, dict):
                no_brand_audit = None

            plan = build_material_gap_plan(actions, mappings, no_brand_audit=no_brand_audit)
            return api_ok('素材缺口采集计划已生成', data={
                'material_gap_plan': plan,
                'source_action_count': len(actions),
                'source_mapping_count': len(mappings),
                'actions_source': 'request' if isinstance(data.get('product_issue_actions'), list) else 'ledger',
                'mappings_source': 'request' if isinstance(data.get('product_record_mappings'), list) else 'ledger',
                'ai_policy': dict(AI_POLICY),
            })
        except Exception as exc:
            traceback.print_exc()
            return api_error(f'素材缺口采集计划生成失败: {str(exc)}')

    @routes.post('/api/ops/sourcing-profit-gate')
    def ops_sourcing_profit_gate():
        try:
            data = ops_request_data()
            product = ops_product_from_action(data)
            if not product:
                return api_error('product 或 action_id 不能为空')

            scenarios = data.get('scenarios') if isinstance(data.get('scenarios'), list) else []
            gate = build_sourcing_profit_gate(
                product=product,
                scenarios=scenarios,
                target_net_profit=ops_float(data, 'target_net_profit', ops_float(data, 'targetNetProfit', DAILY_NET_PROFIT_TARGET)),
            )
            return api_ok('采购利润闸已生成', data={
                'sourcing_profit_gate': gate,
                'scenario_count': len(scenarios),
                'ai_policy': dict(AI_POLICY),
            })
        except Exception as exc:
            traceback.print_exc()
            return api_error(f'采购利润闸生成失败: {str(exc)}')

    @routes.post('/api/ops/supplier-quote-plan')
    def ops_supplier_quote_plan():
        try:
            data = ops_request_data()
            product = ops_product_from_action(data)
            if not product:
                return api_error('product 或 action_id 不能为空')

            sourcing_profit_gate = data.get('sourcing_profit_gate') or data.get('sourcingProfitGate')
            if not isinstance(sourcing_profit_gate, dict):
                scenarios = data.get('scenarios') if isinstance(data.get('scenarios'), list) else []
                sourcing_profit_gate = build_sourcing_profit_gate(product=product, scenarios=scenarios)
            supplier_candidates = data.get('supplier_candidates') or data.get('supplierCandidates')
            if not isinstance(supplier_candidates, list):
                supplier_candidates = []

            plan = build_supplier_quote_plan(product, sourcing_profit_gate, supplier_candidates)
            return api_ok('供应商询价计划已生成', data={
                'supplier_quote_plan': plan,
                'candidate_count': len(supplier_candidates),
                'ai_policy': dict(AI_POLICY),
            })
        except Exception as exc:
            traceback.print_exc()
            return api_error(f'供应商询价计划生成失败: {str(exc)}')

    @routes.post('/api/ops/supplier-quote-intake')
    def ops_supplier_quote_intake():
        try:
            data = ops_request_data()
            product = ops_product_from_action(data)
            if not product:
                return api_error('product 或 action_id 不能为空')

            supplier_quote = data.get('supplier_quote') or data.get('supplierQuote')
            if not isinstance(supplier_quote, dict):
                return api_error('supplier_quote 不能为空')

            sourcing_profit_gate = data.get('sourcing_profit_gate') or data.get('sourcingProfitGate')
            if not isinstance(sourcing_profit_gate, dict):
                scenarios = data.get('scenarios') if isinstance(data.get('scenarios'), list) else []
                sourcing_profit_gate = build_sourcing_profit_gate(product=product, scenarios=scenarios)

            intake = build_supplier_quote_intake(
                product=product,
                sourcing_profit_gate=sourcing_profit_gate,
                supplier_quote=supplier_quote,
                target_net_profit=ops_float(data, 'target_net_profit', ops_float(data, 'targetNetProfit', DAILY_NET_PROFIT_TARGET)),
            )
            return api_ok('供应商报价回传判定已生成', data={
                'supplier_quote_intake': intake,
                'ai_policy': dict(AI_POLICY),
            })
        except Exception as exc:
            traceback.print_exc()
            return api_error(f'供应商报价回传判定失败: {str(exc)}')

# -*- coding: utf-8 -*-
"""运营闭环：经营测算与计划类接口（/api/ops/*）。

路由只做请求解析与返回，计算规则都在 ``src.ops_engine``。"""
import json
import traceback
from dataclasses import asdict
from datetime import datetime

from src.ops_engine import (
    AI_POLICY,
    DAILY_NET_PROFIT_TARGET,
    ProductEvaluationInput,
    StockPlanInput,
    apply_candidate_pricing_to_skus,
    build_conversion_asset_pack,
    build_conversion_experiment_plan,
    build_daily_plan,
    build_daily_review,
    build_detail_conversion_audit,
    build_detail_improvement_suggestions,
    build_first_order_decision_matrix,
    build_material_gap_plan,
    build_net_profit_verification_matrix,
    build_ops_execution_queue,
    build_portfolio_path_to_500,
    build_post_save_conversion_monitor,
    build_profit_ladder_to_500,
    build_profit_ramp_plan,
    build_search_conversion_work_package,
    build_stock_plan,
    evaluate_product,
    get_ops_ledger,
)
from ..responses import api_error, api_ok
from .support import (
    ops_build_local_product_candidates,
    ops_first_sku_price,
    ops_float,
    ops_int,
    ops_pricing_defaults,
    ops_record_context,
    ops_request_data,
)


def register_ops_planning_routes(routes, *, record_model):
    """注册经营测算与计划类接口。"""

    @routes.get('/api/ops/ai-policy')
    def ops_ai_policy():
        return api_ok('外部 AI 已禁用', data={
            'ai_policy': dict(AI_POLICY),
            'model_configs': [],
        })

    @routes.post('/api/ops/evaluate-product')
    def ops_evaluate_product():
        try:
            data = ops_request_data()
            record_id = ops_int(data, 'record_id', ops_int(data, 'recordId', 0))
            record, sku_list, record_context = ops_record_context(record_model, record_id)
            defaults = ops_pricing_defaults()
            title = str(data.get('title') or (record.title if record else '') or (record.name if record else '') or '')
            sale_price = ops_float(data, 'sale_price', ops_float(data, 'salePrice', ops_first_sku_price(sku_list)))
            goods_cost = ops_float(data, 'goods_cost', ops_float(data, 'goodsCost', 0))
            evaluation = evaluate_product(ProductEvaluationInput(
                record_id=record_id,
                title=title,
                sale_price=sale_price,
                goods_cost=goods_cost,
                shipping_cost=ops_float(data, 'shipping_cost', defaults['shipping_cost']),
                packaging_cost=ops_float(data, 'packaging_cost', defaults['packaging_cost']),
                platform_commission_rate=ops_float(data, 'platform_commission_rate', defaults['platform_commission_rate']),
                promotion_cost=ops_float(data, 'promotion_cost', 0),
                refund_loss=ops_float(data, 'refund_loss', 0),
                after_sale_loss=ops_float(data, 'after_sale_loss', 0),
                expected_daily_orders=ops_int(data, 'expected_daily_orders', 0),
            ))
            saved = get_ops_ledger().save_product_evaluation(evaluation)
            return api_ok('单品经营净利评估完成', data={
                'evaluation': asdict(evaluation),
                'saved_snapshot': saved,
                'record': record_context,
                'ai_policy': dict(AI_POLICY),
            })
        except Exception as exc:
            traceback.print_exc()
            return api_error(f'单品评估失败: {str(exc)}')

    @routes.post('/api/ops/stock-plan')
    def ops_stock_plan():
        try:
            data = ops_request_data()
            record_id = ops_int(data, 'record_id', ops_int(data, 'recordId', 0))
            _record, sku_list, record_context = ops_record_context(record_model, record_id)
            sku_count = ops_int(data, 'sku_count', len(sku_list) or 1)
            stock_plan = build_stock_plan(StockPlanInput(
                record_id=record_id,
                sku_count=sku_count,
                expected_daily_orders=ops_int(data, 'expected_daily_orders', 0),
                replenishment_days=ops_int(data, 'replenishment_days', 1),
                can_restock_same_day=bool(data.get('can_restock_same_day', True)),
                max_per_sku_without_sales_signal=ops_int(data, 'max_per_sku_without_sales_signal', 2),
            ))
            saved = get_ops_ledger().save_stock_plan(stock_plan)
            return api_ok('备货建议已生成', data={
                'stock_plan': asdict(stock_plan),
                'saved_snapshot': saved,
                'record': record_context,
                'ai_policy': dict(AI_POLICY),
            })
        except Exception as exc:
            traceback.print_exc()
            return api_error(f'备货建议生成失败: {str(exc)}')

    @routes.post('/api/ops/product-candidates')
    def ops_product_candidates():
        try:
            data = ops_request_data()
            candidate_data = ops_build_local_product_candidates(record_model, data)
            return api_ok('本地商品候选评估完成', data={
                'candidates': candidate_data['candidates'],
                'records': candidate_data['records'],
                'cost_defaults': candidate_data['cost_defaults'],
                'target_net_profit': DAILY_NET_PROFIT_TARGET,
                'ai_policy': dict(AI_POLICY),
            })
        except Exception as exc:
            traceback.print_exc()
            return api_error(f'本地商品候选评估失败: {str(exc)}')

    @routes.post('/api/ops/apply-candidate-pricing')
    def ops_apply_candidate_pricing():
        try:
            data = ops_request_data()
            record_id = ops_int(data, 'record_id', ops_int(data, 'recordId', 0))
            dry_run = bool(data.get('dry_run', data.get('dryRun', True)))
            if not record_id:
                return api_error('record_id 不能为空')
            record, sku_list, record_context = ops_record_context(record_model, record_id)
            if not record:
                return api_error(f'商品不存在: {record_id}')

            candidate_data = ops_build_local_product_candidates(record_model, {
                **data,
                'limit': max(ops_int(data, 'limit', 20), 20),
            })
            candidate = None
            for item in candidate_data['candidates']:
                if int(item.get('record_id') or 0) == record_id:
                    candidate = item
                    break
            if not candidate:
                return api_error(f'未生成商品候选: {record_id}')

            sale_price = ops_float(data, 'sale_price', ops_float(data, 'salePrice', candidate.get('recommended_sale_price', 0)))
            pricing_result = apply_candidate_pricing_to_skus(sku_list, sale_price)
            saved = False
            if not dry_run:
                record.content = json.dumps(pricing_result['skus'], ensure_ascii=False)
                record.update_time = datetime.now()
                record.save()
                saved = True

            refreshed_record, refreshed_skus, refreshed_context = ops_record_context(record_model, record_id)
            return api_ok('候选商品售价应用完成' if saved else '候选商品售价 dry-run 完成', data={
                'dry_run': dry_run,
                'saved': saved,
                'record': refreshed_context or record_context,
                'candidate': candidate,
                'pricing': {
                    'sale_price': pricing_result['sale_price'],
                    'updated_count': pricing_result['updated_count'],
                    'changes': pricing_result['changes'],
                },
                'current_sku_prices': [
                    {
                        'name': sku.get('name'),
                        'price': sku.get('price'),
                        'ops_goods_cost': sku.get('ops_goods_cost'),
                    }
                    for sku in (refreshed_skus if saved else pricing_result['skus'])
                    if isinstance(sku, dict)
                ],
                'ai_policy': dict(AI_POLICY),
            })
        except Exception as exc:
            traceback.print_exc()
            return api_error(f'候选商品售价应用失败: {str(exc)}')

    @routes.post('/api/ops/daily-plan')
    def ops_daily_plan():
        try:
            data = ops_request_data()
            metrics = data.get('metrics') if isinstance(data.get('metrics'), dict) else data
            if not metrics:
                latest = get_ops_ledger().list_daily_snapshots(limit=1)
                metrics = latest[0] if latest else {}
            diagnostic_signals = data.get('diagnostic_signals') or data.get('diagnosticSignals')
            if isinstance(diagnostic_signals, dict):
                metrics = {
                    **(metrics or {}),
                    'diagnostic_signals': diagnostic_signals,
                }
            plan = build_daily_plan(metrics)
            return api_ok('每日运营计划已生成', data={
                'daily_plan': plan,
                'source': 'request' if data else 'latest_snapshot',
            })
        except Exception as exc:
            traceback.print_exc()
            return api_error(f'每日运营计划生成失败: {str(exc)}')

    @routes.post('/api/ops/search-conversion-work-package')
    def ops_search_conversion_work_package():
        try:
            data = ops_request_data()
            ledger = get_ops_ledger()
            metrics = data.get('metrics') if isinstance(data.get('metrics'), dict) else None
            if metrics is None:
                latest = ledger.list_daily_snapshots(limit=1)
                metrics = latest[0] if latest else {}

            actions = data.get('product_issue_actions') or data.get('productIssueActions')
            if not isinstance(actions, list):
                actions = ledger.list_product_issue_actions(limit=max(min(ops_int(data, 'limit', 100), 500), 1))

            package = build_search_conversion_work_package(
                metrics=metrics,
                product_issue_actions=actions,
                target_net_profit=ops_float(data, 'target_net_profit', ops_float(data, 'targetNetProfit', DAILY_NET_PROFIT_TARGET)),
                action_id=ops_int(data, 'action_id', ops_int(data, 'actionId', 0)) or None,
            )
            return api_ok('搜索承接工作包已生成', data={
                'search_conversion_work_package': package,
                'metrics_source': 'request' if isinstance(data.get('metrics'), dict) else 'latest_snapshot',
                'actions_source': 'request' if isinstance(data.get('product_issue_actions') or data.get('productIssueActions'), list) else 'ledger',
                'ai_policy': dict(AI_POLICY),
            })
        except Exception as exc:
            traceback.print_exc()
            return api_error(f'搜索承接工作包生成失败: {str(exc)}')

    @routes.post('/api/ops/daily-review')
    def ops_daily_review():
        try:
            data = ops_request_data()
            metrics = data.get('metrics') if isinstance(data.get('metrics'), dict) else {}
            if not metrics:
                latest = get_ops_ledger().list_daily_snapshots(limit=1)
                metrics = latest[0] if latest else {}
            diagnostic_signals = data.get('diagnostic_signals') or data.get('diagnosticSignals')
            if isinstance(diagnostic_signals, dict):
                metrics = {
                    **(metrics or {}),
                    'diagnostic_signals': diagnostic_signals,
                }
            candidate_data = ops_build_local_product_candidates(record_model, data)
            review = build_daily_review(metrics, candidate_data['candidates'])
            return api_ok('每日经营复盘已生成', data={
                'review': review,
                'metrics_source': 'request' if isinstance(data.get('metrics'), dict) and data.get('metrics') else 'latest_snapshot',
                'candidates': candidate_data['candidates'],
                'records': candidate_data['records'],
                'cost_defaults': candidate_data['cost_defaults'],
            })
        except Exception as exc:
            traceback.print_exc()
            return api_error(f'每日经营复盘生成失败: {str(exc)}')

    @routes.post('/api/ops/detail-conversion-audit')
    def ops_detail_conversion_audit():
        try:
            data = ops_request_data()
            metrics = data.get('metrics') if isinstance(data.get('metrics'), dict) else {}
            if not metrics:
                latest = get_ops_ledger().list_daily_snapshots(limit=1)
                metrics = latest[0] if latest else {}
            page_snapshot = data.get('page_snapshot') or data.get('pageSnapshot')
            if not isinstance(page_snapshot, dict):
                return api_error('page_snapshot 不能为空')
            audit = build_detail_conversion_audit(metrics, page_snapshot)
            product_title = str(data.get('product_title') or data.get('productTitle') or page_snapshot.get('product_title') or page_snapshot.get('productTitle') or '')
            suggestions = build_detail_improvement_suggestions(product_title, audit) if product_title else None
            return api_ok('详情承接审计完成', data={
                'audit': audit,
                'suggestions': suggestions,
                'metrics_source': 'request' if isinstance(data.get('metrics'), dict) and data.get('metrics') else 'latest_snapshot',
                'ai_policy': dict(AI_POLICY),
            })
        except Exception as exc:
            traceback.print_exc()
            return api_error(f'详情承接审计失败: {str(exc)}')

    @routes.post('/api/ops/conversion-asset-pack')
    def ops_conversion_asset_pack():
        try:
            data = ops_request_data()
            metrics = data.get('metrics') if isinstance(data.get('metrics'), dict) else {}
            if not metrics:
                latest = get_ops_ledger().list_daily_snapshots(limit=1)
                metrics = latest[0] if latest else {}

            product = data.get('product') if isinstance(data.get('product'), dict) else {}
            detail_audit = data.get('detail_audit') or data.get('detailAudit')
            page_snapshot = data.get('page_snapshot') or data.get('pageSnapshot')
            if not isinstance(detail_audit, dict) and isinstance(page_snapshot, dict):
                detail_audit = build_detail_conversion_audit(metrics, page_snapshot)
            if not isinstance(detail_audit, dict):
                detail_audit = {}

            suggestions = data.get('suggestions') if isinstance(data.get('suggestions'), dict) else None
            if suggestions is None:
                title = str(product.get('title') or product.get('product_title') or product.get('productTitle') or '')
                suggestions = build_detail_improvement_suggestions(title, detail_audit) if title else None

            pack = build_conversion_asset_pack(
                product=product,
                audit=detail_audit,
                suggestions=suggestions,
                metrics=metrics,
                target_net_profit=ops_float(data, 'target_net_profit', ops_float(data, 'targetNetProfit', DAILY_NET_PROFIT_TARGET)),
            )
            return api_ok('无品牌转化素材包已生成', data={
                'conversion_asset_pack': pack,
                'metrics_source': 'request' if isinstance(data.get('metrics'), dict) and data.get('metrics') else 'latest_snapshot',
                'detail_audit_source': 'request' if isinstance(data.get('detail_audit') or data.get('detailAudit'), dict) else ('page_snapshot' if isinstance(page_snapshot, dict) else 'empty'),
                'safe_to_auto_upload': False,
                'ai_policy': dict(AI_POLICY),
            })
        except Exception as exc:
            traceback.print_exc()
            return api_error(f'无品牌转化素材包生成失败: {str(exc)}')

    @routes.post('/api/ops/conversion-experiment-plan')
    def ops_conversion_experiment_plan():
        try:
            data = ops_request_data()
            metrics = data.get('metrics') if isinstance(data.get('metrics'), dict) else {}
            if not metrics:
                latest = get_ops_ledger().list_daily_snapshots(limit=1)
                metrics = latest[0] if latest else {}

            detail_audit = data.get('detail_audit') or data.get('detailAudit')
            page_snapshot = data.get('page_snapshot') or data.get('pageSnapshot')
            if not isinstance(detail_audit, dict) and isinstance(page_snapshot, dict):
                detail_audit = build_detail_conversion_audit(metrics, page_snapshot)
            if not isinstance(detail_audit, dict):
                detail_audit = {}

            profit_plan = data.get('profit_plan') or data.get('profitPlan')
            if not isinstance(profit_plan, dict):
                candidate_data = ops_build_local_product_candidates(record_model, data)
                profit_plan = build_profit_ramp_plan(metrics, candidate_data['candidates'])

            plan = build_conversion_experiment_plan(metrics, detail_audit, profit_plan)
            return api_ok('转化实验计划已生成', data={
                'conversion_experiment_plan': plan,
                'metrics_source': 'request' if isinstance(data.get('metrics'), dict) and data.get('metrics') else 'latest_snapshot',
                'detail_audit_source': 'request' if isinstance(data.get('detail_audit') or data.get('detailAudit'), dict) else ('page_snapshot' if isinstance(page_snapshot, dict) else 'empty'),
                'profit_plan_source': 'request' if isinstance(data.get('profit_plan') or data.get('profitPlan'), dict) else 'local_candidates',
                'ai_policy': dict(AI_POLICY),
            })
        except Exception as exc:
            traceback.print_exc()
            return api_error(f'转化实验计划生成失败: {str(exc)}')

    @routes.post('/api/ops/profit-ramp-plan')
    def ops_profit_ramp_plan():
        try:
            data = ops_request_data()
            metrics = data.get('metrics') if isinstance(data.get('metrics'), dict) else {}
            if not metrics:
                latest = get_ops_ledger().list_daily_snapshots(limit=1)
                metrics = latest[0] if latest else {}
            candidate_data = ops_build_local_product_candidates(record_model, data)
            plan = build_profit_ramp_plan(metrics, candidate_data['candidates'])
            return api_ok('日净利目标拆解已生成', data={
                'profit_ramp_plan': plan,
                'metrics_source': 'request' if isinstance(data.get('metrics'), dict) and data.get('metrics') else 'latest_snapshot',
                'candidate_count': len(candidate_data['candidates']),
                'top_candidate': candidate_data['candidates'][0] if candidate_data['candidates'] else None,
                'ai_policy': dict(AI_POLICY),
            })
        except Exception as exc:
            traceback.print_exc()
            return api_error(f'日净利目标拆解生成失败: {str(exc)}')

    @routes.post('/api/ops/profit-ladder-to-500')
    def ops_profit_ladder_to_500():
        try:
            data = ops_request_data()
            metrics = data.get('metrics') if isinstance(data.get('metrics'), dict) else {}
            if not metrics:
                latest = get_ops_ledger().list_daily_snapshots(limit=1)
                metrics = latest[0] if latest else {}

            product = data.get('product') if isinstance(data.get('product'), dict) else {}
            cost_scenarios = data.get('cost_scenarios') or data.get('costScenarios')
            if not isinstance(cost_scenarios, list) or not cost_scenarios:
                cost_scenarios = [
                    {'scenario_id': 'floor_quote', 'label': '低成本报价', 'goods_cost': 1.5},
                    {'scenario_id': 'target_quote', 'label': '目标报价', 'goods_cost': 2.0},
                    {'scenario_id': 'mid_quote', 'label': '中位报价', 'goods_cost': 5.0},
                    {'scenario_id': 'high_quote', 'label': '高成本报价', 'goods_cost': 8.0},
                ]

            ladder = build_profit_ladder_to_500(
                metrics=metrics,
                product=product,
                cost_scenarios=cost_scenarios,
                target_net_profit=ops_float(data, 'target_net_profit', ops_float(data, 'targetNetProfit', DAILY_NET_PROFIT_TARGET)),
            )
            return api_ok('500元净利阶梯已生成', data={
                'profit_ladder_to_500': ladder,
                'metrics_source': 'request' if isinstance(data.get('metrics'), dict) and data.get('metrics') else 'latest_snapshot',
                'scenario_count': len(cost_scenarios),
                'ai_policy': dict(AI_POLICY),
            })
        except Exception as exc:
            traceback.print_exc()
            return api_error(f'500元净利阶梯生成失败: {str(exc)}')

    @routes.post('/api/ops/execution-queue')
    def ops_execution_queue():
        try:
            data = ops_request_data()
            limit = max(min(ops_int(data, 'limit', 100), 500), 1)
            action_status = str(data.get('action_status') or data.get('actionStatus') or '').strip()
            ledger = get_ops_ledger()

            metrics = data.get('metrics') if isinstance(data.get('metrics'), dict) else None
            if metrics is None:
                latest = ledger.list_daily_snapshots(limit=1)
                metrics = latest[0] if latest else {}

            actions = data.get('product_issue_actions') if isinstance(data.get('product_issue_actions'), list) else None
            if actions is None:
                actions = ledger.list_product_issue_actions(
                    limit=limit,
                    action_status=action_status or None,
                )

            material_gap_plan = data.get('material_gap_plan') or data.get('materialGapPlan')
            if not isinstance(material_gap_plan, dict):
                mappings = data.get('product_record_mappings') if isinstance(data.get('product_record_mappings'), list) else None
                if mappings is None:
                    mappings = ledger.list_product_record_mappings(limit=limit)
                no_brand_audit = data.get('no_brand_audit') or data.get('noBrandAudit')
                if not isinstance(no_brand_audit, dict):
                    no_brand_audit = None
                material_gap_plan = build_material_gap_plan(actions, mappings, no_brand_audit=no_brand_audit)

            supplier_quote_plan = (
                data.get('supplier_quote_plan')
                or data.get('supplierQuotePlan')
                or data.get('supplier_quote_plans')
                or data.get('supplierQuotePlans')
            )
            conversion_experiment_plan = data.get('conversion_experiment_plan') or data.get('conversionExperimentPlan')
            if not isinstance(conversion_experiment_plan, dict):
                conversion_experiment_plan = None

            queue = build_ops_execution_queue(
                metrics=metrics,
                product_issue_actions=actions,
                material_gap_plan=material_gap_plan,
                supplier_quote_plan=supplier_quote_plan,
                conversion_experiment_plan=conversion_experiment_plan,
                target_net_profit=ops_float(data, 'target_net_profit', ops_float(data, 'targetNetProfit', DAILY_NET_PROFIT_TARGET)),
            )
            return api_ok('运营执行队列已生成', data={
                'execution_queue': queue,
                'metrics_source': 'request' if isinstance(data.get('metrics'), dict) else 'latest_snapshot',
                'actions_source': 'request' if isinstance(data.get('product_issue_actions'), list) else 'ledger',
                'source_action_count': len(actions),
                'ai_policy': dict(AI_POLICY),
            })
        except Exception as exc:
            traceback.print_exc()
            return api_error(f'运营执行队列生成失败: {str(exc)}')

    @routes.post('/api/ops/portfolio-path-to-500')
    def ops_portfolio_path_to_500():
        try:
            data = ops_request_data()
            limit = max(min(ops_int(data, 'limit', 100), 500), 1)
            action_status = str(data.get('action_status') or data.get('actionStatus') or '').strip()
            ledger = get_ops_ledger()

            metrics = data.get('metrics') if isinstance(data.get('metrics'), dict) else None
            if metrics is None:
                latest = ledger.list_daily_snapshots(limit=1)
                metrics = latest[0] if latest else {}

            actions = data.get('product_issue_actions') or data.get('productIssueActions')
            if not isinstance(actions, list):
                actions = ledger.list_product_issue_actions(
                    limit=limit,
                    action_status=action_status or None,
                )

            plan = build_portfolio_path_to_500(
                metrics=metrics,
                product_issue_actions=actions,
                target_net_profit=ops_float(data, 'target_net_profit', ops_float(data, 'targetNetProfit', DAILY_NET_PROFIT_TARGET)),
            )
            return api_ok('500元组合路径已生成', data={
                'portfolio_path_to_500': plan,
                'metrics_source': 'request' if isinstance(data.get('metrics'), dict) else 'latest_snapshot',
                'actions_source': 'request' if isinstance(data.get('product_issue_actions') or data.get('productIssueActions'), list) else 'ledger',
                'source_action_count': len(actions),
                'ai_policy': dict(AI_POLICY),
            })
        except Exception as exc:
            traceback.print_exc()
            return api_error(f'500元组合路径生成失败: {str(exc)}')

    @routes.post('/api/ops/first-order-decision-matrix')
    def ops_first_order_decision_matrix():
        try:
            data = ops_request_data()
            ledger = get_ops_ledger()

            baseline_metrics = data.get('baseline_metrics') or data.get('baselineMetrics')
            if not isinstance(baseline_metrics, dict):
                latest = ledger.list_daily_snapshots(limit=1)
                baseline_metrics = latest[0] if latest else {}

            current_metrics = data.get('current_metrics') or data.get('currentMetrics') or data.get('metrics')
            if not isinstance(current_metrics, dict):
                current_metrics = baseline_metrics

            action = data.get('action') if isinstance(data.get('action'), dict) else None
            action_id = ops_int(data, 'action_id', ops_int(data, 'actionId', 0))
            if action is None and action_id:
                actions = ledger.list_product_issue_actions(limit=500)
                for row in actions:
                    if int(row.get('id') or 0) == int(action_id):
                        action = row
                        break
            if action is None:
                action = {}

            save_gate = data.get('save_gate') or data.get('saveGate')
            if not isinstance(save_gate, dict):
                evidence = action.get('evidence') if isinstance(action.get('evidence'), dict) else {}
                save_gate = evidence.get('save_edit_human_gate') if isinstance(evidence.get('save_edit_human_gate'), dict) else {}

            matrix = build_first_order_decision_matrix(
                baseline_metrics=baseline_metrics,
                current_metrics=current_metrics,
                action=action,
                save_gate=save_gate,
                target_net_profit=ops_float(data, 'target_net_profit', ops_float(data, 'targetNetProfit', DAILY_NET_PROFIT_TARGET)),
                saved_confirmed=bool(data.get('saved_confirmed') if 'saved_confirmed' in data else data.get('savedConfirmed', False)),
            )
            return api_ok('首单决策矩阵已生成', data={
                'first_order_decision_matrix': matrix,
                'baseline_metrics_source': 'request' if isinstance(data.get('baseline_metrics') or data.get('baselineMetrics'), dict) else 'latest_snapshot',
                'current_metrics_source': 'request' if isinstance(data.get('current_metrics') or data.get('currentMetrics') or data.get('metrics'), dict) else 'baseline_metrics',
                'action_source': 'request' if isinstance(data.get('action'), dict) else ('ledger' if action_id else 'empty'),
                'ai_policy': dict(AI_POLICY),
            })
        except Exception as exc:
            traceback.print_exc()
            return api_error(f'首单决策矩阵生成失败: {str(exc)}')

    @routes.post('/api/ops/net-profit-verification-matrix')
    def ops_net_profit_verification_matrix():
        try:
            data = ops_request_data()
            orders = data.get('orders') if isinstance(data.get('orders'), list) else []
            matrix = build_net_profit_verification_matrix(
                orders=orders,
                target_net_profit=ops_float(data, 'target_net_profit', ops_float(data, 'targetNetProfit', DAILY_NET_PROFIT_TARGET)),
            )
            return api_ok('经营净利核验矩阵已生成', data={
                'net_profit_verification_matrix': matrix,
                'orders_source': 'request' if isinstance(data.get('orders'), list) else 'empty',
                'ai_policy': dict(AI_POLICY),
            })
        except Exception as exc:
            traceback.print_exc()
            return api_error(f'经营净利核验矩阵生成失败: {str(exc)}')

    @routes.post('/api/ops/post-save-conversion-monitor')
    def ops_post_save_conversion_monitor():
        try:
            data = ops_request_data()
            ledger = get_ops_ledger()

            metrics = data.get('metrics') if isinstance(data.get('metrics'), dict) else None
            if metrics is None:
                latest = ledger.list_daily_snapshots(limit=1)
                metrics = latest[0] if latest else {}

            action = data.get('action') if isinstance(data.get('action'), dict) else None
            action_id = ops_int(data, 'action_id', ops_int(data, 'actionId', 0))
            if action is None and action_id > 0:
                actions = ledger.list_product_issue_actions(limit=500)
                action = next(
                    (item for item in actions if int(item.get('id') or 0) == action_id),
                    {},
                )
            if action is None:
                action = {}

            save_gate = data.get('save_gate') or data.get('saveGate')
            if not isinstance(save_gate, dict):
                save_gate = {}
            if not save_gate and isinstance(action, dict):
                action_evidence = action.get('evidence')
                if not isinstance(action_evidence, dict):
                    evidence_json = action.get('evidence_json')
                    if evidence_json:
                        try:
                            parsed_evidence = json.loads(str(evidence_json))
                            action_evidence = parsed_evidence if isinstance(parsed_evidence, dict) else {}
                        except Exception:
                            action_evidence = {}
                if isinstance(action_evidence, dict) and isinstance(action_evidence.get('save_edit_human_gate'), dict):
                    save_gate = dict(action_evidence.get('save_edit_human_gate') or {})

            conversion_experiment_plan = data.get('conversion_experiment_plan') or data.get('conversionExperimentPlan')
            if not isinstance(conversion_experiment_plan, dict):
                conversion_experiment_plan = None

            raw_saved_confirmed = data.get('saved_confirmed', data.get('savedConfirmed', False))
            saved_confirmed = (
                raw_saved_confirmed is True
                or str(raw_saved_confirmed).strip().lower() in {'1', 'true', 'yes', 'y'}
            )

            monitor = build_post_save_conversion_monitor(
                metrics=metrics,
                action=action,
                save_gate=save_gate,
                conversion_experiment_plan=conversion_experiment_plan,
                target_net_profit=ops_float(data, 'target_net_profit', ops_float(data, 'targetNetProfit', DAILY_NET_PROFIT_TARGET)),
                saved_confirmed=saved_confirmed,
            )
            return api_ok('保存后转化复盘闸已生成', data={
                'post_save_conversion_monitor': monitor,
                'metrics_source': 'request' if isinstance(data.get('metrics'), dict) else 'latest_snapshot',
                'action_source': 'request' if isinstance(data.get('action'), dict) else ('ledger' if action_id > 0 else 'empty'),
                'ai_policy': dict(AI_POLICY),
            })
        except Exception as exc:
            traceback.print_exc()
            return api_error(f'保存后转化复盘闸生成失败: {str(exc)}')

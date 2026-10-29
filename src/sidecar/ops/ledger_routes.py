# -*- coding: utf-8 -*-
"""运营闭环：运营账本读写类接口（/api/ops/*）。"""
import traceback

from flask import request

from src.ops_engine import (
    AI_POLICY,
    DAILY_NET_PROFIT_TARGET,
    build_daily_review,
    build_product_record_mappings,
    build_strategy_action_reconcile_plan,
    get_ops_ledger,
)
from ..responses import api_error, api_ok
from .support import (
    ops_build_local_product_candidates,
    ops_float,
    ops_int,
    ops_local_record_mapping_rows,
    ops_request_data,
)


def register_ops_ledger_routes(routes, *, record_model):
    """注册运营账本读写类接口。"""

    @routes.post('/api/ops/sync-strategy-signals')
    def ops_sync_strategy_signals():
        try:
            data = ops_request_data()
            signals = data.get('signals')
            if not isinstance(signals, dict):
                signals = data.get('diagnostic_signals') or data.get('diagnosticSignals')
            if not isinstance(signals, dict) or not signals:
                return api_error('diagnostic_signals 不能为空')

            signals = dict(signals)
            if not signals.get('raw_payload') and data.get('raw_payload'):
                signals['raw_payload'] = data.get('raw_payload')
            if data.get('source') and not signals.get('source'):
                signals['source'] = data.get('source')

            ledger = get_ops_ledger()
            audit_metrics = data.get('audit_metrics') if isinstance(data.get('audit_metrics'), list) else []
            browser_snapshot = data.get('browser') if isinstance(data.get('browser'), dict) else {}
            audit_rows = []
            if browser_snapshot.get('url') or browser_snapshot.get('title'):
                audit_rows.extend(ledger.save_browser_metric_audit([
                    {
                        'metric_name': 'strategy_browser_page',
                        'metric_value': browser_snapshot.get('title') or '',
                        'page_url': browser_snapshot.get('url') or '',
                        'status': browser_snapshot.get('status') or 'observed',
                    }
                ]))
            if audit_metrics:
                audit_rows.extend(ledger.save_browser_metric_audit(audit_metrics))

            saved = ledger.save_strategy_snapshot(signals)
            latest = ledger.list_daily_snapshots(limit=1)
            metrics = latest[0] if latest else {}
            review_metrics = {
                **(metrics or {}),
                'diagnostic_signals': signals,
            }
            candidate_data = ops_build_local_product_candidates(record_model, data)
            review = build_daily_review(review_metrics, candidate_data['candidates'])
            return api_ok('诊断信号同步完成', data={
                'synced': True,
                'saved_strategy_snapshot': saved['snapshot'],
                'product_issue_actions': saved['product_issue_actions'],
                'review': review,
                'metrics_source': 'latest_snapshot' if metrics else 'empty_snapshot',
                'audit_rows': audit_rows,
                'ai_policy': dict(AI_POLICY),
            })
        except Exception as exc:
            traceback.print_exc()
            return api_error(f'诊断信号同步失败: {str(exc)}')

    @routes.get('/api/ops/daily-snapshots')
    def ops_daily_snapshots():
        try:
            limit = ops_int(request.args, 'limit', 20)
            return api_ok('经营快照读取成功', data={
                'snapshots': get_ops_ledger().list_daily_snapshots(limit=limit),
                'target_net_profit': DAILY_NET_PROFIT_TARGET,
            })
        except Exception as exc:
            return api_error(f'经营快照读取失败: {str(exc)}')

    @routes.get('/api/ops/strategy-snapshots')
    def ops_strategy_snapshots():
        try:
            limit = ops_int(request.args, 'limit', 20)
            action_status = str(request.args.get('action_status') or request.args.get('actionStatus') or '').strip()
            ledger = get_ops_ledger()
            return api_ok('诊断快照读取成功', data={
                'snapshots': ledger.list_strategy_snapshots(limit=limit),
                'product_issue_actions': ledger.list_product_issue_actions(
                    limit=limit,
                    action_status=action_status or None,
                ),
                'ai_policy': dict(AI_POLICY),
            })
        except Exception as exc:
            return api_error(f'诊断快照读取失败: {str(exc)}')

    @routes.get('/api/ops/product-issue-actions')
    def ops_product_issue_actions():
        try:
            limit = ops_int(request.args, 'limit', 20)
            action_status = str(request.args.get('action_status') or request.args.get('actionStatus') or '').strip()
            action_id = ops_int(request.args, 'action_id', ops_int(request.args, 'actionId', 0))
            ledger = get_ops_ledger()
            return api_ok('商品问题待办读取成功', data={
                'product_issue_actions': ledger.list_product_issue_actions(
                    limit=limit,
                    action_status=action_status or None,
                ),
                'events': ledger.list_product_issue_action_events(
                    action_id=action_id or None,
                    limit=limit,
                ),
                'ai_policy': dict(AI_POLICY),
            })
        except Exception as exc:
            return api_error(f'商品问题待办读取失败: {str(exc)}')

    @routes.post('/api/ops/reconcile-strategy-actions')
    def ops_reconcile_strategy_actions():
        try:
            data = ops_request_data()
            limit = max(min(ops_int(data, 'limit', 500), 500), 1)
            apply_updates = bool(data.get('apply', data.get('applyUpdates', False)))
            latest_strategy_snapshot_id = ops_int(
                data,
                'latest_strategy_snapshot_id',
                ops_int(data, 'latestStrategySnapshotId', 0),
            )
            ledger = get_ops_ledger()
            actions = data.get('product_issue_actions') if isinstance(data.get('product_issue_actions'), list) else None
            if actions is None:
                actions = ledger.list_product_issue_actions(limit=limit)
            plan = build_strategy_action_reconcile_plan(
                product_issue_actions=actions,
                latest_strategy_snapshot_id=latest_strategy_snapshot_id or None,
            )

            applied = []
            if apply_updates:
                for update in plan.get('local_ledger_updates') or []:
                    if not isinstance(update, dict):
                        continue
                    action_id = ops_int(update, 'action_id', 0)
                    action_status = str(update.get('recommended_status') or '').strip()
                    if not action_id or not action_status:
                        continue
                    applied.append(ledger.update_product_issue_action(
                        action_id=action_id,
                        action_status=action_status,
                        note=str(update.get('note') or ''),
                        evidence=update.get('evidence') if isinstance(update.get('evidence'), dict) else {},
                    ))

            return api_ok('诊断待办状态对齐完成', data={
                'strategy_action_reconcile_plan': plan,
                'applied': applied,
                'applied_count': len(applied),
                'dry_run': not apply_updates,
                'actions_source': 'request' if isinstance(data.get('product_issue_actions'), list) else 'ledger',
                'ai_policy': dict(AI_POLICY),
            })
        except Exception as exc:
            traceback.print_exc()
            return api_error(f'诊断待办状态对齐失败: {str(exc)}')

    @routes.post('/api/ops/product-issue-actions/<int:action_id>')
    def ops_update_product_issue_action(action_id):
        try:
            data = ops_request_data()
            action_status = data.get('action_status') or data.get('actionStatus') or data.get('status')
            if not action_status:
                return api_error('action_status 不能为空')
            evidence = data.get('evidence') if isinstance(data.get('evidence'), dict) else {}
            updated = get_ops_ledger().update_product_issue_action(
                action_id=action_id,
                action_status=str(action_status),
                note=str(data.get('note') or data.get('action_note') or data.get('actionNote') or ''),
                evidence=evidence,
            )
            events = get_ops_ledger().list_product_issue_action_events(action_id=action_id, limit=5)
            return api_ok('商品问题待办状态已更新', data={
                'updated_action': updated,
                'events': events,
                'ai_policy': dict(AI_POLICY),
            })
        except Exception as exc:
            traceback.print_exc()
            return api_error(f'商品问题待办状态更新失败: {str(exc)}')

    @routes.post('/api/ops/sync-product-record-mappings')
    def ops_sync_product_record_mappings():
        try:
            data = ops_request_data()
            limit = max(min(ops_int(data, 'limit', 50), 200), 1)
            min_confidence = ops_float(data, 'min_confidence', ops_float(data, 'minConfidence', 0.72))
            action_status = str(data.get('action_status') or data.get('actionStatus') or '').strip()
            ledger = get_ops_ledger()
            actions = data.get('product_issue_actions') if isinstance(data.get('product_issue_actions'), list) else None
            if actions is None:
                actions = ledger.list_product_issue_actions(
                    limit=limit,
                    action_status=action_status or None,
                )
            shop_products = []
            for action in actions:
                if not isinstance(action, dict):
                    continue
                shop_products.append({
                    'action_id': action.get('id') or action.get('action_id') or action.get('actionId'),
                    'product_id': action.get('product_id') or action.get('productId'),
                    'title': action.get('title') or '',
                })
            local_records = ops_local_record_mapping_rows(record_model)
            mappings = build_product_record_mappings(
                shop_products=shop_products,
                local_records=local_records,
                min_confidence=min_confidence,
            )
            saved = ledger.save_product_record_mappings(mappings)
            summary = {
                'total': len(saved),
                'matched': len([item for item in saved if item.get('match_status') == 'matched']),
                'unmatched': len([item for item in saved if item.get('match_status') == 'unmatched']),
                'local_record_count': len(local_records),
            }
            return api_ok('线上商品与本地 Record 映射已生成', data={
                'summary': summary,
                'mappings': saved,
                'local_records': local_records,
                'ai_policy': dict(AI_POLICY),
            })
        except Exception as exc:
            traceback.print_exc()
            return api_error(f'线上商品与本地 Record 映射失败: {str(exc)}')

    @routes.get('/api/ops/product-record-mappings')
    def ops_product_record_mappings():
        try:
            limit = ops_int(request.args, 'limit', 20)
            match_status = str(request.args.get('match_status') or request.args.get('matchStatus') or '').strip()
            return api_ok('线上商品与本地 Record 映射读取成功', data={
                'mappings': get_ops_ledger().list_product_record_mappings(
                    limit=limit,
                    match_status=match_status or None,
                ),
                'ai_policy': dict(AI_POLICY),
            })
        except Exception as exc:
            return api_error(f'线上商品与本地 Record 映射读取失败: {str(exc)}')

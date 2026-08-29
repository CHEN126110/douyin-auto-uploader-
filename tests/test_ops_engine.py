# -*- coding: utf-8 -*-

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.ops_engine import (
    DAILY_NET_PROFIT_TARGET,
    OperatingCostInput,
    OpsLedger,
    ProductEvaluationInput,
    StockPlanInput,
    ProductCandidateInput,
    apply_candidate_pricing_to_skus,
    build_daily_plan,
    build_daily_review,
    build_conversion_experiment_plan,
    build_conversion_asset_pack,
    build_detail_conversion_audit,
    build_detail_improvement_suggestions,
    build_diagnostic_action_plan,
    build_growth_bottleneck_plan,
    build_market_context,
    build_material_gap_plan,
    build_no_brand_title_audit,
    build_no_brand_remediation_plan,
    build_ops_execution_queue,
    build_portfolio_path_to_500,
    build_first_order_decision_matrix,
    build_net_profit_verification_matrix,
    build_post_save_conversion_monitor,
    build_profit_ladder_to_500,
    build_profit_ramp_plan,
    build_product_record_mappings,
    build_strategy_action_reconcile_plan,
    build_search_conversion_work_package,
    build_sourcing_profit_gate,
    build_supplier_quote_intake,
    build_supplier_quote_plan,
    build_product_candidate,
    build_product_candidate_list,
    build_stock_plan,
    calculate_operating_profit,
    enforce_no_external_ai_settings,
    evaluate_product,
    extract_sku_goods_costs,
    merge_observed_shop_metrics,
    resolve_ops_ledger_path,
)


class OpsEngineProfitTest(unittest.TestCase):
    def test_calculates_operating_net_profit_with_all_costs(self) -> None:
        result = calculate_operating_profit(
            OperatingCostInput(
                sale_price=29.9,
                goods_cost=8.0,
                shipping_cost=3.0,
                packaging_cost=0.5,
                platform_commission_rate=0.05,
                promotion_cost=2.0,
                refund_loss=1.0,
                after_sale_loss=0.5,
            )
        )

        self.assertEqual(result.net_profit, 13.4)
        self.assertEqual(result.cost_total, 16.5)
        self.assertEqual(result.platform_commission, 1.5)
        self.assertEqual(result.target_daily_orders, 38)
        self.assertEqual(DAILY_NET_PROFIT_TARGET, 500)

    def test_search_conversion_work_package_keeps_no_brand_and_readonly_gates(self) -> None:
        package = build_search_conversion_work_package(
            metrics={
                "id": 24,
                "snapshot_date": "2026-06-03",
                "product_exposure_count": 45,
                "product_click_count": 3,
                "search_exposure_count": 235,
                "orders_count": 0,
                "promotion_cost": 0,
                "raw_payload": {
                    "text_excerpt": "62个非自己发的视频未配置看后搜 设置小蓝词 澳洲小绿正品等19个 承接商品，曝光显著提升"
                },
            },
            product_issue_actions=[
                {
                    "id": 1,
                    "product_id": "3819238447663677663",
                    "title": "韩系波点中筒袜防臭夏天袜子白女夏季薄款甜美蕾丝花边棉袜堆堆袜",
                    "recent_30d_sales": 7,
                    "action_status": "blocked",
                },
                {
                    "id": 2,
                    "product_id": "3811600816893198348",
                    "title": "songmu淞木 布标镂空无骨袜子女春夏新品薄款中筒袜韩系ins堆堆",
                    "recent_30d_sales": 5,
                    "action_status": "blocked",
                },
            ],
        )

        self.assertEqual(package["plan_type"], "search_conversion_work_package")
        self.assertEqual(package["current_state"]["snapshot_id"], 24)
        self.assertEqual(package["stage"], "search_click_without_order")
        self.assertEqual(package["brand_policy"]["required_value"], "无品牌")
        self.assertFalse(package["safe_to_auto_apply"])
        self.assertTrue(package["paid_ads_paused"])
        self.assertEqual(package["focus_products"][0]["action_id"], 1)
        self.assertIn("看后搜", "".join(package["readonly_platform_signals"]))
        self.assertIn("小蓝词", "".join(package["readonly_platform_signals"]))
        terms = " ".join(package["candidate_search_terms"])
        self.assertIn("波点中筒袜", terms)
        for forbidden in ("songmu", "淞木", "KIKISOCKS", "品牌", "澳洲小绿"):
            self.assertNotIn(forbidden, terms)
        self.assertIn("不得自动批量设置小蓝词或看后搜", package["forbidden_actions"])
        self.assertTrue(package["ai_policy"]["external_ai_disabled"])

    def test_strategy_action_reconcile_plan_inherits_prior_status_and_blocks_brand_risk(self) -> None:
        plan = build_strategy_action_reconcile_plan(
            product_issue_actions=[
                {
                    "id": 1,
                    "strategy_snapshot_id": 1,
                    "product_id": "3819238447663677663",
                    "title": "韩系波点中筒袜防臭夏天袜子白女夏季薄款甜美蕾丝花边棉袜堆堆袜",
                    "recent_30d_sales": 7,
                    "action_status": "blocked",
                    "action_note": "缺同款素材、无品牌供货凭证和成本证据",
                },
                {
                    "id": 3,
                    "strategy_snapshot_id": 1,
                    "product_id": "3811995393416364123",
                    "title": "小雏菊碎花袜子女春夏新款镂空网眼中筒袜无骨甜美木耳边堆堆袜女",
                    "recent_30d_sales": 1,
                    "action_status": "in_progress",
                    "action_note": "等待人工保存确认",
                },
                {
                    "id": 10,
                    "strategy_snapshot_id": 3,
                    "product_id": "3819238447663677663",
                    "title": "韩系波点中筒袜防臭夏天袜子白女夏季薄款甜美蕾丝花边棉袜堆堆袜",
                    "recent_30d_sales": 7,
                    "action_status": "open",
                },
                {
                    "id": 11,
                    "strategy_snapshot_id": 3,
                    "product_id": "3811600816893198348",
                    "title": "songmu淞木 布标镂空无骨袜子女春夏新品薄款中筒袜韩系ins堆堆",
                    "recent_30d_sales": 5,
                    "action_status": "open",
                },
                {
                    "id": 12,
                    "strategy_snapshot_id": 3,
                    "product_id": "3811995393416364123",
                    "title": "小雏菊碎花袜子女春夏新款镂空网眼中筒袜无骨甜美木耳边堆堆袜女",
                    "recent_30d_sales": 1,
                    "action_status": "open",
                },
            ],
        )

        self.assertEqual(plan["plan_type"], "strategy_action_reconcile_plan")
        self.assertEqual(plan["latest_strategy_snapshot_id"], 3)
        self.assertFalse(plan["safe_to_shop_mutation"])
        self.assertTrue(plan["ai_policy"]["external_ai_disabled"])

        updates = {item["action_id"]: item for item in plan["local_ledger_updates"]}
        self.assertEqual(updates[10]["recommended_status"], "blocked")
        self.assertEqual(updates[10]["inherited_from_action_id"], 1)
        self.assertIn("供应商/同款素材/无品牌凭证", updates[10]["note"])

        self.assertEqual(updates[11]["recommended_status"], "blocked")
        self.assertEqual(updates[11]["reason"], "brand_residue")
        self.assertIn("songmu", "".join(updates[11]["risk_terms"]).lower())

        self.assertEqual(updates[12]["recommended_status"], "in_progress")
        self.assertEqual(updates[12]["inherited_from_action_id"], 3)
        self.assertIn("等待人工保存确认", updates[12]["note"])

    def test_strategy_action_reconcile_plan_prefers_prior_in_progress_with_upload_evidence(self) -> None:
        plan = build_strategy_action_reconcile_plan(
            product_issue_actions=[
                {
                    "id": 3,
                    "strategy_snapshot_id": 1,
                    "product_id": "3811995393416364123",
                    "title": "小雏菊碎花袜子女春夏新款镂空网眼中筒袜无骨甜美木耳边堆堆袜女",
                    "recent_30d_sales": 1,
                    "action_status": "in_progress",
                    "action_note": "主图视频上传截停后等待人工保存确认",
                    "evidence": {
                        "mutation_type": "main_video_upload_only",
                        "upload_result": {
                            "upload_triggered": True,
                            "upload_confirmed": True,
                        },
                        "save_edit_human_gate": {
                            "ready_for_human_save_confirmation": True,
                        },
                    },
                },
                {
                    "id": 21,
                    "strategy_snapshot_id": 4,
                    "product_id": "3811995393416364123",
                    "title": "小雏菊碎花袜子女春夏新款镂空网眼中筒袜无骨甜美木耳边堆堆袜女",
                    "recent_30d_sales": 1,
                    "action_status": "in_progress",
                    "action_note": "上传前安全预检通过",
                    "evidence": {
                        "preflight": {
                            "ready_for_upload_preflight": True,
                        },
                    },
                },
                {
                    "id": 30,
                    "strategy_snapshot_id": 5,
                    "product_id": "3811995393416364123",
                    "title": "小雏菊碎花袜子女春夏新款镂空网眼中筒袜无骨甜美木耳边堆堆袜女",
                    "recent_30d_sales": 1,
                    "action_status": "open",
                },
            ],
            latest_strategy_snapshot_id=5,
        )

        update = plan["local_ledger_updates"][0]
        self.assertEqual(update["action_id"], 30)
        self.assertEqual(update["recommended_status"], "in_progress")
        self.assertEqual(update["inherited_from_action_id"], 3)
        self.assertEqual(update["evidence"]["mutation_type"], "main_video_upload_only")
        self.assertTrue(update["evidence"]["upload_result"]["upload_confirmed"])
        self.assertTrue(update["evidence"]["save_edit_human_gate"]["ready_for_human_save_confirmation"])

    def test_evaluates_product_with_conservative_launch_decision(self) -> None:
        evaluation = evaluate_product(
            ProductEvaluationInput(
                record_id=7,
                title="春夏浅口船袜女",
                sale_price=19.9,
                goods_cost=5.2,
                shipping_cost=3.0,
                packaging_cost=0.5,
                platform_commission_rate=0.05,
                promotion_cost=1.0,
                refund_loss=0,
                after_sale_loss=0,
                expected_daily_orders=18,
            )
        )

        self.assertEqual(evaluation.net_profit_per_order, 9.2)
        self.assertEqual(evaluation.expected_daily_net_profit, 165.6)
        self.assertEqual(evaluation.decision, "test_launch")
        self.assertIn("低预算试卖", evaluation.rationale)

    def test_net_profit_verification_matrix_does_not_verify_without_orders(self) -> None:
        matrix = build_net_profit_verification_matrix(
            orders=[],
            target_net_profit=500,
        )

        self.assertEqual(matrix["plan_type"], "net_profit_verification_matrix")
        self.assertFalse(matrix["net_profit_verified"])
        self.assertEqual(matrix["decision"], "wait_for_orders")
        self.assertEqual(matrix["verified_order_count"], 0)
        self.assertIn("没有订单，不能核验经营净利", matrix["blockers"])
        self.assertTrue(matrix["ai_policy"]["external_ai_disabled"])

    def test_net_profit_verification_matrix_requires_complete_cost_evidence(self) -> None:
        matrix = build_net_profit_verification_matrix(
            orders=[
                {
                    "order_id": "order-1",
                    "product_id": "3811995393416364123",
                    "sale_price": 20,
                    "goods_cost": 2,
                    "shipping_cost": 3,
                    "packaging_cost": 0.3,
                    "platform_commission_rate": 0.05,
                    "promotion_cost": 0,
                    "refund_loss": 0,
                    "after_sale_loss": 0,
                },
                {
                    "order_id": "order-2",
                    "product_id": "3811995393416364123",
                    "sale_price": 20,
                    "shipping_cost": 3,
                    "platform_commission_rate": 0.05,
                },
            ],
            target_net_profit=500,
        )

        self.assertFalse(matrix["net_profit_verified"])
        self.assertEqual(matrix["decision"], "needs_cost_evidence")
        self.assertEqual(matrix["verified_order_count"], 1)
        self.assertEqual(matrix["unverified_order_count"], 1)
        self.assertIn("存在订单缺少商品成本、运费、佣金、推广费、退款或售后证据", matrix["blockers"])
        self.assertFalse(matrix["ready_for_paid_scale"])

    def test_net_profit_verification_matrix_sums_verified_order_profit(self) -> None:
        matrix = build_net_profit_verification_matrix(
            orders=[
                {
                    "order_id": f"order-{index}",
                    "product_id": "3811995393416364123",
                    "sale_price": 20,
                    "goods_cost": 2,
                    "shipping_cost": 3,
                    "packaging_cost": 0.3,
                    "platform_commission_rate": 0.05,
                    "promotion_cost": 0,
                    "refund_loss": 0.2,
                    "after_sale_loss": 0,
                }
                for index in range(1, 39)
            ],
            target_net_profit=500,
        )

        self.assertTrue(matrix["net_profit_verified"])
        self.assertEqual(matrix["verified_order_count"], 38)
        self.assertEqual(matrix["total_net_profit"], 513.0)
        self.assertEqual(matrix["decision"], "target_verified")
        self.assertTrue(matrix["ready_for_paid_scale"])
        self.assertEqual(matrix["brand_policy"]["required_value"], "无品牌")


class OpsEngineStockPlanTest(unittest.TestCase):
    def test_builds_conservative_stock_plan_without_sales_signal(self) -> None:
        plan = build_stock_plan(
            StockPlanInput(
                record_id=7,
                sku_count=10,
                expected_daily_orders=0,
                replenishment_days=1,
                can_restock_same_day=True,
            )
        )

        self.assertEqual(plan.total_recommended_stock, 20)
        self.assertEqual(plan.per_sku_stock, 2)
        self.assertEqual(plan.risk_level, "low")
        self.assertIn("没有实销信号", plan.rationale)

    def test_builds_stock_plan_from_expected_orders(self) -> None:
        plan = build_stock_plan(
            StockPlanInput(
                record_id=8,
                sku_count=6,
                expected_daily_orders=24,
                replenishment_days=2,
                can_restock_same_day=False,
            )
        )

        self.assertEqual(plan.total_recommended_stock, 60)
        self.assertEqual(plan.per_sku_stock, 10)
        self.assertEqual(plan.risk_level, "medium")


class OpsEnginePolicyAndLedgerTest(unittest.TestCase):
    def test_profit_ramp_plan_quantifies_500_goal_from_candidate_margin(self) -> None:
        plan = build_profit_ramp_plan(
            {
                "snapshot_date": "2026-06-02",
                "gross_sales": 0,
                "orders_count": 0,
                "product_exposure_count": 68,
                "product_click_count": 1,
                "search_exposure_count": 255,
                "promotion_cost": 0,
                "net_profit_verified": False,
            },
            [
                {
                    "record_id": 1,
                    "title": "女款动物图案浅口船袜春夏薄款可爱短袜单双装均码",
                    "evaluation": {
                        "net_profit_per_order": 9.2,
                        "target_daily_orders": 55,
                    },
                }
            ],
        )

        self.assertEqual(plan["stage"], "detail_conversion_bottleneck")
        self.assertEqual(plan["target_orders"]["minimum_daily_orders"], 55)
        self.assertEqual(plan["target_orders"]["current_orders"], 0)
        self.assertEqual(plan["traffic_estimate"]["assumption_click_to_order_rate_percent"], 2.0)
        self.assertEqual(plan["traffic_estimate"]["estimated_clicks_for_target"], 2750)
        self.assertTrue(plan["paid_ads_paused"])
        self.assertFalse(plan["scale_readiness"]["ready_for_paid_scale"])
        self.assertIn("详情页", "；".join(plan["actions"]))

    def test_profit_ramp_plan_blocks_goal_math_without_unit_profit(self) -> None:
        plan = build_profit_ramp_plan(
            {
                "snapshot_date": "2026-06-02",
                "orders_count": 0,
                "product_exposure_count": 0,
                "product_click_count": 0,
                "net_profit_verified": False,
            },
            [],
        )

        self.assertEqual(plan["stage"], "unit_economics_missing")
        self.assertIsNone(plan["target_orders"]["minimum_daily_orders"])
        self.assertTrue(plan["paid_ads_paused"])
        self.assertIn("单笔经营净利", "；".join(plan["actions"]))

    def test_profit_ladder_to_500_quantifies_action3_cost_scenarios_without_scaling(self) -> None:
        ladder = build_profit_ladder_to_500(
            metrics={
                "id": 22,
                "snapshot_date": "2026-06-03",
                "product_exposure_count": 36,
                "product_click_count": 3,
                "orders_count": 0,
                "net_profit_verified": False,
                "promotion_cost": 0,
            },
            product={
                "action_id": 3,
                "product_id": "3811995393416364123",
                "title": "小雏菊碎花袜子女春夏新款镂空网眼中筒袜无骨甜美木耳边堆堆袜女",
                "sale_price": 20,
                "shipping_cost": 3,
                "packaging_cost": 0.3,
                "platform_commission_rate": 0.05,
                "refund_loss": 0.2,
            },
            cost_scenarios=[
                {"scenario_id": "low_cost", "goods_cost": 2},
                {"scenario_id": "mid_cost", "goods_cost": 5},
                {"scenario_id": "high_cost", "goods_cost": 8},
            ],
        )

        self.assertEqual(ladder["plan_type"], "profit_ladder_to_500")
        self.assertEqual(ladder["stage"], "detail_conversion_bottleneck")
        self.assertEqual(ladder["product_context"]["sale_price"], 20.0)
        self.assertEqual(ladder["current_state"]["snapshot_id"], 22)
        self.assertEqual(ladder["current_state"]["orders_count"], 0)
        self.assertTrue(ladder["paid_ads_paused"])
        self.assertFalse(ladder["ready_for_paid_scale"])
        self.assertTrue(ladder["requires_first_order_validation"])
        self.assertTrue(ladder["requires_cost_confirmation"])
        self.assertEqual(ladder["ladder"][0]["scenario_id"], "low_cost")
        self.assertEqual(ladder["ladder"][0]["net_profit_per_order"], 13.5)
        self.assertEqual(ladder["ladder"][0]["minimum_daily_orders_for_500"], 38)
        self.assertEqual(ladder["ladder"][1]["minimum_daily_orders_for_500"], 48)
        self.assertEqual(ladder["ladder"][2]["minimum_daily_orders_for_500"], 67)
        self.assertIn("不投放", "；".join(ladder["actions"]))

    def test_profit_ladder_to_500_flags_unprofitable_or_volume_heavy_scenarios(self) -> None:
        ladder = build_profit_ladder_to_500(
            metrics={
                "product_exposure_count": 10,
                "product_click_count": 0,
                "orders_count": 0,
                "net_profit_verified": False,
            },
            product={
                "sale_price": 6.8,
                "shipping_cost": 3,
                "packaging_cost": 0.3,
                "platform_commission_rate": 0.05,
                "refund_loss": 0.2,
            },
            cost_scenarios=[
                {"scenario_id": "too_high", "goods_cost": 3},
                {"scenario_id": "barely", "goods_cost": 1},
            ],
        )

        self.assertEqual(ladder["ladder"][0]["decision"], "reject_unprofitable")
        self.assertIsNone(ladder["ladder"][0]["minimum_daily_orders_for_500"])
        self.assertEqual(ladder["ladder"][1]["decision"], "volume_too_heavy")
        self.assertGreater(ladder["ladder"][1]["minimum_daily_orders_for_500"], 200)
        self.assertEqual(ladder["brand_policy"]["required_value"], "无品牌")
        self.assertTrue(ladder["ai_policy"]["external_ai_disabled"])
        self.assertIn("不调用抖店官方 API", ladder["safety_gates"])
        self.assertIn("不调用外部 AI 或第三方模型", ladder["safety_gates"])

    def test_enforces_no_external_ai_settings(self) -> None:
        sanitized = enforce_no_external_ai_settings(
            {
                "model_configs": [
                    {
                        "provider": "openai",
                        "enabled": True,
                        "api_key": "sk-test",
                        "api_base": "https://api.openai.com/v1",
                        "model_name": "gpt-4",
                    }
                ],
                "automation_config": {"shipping_template": "中通包邮"},
            }
        )

        self.assertEqual(sanitized["model_configs"], [])
        self.assertTrue(sanitized["ai_policy"]["external_ai_disabled"])
        self.assertEqual(sanitized["ai_policy"]["decision_source"], "codex_only")

    def test_ledger_initializes_and_persists_daily_snapshot_utf8(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "ops.db"
            ledger = OpsLedger(db_path)
            snapshot = ledger.save_daily_snapshot(
                {
                    "snapshot_date": "2026-06-02",
                    "net_profit": 123.45,
                    "gross_sales": 456.78,
                    "promotion_cost": 12.3,
                    "source": "browser",
                    "status": "partial",
                    "notes": "中文备注：少量订单，继续低预算验证",
                }
            )

            self.assertGreaterEqual(snapshot["id"], 1)
            loaded = ledger.list_daily_snapshots()
            self.assertEqual(loaded[0]["notes"], "中文备注：少量订单，继续低预算验证")
            self.assertEqual(loaded[0]["target_net_profit"], 500)

    def test_daily_plan_reports_gap_and_next_actions(self) -> None:
        plan = build_daily_plan(
            {
                "net_profit": 165.6,
                "net_profit_verified": True,
                "ready_products": 1,
                "blocked_products": 2,
                "low_stock_products": 1,
            }
        )

        self.assertEqual(plan["target_net_profit"], 500)
        self.assertEqual(plan["profit_gap"], 334.4)
        self.assertIn("优先处理 2 个发布阻塞商品", plan["actions"])

    def test_daily_plan_does_not_treat_missing_net_profit_as_verified(self) -> None:
        plan = build_daily_plan(
            {
                "gross_sales": 368.8,
                "orders_count": 12,
                "promotion_cost": 18.5,
                "net_profit_verified": False,
                "status": "cdp_partial_no_net_profit",
            }
        )

        self.assertFalse(plan["net_profit_verified"])
        self.assertEqual(plan["profit_gap"], None)
        self.assertIn("还没有可核算净利", "；".join(plan["actions"]))

    def test_merge_observed_shop_metrics_preserves_missing_previous_values(self) -> None:
        merged = merge_observed_shop_metrics(
            {
                "gross_sales": 0,
                "orders_count": 0,
                "product_exposure_count": 69,
                "product_click_count": 1,
                "raw_payload": {
                    "observed_metric_keys": [
                        "gross_sales",
                        "orders_count",
                        "product_exposure_count",
                        "product_click_count",
                    ],
                },
            },
            {
                "search_exposure_count": 255,
                "promotion_cost": 0,
                "experience_score": 70,
            },
        )

        self.assertEqual(merged["gross_sales"], 0)
        self.assertEqual(merged["search_exposure_count"], 255)
        self.assertEqual(merged["promotion_cost"], 0)
        self.assertIn("search_exposure_count", merged["raw_payload"]["merged_missing_metric_keys"])

    def test_merge_observed_shop_metrics_keeps_observed_zero(self) -> None:
        merged = merge_observed_shop_metrics(
            {
                "search_exposure_count": 0,
                "raw_payload": {
                    "observed_metric_keys": ["search_exposure_count"],
                },
            },
            {"search_exposure_count": 255},
        )

        self.assertEqual(merged["search_exposure_count"], 0)
        self.assertEqual(merged["raw_payload"]["merged_missing_metric_keys"], [])

    def test_merge_observed_shop_metrics_skips_previous_unobserved_field(self) -> None:
        merged = merge_observed_shop_metrics(
            {
                "gross_sales": 0,
                "raw_payload": {"observed_metric_keys": ["gross_sales"]},
            },
            [
                {
                    "id": 13,
                    "search_exposure_count": 0,
                    "raw_payload_json": '{"observed_metric_keys":["gross_sales"],"merged_missing_metric_keys":[]}',
                },
                {
                    "id": 12,
                    "search_exposure_count": 255,
                    "raw_payload_json": '{"observed_metric_keys":["search_exposure_count"]}',
                },
            ],
        )

        self.assertEqual(merged["search_exposure_count"], 255)
        self.assertIn("search_exposure_count", merged["raw_payload"]["merged_missing_metric_keys"])
        self.assertEqual(merged["raw_payload"]["merged_from_previous_snapshot_id"], 12)

    def test_daily_plan_flags_exposure_without_clicks_as_click_bottleneck(self) -> None:
        plan = build_daily_plan(
            {
                "gross_sales": 0,
                "orders_count": 0,
                "promotion_cost": 0,
                "product_exposure_count": 51,
                "product_click_count": 0,
                "search_exposure_count": 251,
                "net_profit_verified": False,
            }
        )

        self.assertEqual(plan["product_exposure_count"], 51)
        self.assertEqual(plan["product_click_count"], 0)
        self.assertEqual(plan["search_exposure_count"], 251)
        actions = "；".join(plan["actions"])
        self.assertIn("51 个商品曝光但点击为 0", actions)
        self.assertIn("暂停付费投放", actions)
        self.assertIn("首图", actions)
        self.assertIn("market_context", plan)
        self.assertEqual(plan["market_context"]["brand_policy"], "no_brand_only_without_qualification")
        self.assertIn("功能化", "；".join(plan["market_context"]["market_signals"]))

    def test_growth_bottleneck_plan_prioritizes_card_assets_when_exposure_has_no_clicks(self) -> None:
        plan = build_growth_bottleneck_plan(
            {
                "product_exposure_count": 51,
                "product_click_count": 0,
                "search_exposure_count": 251,
                "orders_count": 0,
            },
            {
                "record_id": 1,
                "title": "女款动物图案浅口船袜春夏薄款可爱短袜单双装均码",
                "recommended_sale_price": 8.9,
            },
        )

        self.assertEqual(plan["stage"], "card_click_bottleneck")
        self.assertTrue(plan["paid_ads_paused"])
        self.assertEqual(plan["primary_metric"], "product_click_count")
        self.assertIn("product_click_rate", plan["next_review_metrics"])
        actions = "；".join(item["action"] for item in plan["priority_actions"])
        self.assertIn("首图", actions)
        self.assertIn("主图视频", actions)
        self.assertIn("标题关键词", actions)
        self.assertIn("价格展示", actions)
        self.assertIn("51 曝光 0 点击", plan["diagnosis"])

    def test_market_context_embeds_sock_category_and_no_brand_safety(self) -> None:
        context = build_market_context(
            {
                "product_exposure_count": 51,
                "product_click_count": 0,
                "search_exposure_count": 251,
            }
        )

        self.assertEqual(context["category"], "socks")
        self.assertEqual(context["brand_policy"], "no_brand_only_without_qualification")
        self.assertIn("无品牌", "；".join(context["compliance_rules"]))
        self.assertIn("搜索运营", "；".join(context["platform_signals"]))
        self.assertIn("功能化", "；".join(context["market_signals"]))
        self.assertIn("暂停付费投放", "；".join(context["stage_actions"]))

    def test_no_brand_title_audit_prioritizes_real_brand_risk_without_style_false_positive(self) -> None:
        audit = build_no_brand_title_audit(
            [
                {
                    "id": 2,
                    "product_id": "3811600816893198348",
                    "title": "songmu淞木 布标镂空无骨袜子女春夏新品薄款中筒袜韩系ins堆堆",
                    "action_status": "blocked",
                },
                {
                    "id": 4,
                    "product_id": "3676351545072550092",
                    "title": "无骨堆堆袜子纯棉女学院风夏季薄款白色女袜中筒袜灰色jk透气长袜",
                    "action_status": "open",
                },
            ]
        )

        self.assertEqual(audit["risk_count"], 1)
        self.assertEqual(audit["risky_products"][0]["action_id"], 2)
        self.assertIn("source_brand_like_prefix", audit["risky_products"][0]["risk_flags"])
        self.assertIn("无品牌", audit["brand_policy"]["required_value"])
        self.assertTrue(audit["safe_products"][0]["title"].endswith("jk透气长袜"))

    def test_no_brand_remediation_plan_builds_readonly_title_fix_gate_for_risky_products(self) -> None:
        plan = build_no_brand_remediation_plan(
            [
                {
                    "id": 2,
                    "product_id": "3811600816893198348",
                    "title": "songmu淞木 布标镂空无骨袜子女春夏新品薄款中筒袜韩系ins堆堆",
                    "action_status": "blocked",
                },
                {
                    "id": 7,
                    "product_id": "3811596586392355102",
                    "title": "KIKISOCKS袜子女春夏薄款透气花边微压中筒韩系甜美少女风",
                    "action_status": "blocked",
                },
            ]
        )

        self.assertEqual(plan["plan_type"], "no_brand_remediation_plan")
        self.assertEqual(plan["summary"]["risk_count"], 2)
        self.assertFalse(plan["safe_to_auto_apply"])
        self.assertTrue(plan["browser_readonly_first"])
        self.assertEqual(plan["brand_policy"]["required_value"], "无品牌")
        self.assertFalse(plan["brand_policy"]["title_use_brand_name_required"])
        self.assertTrue(plan["ai_policy"]["external_ai_disabled"])
        rows = plan["remediation_items"]
        self.assertEqual([row["action_id"] for row in rows], [2, 7])
        self.assertNotIn("songmu", rows[0]["proposed_title"].lower())
        self.assertNotIn("淞木", rows[0]["proposed_title"])
        self.assertNotIn("kikisocks", rows[1]["proposed_title"].lower())
        self.assertIn("只读确认", rows[0]["required_precheck"])
        self.assertFalse(rows[0]["safe_to_auto_save"])

    def test_no_brand_remediation_plan_ignores_safe_style_terms_and_keeps_safety_gates(self) -> None:
        plan = build_no_brand_remediation_plan(
            [
                {
                    "id": 4,
                    "product_id": "3676351545072550092",
                    "title": "无骨堆堆袜子纯棉女学院风夏季薄款白色女袜中筒袜灰色jk透气长袜",
                    "action_status": "open",
                },
            ]
        )

        self.assertEqual(plan["summary"]["risk_count"], 0)
        self.assertEqual(plan["summary"]["safe_count"], 1)
        self.assertEqual(plan["remediation_items"], [])
        self.assertIn("不调用抖店官方 API", plan["safety_gates"])
        self.assertIn("不调用外部 AI 或第三方模型", plan["safety_gates"])
        self.assertIn("不自动保存、不发布、不投放、不付款", plan["safety_gates"])

    def test_diagnostic_action_plan_prioritizes_material_and_wrong_order_reduction(self) -> None:
        plan = build_diagnostic_action_plan(
            {
                "missing_main_video_count": 6,
                "missing_spec_image_count": 3,
                "attribute_optimization_count": 6,
                "risk_product_count": 12,
                "opportunity_keywords": ["女夏季薄款船袜", "女夏季薄款棉袜"],
                "refund_reasons": {"多拍/错拍/不想要": 12},
            }
        )

        self.assertEqual(plan["primary_focus"], "product_material_quality")
        self.assertIn("主图视频", "；".join(plan["actions"]))
        self.assertIn("规格图", "；".join(plan["actions"]))
        self.assertIn("多拍/错拍/不想要", "；".join(plan["actions"]))
        self.assertIn("女夏季薄款船袜", "；".join(plan["actions"]))
        self.assertFalse(plan["paid_ads_ready"])

    def test_daily_plan_includes_diagnostic_actions_when_signals_are_present(self) -> None:
        plan = build_daily_plan(
            {
                "gross_sales": 0,
                "orders_count": 0,
                "promotion_cost": 0,
                "product_exposure_count": 51,
                "product_click_count": 0,
                "search_exposure_count": 251,
                "net_profit_verified": False,
                "diagnostic_signals": {
                    "missing_main_video_count": 6,
                    "missing_spec_image_count": 3,
                    "opportunity_keywords": ["女夏季薄款船袜"],
                    "refund_reasons": {"多拍/错拍/不想要": 12},
                },
            }
        )

        self.assertIn("diagnostic_action_plan", plan)
        self.assertEqual(plan["diagnostic_action_plan"]["primary_focus"], "product_material_quality")
        self.assertIn("女夏季薄款船袜", "；".join(plan["actions"]))

    def test_diagnostic_action_plan_prioritizes_specific_product_issue_rows(self) -> None:
        plan = build_diagnostic_action_plan(
            {
                "missing_main_video_count": 6,
                "product_issues": [
                    {
                        "title": "韩系波点中筒袜防臭夏天袜子白女夏季薄款甜美蕾丝花边棉袜堆堆袜",
                        "product_id": "3819238447663677663",
                        "quality_score": 90,
                        "recent_30d_sales": 7,
                        "issues": [
                            "商品缺少主图视频或主图视频质量不合格",
                            "商品缺少讲解回放",
                        ],
                    },
                    {
                        "title": "songmu淞木 布标镂空无骨袜子女春夏新品薄款中筒袜韩系ins堆堆",
                        "product_id": "3811600816893198348",
                        "quality_score": 90,
                        "recent_30d_sales": 5,
                        "issues": ["商品缺少规格图"],
                    },
                ],
            }
        )

        self.assertEqual(plan["specific_issue_products"][0]["product_id"], "3819238447663677663")
        self.assertIn("近30天销量 7", "；".join(plan["actions"]))
        self.assertIn("3819238447663677663", "；".join(plan["actions"]))

    def test_growth_bottleneck_plan_focuses_conversion_when_clicks_have_no_orders(self) -> None:
        plan = build_growth_bottleneck_plan(
            {
                "product_exposure_count": 100,
                "product_click_count": 8,
                "orders_count": 0,
                "gross_sales": 0,
            }
        )

        self.assertEqual(plan["stage"], "detail_conversion_bottleneck")
        actions = "；".join(item["action"] for item in plan["priority_actions"])
        self.assertIn("详情页", actions)
        self.assertIn("SKU", actions)
        self.assertIn("运费", actions)
        self.assertEqual(plan["primary_metric"], "orders_count")

    def test_conversion_experiment_plan_turns_detail_audit_into_safe_experiment(self) -> None:
        plan = build_conversion_experiment_plan(
            metrics={
                "snapshot_date": "2026-06-03",
                "product_exposure_count": 23,
                "product_click_count": 2,
                "orders_count": 0,
                "net_profit_verified": False,
            },
            detail_audit={
                "stage": "detail_conversion_bottleneck",
                "page_verified": True,
                "safe_to_auto_save": False,
                "brand_gate": {"ready": True, "required_value": "无品牌"},
                "evidence_flags": [
                    "main_video_pending_save",
                    "guide_short_title_empty",
                    "important_attributes_incomplete",
                    "material_components_incomplete",
                    "spec_image_needed",
                ],
                "detail_summary": {
                    "guide_short_title_length": 0,
                    "important_attributes_filled": 4,
                    "important_attributes_total": 10,
                    "material_components_filled": 1,
                    "material_components_total": 2,
                    "spec_image_prompt_visible": True,
                },
                "sku_summary": {
                    "color_values": ["海盐蓝色", "燕麦色", "韩国灰", "淡粉色", "本白色"],
                    "size_values": ["均码"],
                    "total_stock_observed": 100,
                },
            },
            profit_plan={
                "unit_economics": {"net_profit_per_order": 2.95},
                "target_orders": {"minimum_daily_orders": 170},
                "scale_readiness": {"ready_for_paid_scale": False},
            },
        )

        self.assertEqual(plan["stage"], "detail_conversion_bottleneck")
        self.assertEqual(plan["experiment_name"], "detail_conversion_first_order")
        self.assertEqual(plan["primary_metric"], "orders_count")
        self.assertEqual(plan["baseline"]["product_click_count"], 2)
        self.assertEqual(plan["success_criteria"]["minimum_orders"], 1)
        self.assertTrue(plan["paid_ads_paused"])
        self.assertFalse(plan["safe_to_auto_apply"])
        self.assertIn("保存当前编辑页", "；".join(plan["allowed_next_actions"]))
        self.assertIn("导购短标题", "；".join(plan["experiment_tasks"]))
        self.assertIn("规格图", "；".join(plan["experiment_tasks"]))
        self.assertIn("不发布商品", "；".join(plan["safety_gates"]))

    def test_detail_conversion_audit_turns_edit_page_evidence_into_safe_actions(self) -> None:
        audit = build_detail_conversion_audit(
            metrics={
                "product_exposure_count": 20,
                "product_click_count": 1,
                "orders_count": 0,
            },
            page_snapshot={
                "product_id_in_url": True,
                "brand_text": "*品牌 无品牌",
                "title_use_brand_name_checked": False,
                "main_video_success_card": True,
                "main_video_unsaved": True,
                "guide_short_title_length": 0,
                "important_attributes_filled": 4,
                "important_attributes_total": 10,
                "material_components_filled": 1,
                "material_components_total": 2,
                "spec_image_prompt_visible": True,
                "detail_image_count": 10,
                "detail_image_capacity": 50,
                "color_values": ["海盐蓝色", "燕麦色", "韩国灰", "淡粉色", "本白色"],
                "size_values": ["均码"],
                "sku_stock_values": [20, 20, 20, 20, 20],
                "freight_template": "包邮",
                "after_sale_policy": "7天无理由退货",
                "forbidden_controls_visible": ["付款减库存", "发布商品", "保存草稿", "填写检查"],
            },
        )

        self.assertEqual(audit["stage"], "detail_conversion_bottleneck")
        self.assertFalse(audit["safe_to_auto_save"])
        self.assertTrue(audit["brand_gate"]["ready"])
        self.assertIn("main_video_pending_save", audit["evidence_flags"])
        self.assertIn("guide_short_title_empty", audit["evidence_flags"])
        self.assertIn("important_attributes_incomplete", audit["evidence_flags"])
        self.assertIn("spec_image_needed", audit["evidence_flags"])
        self.assertEqual(audit["sku_summary"]["color_count"], 5)
        self.assertEqual(audit["fulfillment_summary"]["freight_template"], "包邮")
        self.assertNotIn("付款减库存", audit["forbidden_controls_visible"])
        self.assertIn("发布商品", audit["forbidden_controls_visible"])
        self.assertIn("不自动保存", "；".join(audit["safe_next_actions"]))

    def test_detail_conversion_audit_derives_fields_from_browser_text_snapshot(self) -> None:
        body_text = (
            "商品发布 基础信息 商品类目 服装 > 内衣裤袜 > 袜子 > 中筒袜 "
            "*商品标题 60/60 使用品牌名 导购短标题 0/24 "
            "*类目属性 必填项进度 100% 材质成分 1/2 重要属性 4/10 "
            "*品牌 无品牌 厚度 请选择 图案 请选择 功能 透气 适用季节 请选择 风格 请选择 "
            "主图视频 发布优质主图视频，介绍商品卖点 "
            "*商品详情 商详图片（10/50） 支持拖拽 "
            "*商品规格 发布规格图，优化商品展示效果 "
            "*颜色分类 添加规格图 批量上传规格图 下移 上移 海盐蓝色 燕麦色 韩国灰 淡粉色 本白色 请选择/输入颜色分类 "
            "*码数 添加规格图 下移 上移 均码 请选择/输入码数 "
            "海盐蓝色 均码 ￥ 20 增 减 20 清空 "
            "燕麦色 均码 ￥ 20 增 减 20 清空 "
            "韩国灰 均码 ￥ 20 增 减 20 清空 "
            "淡粉色 均码 ￥ 20 增 减 20 清空 "
            "本白色 均码 ￥ 20 增 减 20 清空 "
            "*订单库存计数 下单减库存 付款减库存 "
            "*运费模板 包邮 *售后政策 7天无理由退货 发布商品 保存草稿 填写检查"
        )

        audit = build_detail_conversion_audit(
            metrics={
                "product_click_count": 1,
                "orders_count": 0,
            },
            page_snapshot={
                "url": "https://fxg.jinritemai.com/ffa/g/create?product_id=3811995393416364123&entrance=edit",
                "body_text": body_text,
                "brand_text": "*商品标题 60/60 使用品牌名",
                "brand_texts": ["*商品标题 60/60 使用品牌名", "*品牌 无品牌"],
                "title_use_brand_name_checked": False,
                "main_video_field": {
                    "has_success_card": True,
                    "has_video_asset_sign": True,
                    "upload_busy": False,
                },
            },
        )

        self.assertTrue(audit["page_verified"])
        self.assertTrue(audit["brand_gate"]["ready"])
        self.assertIn("main_video_pending_save", audit["evidence_flags"])
        self.assertEqual(audit["detail_summary"]["guide_short_title_length"], 0)
        self.assertEqual(audit["detail_summary"]["important_attributes_filled"], 4)
        self.assertEqual(audit["detail_summary"]["important_attributes_total"], 10)
        self.assertEqual(audit["detail_summary"]["material_components_filled"], 1)
        self.assertEqual(audit["detail_summary"]["material_components_total"], 2)
        self.assertEqual(audit["detail_summary"]["detail_image_count"], 10)
        self.assertEqual(audit["detail_summary"]["detail_image_capacity"], 50)
        self.assertEqual(audit["sku_summary"]["color_values"], ["海盐蓝色", "燕麦色", "韩国灰", "淡粉色", "本白色"])
        self.assertEqual(audit["sku_summary"]["size_values"], ["均码"])
        self.assertEqual(audit["sku_summary"]["sku_stock_values"], [20, 20, 20, 20, 20])
        self.assertEqual(audit["fulfillment_summary"]["freight_template"], "包邮")
        self.assertEqual(audit["fulfillment_summary"]["after_sale_policy"], "7天无理由退货")
        self.assertIn("发布商品", audit["forbidden_controls_visible"])
        self.assertNotIn("付款减库存", audit["forbidden_controls_visible"])

    def test_detail_conversion_audit_requires_explicit_no_brand_field_evidence(self) -> None:
        body_text = (
            "商品发布 基础信息 *商品标题 60/60 使用品牌名 "
            "*类目属性 必填项进度 100% *品牌 无品牌 "
            "主图视频 发布商品 保存草稿 填写检查"
        )

        audit = build_detail_conversion_audit(
            metrics={
                "product_click_count": 1,
                "orders_count": 0,
            },
            page_snapshot={
                "url": "https://fxg.jinritemai.com/ffa/g/create?product_id=3811995393416364123&entrance=edit",
                "body_text": body_text,
                "brand_text": "*商品标题 60/60 使用品牌名",
                "title_use_brand_name_checked": False,
                "main_video_success_card": True,
                "main_video_unsaved": True,
            },
        )

        self.assertFalse(audit["brand_gate"]["ready"])
        self.assertIn("brand_gate_not_ready", audit["evidence_flags"])

    def test_detail_improvement_suggestions_keep_no_brand_and_mark_unverified_facts(self) -> None:
        audit = build_detail_conversion_audit(
            metrics={
                "product_exposure_count": 20,
                "product_click_count": 1,
                "orders_count": 0,
            },
            page_snapshot={
                "product_id_in_url": True,
                "brand_text": "*品牌 无品牌",
                "title_use_brand_name_checked": False,
                "main_video_success_card": True,
                "main_video_unsaved": True,
                "guide_short_title_length": 0,
                "important_attributes_filled": 4,
                "important_attributes_total": 10,
                "material_components_filled": 1,
                "material_components_total": 2,
                "spec_image_prompt_visible": True,
                "detail_image_count": 10,
                "detail_image_capacity": 50,
                "color_values": ["海盐蓝色", "燕麦色", "韩国灰", "淡粉色", "本白色"],
                "size_values": ["均码"],
                "sku_stock_values": [20, 20, 20, 20, 20],
                "freight_template": "包邮",
                "after_sale_policy": "7天无理由退货",
            },
        )

        suggestions = build_detail_improvement_suggestions(
            product_title="小雏菊碎花袜子女春夏新款镂空网眼中筒袜无骨甜美木耳边堆堆袜女",
            audit=audit,
        )

        self.assertEqual(suggestions["stage"], "detail_conversion_bottleneck")
        self.assertFalse(suggestions["safe_to_auto_apply"])
        self.assertLessEqual(suggestions["guide_short_title"]["char_count"], 24)
        self.assertNotIn("品牌", suggestions["guide_short_title"]["text"])
        attribute_fields = {item["field"]: item for item in suggestions["attribute_suggestions"]}
        self.assertEqual(attribute_fields["适用季节"]["suggested_value"], "春夏")
        self.assertEqual(attribute_fields["图案"]["suggested_value"], "小雏菊/碎花")
        self.assertTrue(attribute_fields["材质成分"]["requires_manual_evidence"])
        self.assertTrue(suggestions["spec_image_brief"]["requires_sell_unit_confirmation"])
        self.assertIn("不保存", "；".join(suggestions["safety_gates"]))

    def test_conversion_asset_pack_keeps_no_brand_and_blocks_unverified_upload(self) -> None:
        audit = build_detail_conversion_audit(
            metrics={
                "product_exposure_count": 36,
                "product_click_count": 3,
                "orders_count": 0,
            },
            page_snapshot={
                "product_id_in_url": True,
                "brand_text": "*品牌 无品牌",
                "title_use_brand_name_checked": False,
                "main_video_success_card": True,
                "main_video_unsaved": True,
                "guide_short_title_length": 0,
                "important_attributes_filled": 4,
                "important_attributes_total": 10,
                "material_components_filled": 1,
                "material_components_total": 2,
                "spec_image_prompt_visible": True,
                "color_values": ["海盐蓝色", "燕麦色", "韩国灰", "淡粉色", "本白色"],
                "size_values": ["均码"],
                "freight_template": "包邮",
                "after_sale_policy": "7天无理由退货",
            },
        )

        suggestions = build_detail_improvement_suggestions(
            product_title="小雏菊碎花袜子女春夏新款镂空网眼中筒袜无骨甜美木耳边堆堆袜女",
            audit=audit,
        )
        pack = build_conversion_asset_pack(
            product={
                "action_id": 3,
                "product_id": "3811995393416364123",
                "title": "小雏菊碎花袜子女春夏新款镂空网眼中筒袜无骨甜美木耳边堆堆袜女",
                "sale_price": 20,
            },
            audit=audit,
            suggestions=suggestions,
            metrics={
                "id": 22,
                "product_exposure_count": 36,
                "product_click_count": 3,
                "orders_count": 0,
                "net_profit_verified": False,
            },
        )

        self.assertEqual(pack["plan_type"], "conversion_asset_pack")
        self.assertEqual(pack["brand_policy"]["required_value"], "无品牌")
        self.assertFalse(pack["safe_to_auto_apply"])
        self.assertFalse(pack["safe_to_auto_upload"])
        self.assertFalse(pack["draft_assets"][0]["ready_for_upload"])
        self.assertIn("海盐蓝色", "；".join(pack["copy_blocks"]["spec_image_lines"]))
        self.assertIn("均码", "；".join(pack["copy_blocks"]["spec_image_lines"]))
        public_copy = "；".join(
            line
            for asset in pack["draft_assets"]
            for line in asset["visible_lines"]
        )
        for forbidden in ("品牌", "songmu", "淞木", "KIKISOCKS"):
            self.assertNotIn(forbidden, public_copy)
        self.assertIn("材质成分", "；".join(pack["manual_evidence_required"]))
        self.assertIn("不自动上传", "；".join(pack["safety_gates"]))

    def test_ledger_persists_extended_shop_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "ops.db"
            ledger = OpsLedger(db_path)
            snapshot = ledger.save_daily_snapshot(
                {
                    "snapshot_date": "2026-06-02",
                    "net_profit": 0,
                    "net_profit_verified": False,
                    "gross_sales": 368.8,
                    "orders_count": 12,
                    "refund_amount": 9.9,
                    "after_sale_amount": 1.2,
                    "promotion_cost": 18.5,
                    "experience_score": 4.71,
                    "product_exposure_count": 51,
                    "product_click_count": 0,
                    "search_exposure_count": 251,
                    "source": "cdp_browser",
                    "status": "cdp_partial_no_net_profit",
                    "raw_payload": {"source": "cdp", "中文": "经营读数"},
                }
            )

            self.assertEqual(snapshot["orders_count"], 12)
            self.assertFalse(snapshot["net_profit_verified"])
            loaded = ledger.list_daily_snapshots(limit=1)[0]
            self.assertEqual(loaded["refund_amount"], 9.9)
            self.assertEqual(loaded["product_exposure_count"], 51)
            self.assertEqual(loaded["product_click_count"], 0)
            self.assertEqual(loaded["search_exposure_count"], 251)
            self.assertIn("经营读数", loaded["raw_payload_json"])

    def test_ledger_persists_strategy_snapshot_and_product_issue_actions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "ops.db"
            ledger = OpsLedger(db_path)
            saved = ledger.save_strategy_snapshot(
                {
                    "snapshot_date": "2026-06-02",
                    "source": "cdp_browser",
                    "status": "strategy_signals_observed",
                    "product_count": 22,
                    "excellent_product_count": 22,
                    "missing_main_video_count": 6,
                    "missing_spec_image_count": 3,
                    "missing_live_replay_count": 22,
                    "opportunity_keywords": ["女夏季薄款船袜"],
                    "refund_reasons": {"多拍/错拍/不想要": 12},
                    "product_issues": [
                        {
                            "product_id": "3819238447663677663",
                            "title": "韩系波点中筒袜防臭夏天袜子白女夏季薄款甜美蕾丝花边棉袜堆堆袜",
                            "quality_score": 90,
                            "recent_30d_sales": 7,
                            "issues": ["商品缺少主图视频或主图视频质量不合格", "商品缺少讲解回放"],
                        }
                    ],
                    "raw_payload": {"中文": "商品诊断"},
                }
            )

            self.assertGreaterEqual(saved["snapshot"]["id"], 1)
            self.assertEqual(saved["snapshot"]["missing_main_video_count"], 6)
            self.assertEqual(saved["product_issue_actions"][0]["product_id"], "3819238447663677663")
            self.assertEqual(saved["product_issue_actions"][0]["priority_rank"], 1)

            loaded_snapshots = ledger.list_strategy_snapshots(limit=1)
            self.assertEqual(loaded_snapshots[0]["opportunity_keywords"], ["女夏季薄款船袜"])
            self.assertEqual(loaded_snapshots[0]["refund_reasons"]["多拍/错拍/不想要"], 12)
            self.assertIn("商品诊断", loaded_snapshots[0]["raw_payload_json"])

            loaded_actions = ledger.list_product_issue_actions(limit=5)
            self.assertEqual(loaded_actions[0]["issues"][0], "商品缺少主图视频或主图视频质量不合格")
            self.assertEqual(loaded_actions[0]["action_status"], "open")

    def test_ledger_updates_product_issue_action_status_with_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "ops.db"
            ledger = OpsLedger(db_path)
            saved = ledger.save_strategy_snapshot(
                {
                    "snapshot_date": "2026-06-02",
                    "source": "cdp_browser",
                    "product_issues": [
                        {
                            "product_id": "3819238447663677663",
                            "title": "韩系波点中筒袜防臭夏天袜子白女夏季薄款甜美蕾丝花边棉袜堆堆袜",
                            "quality_score": 90,
                            "recent_30d_sales": 7,
                            "issues": ["商品缺少主图视频或主图视频质量不合格"],
                        }
                    ],
                }
            )
            action_id = saved["product_issue_actions"][0]["id"]

            updated = ledger.update_product_issue_action(
                action_id,
                action_status="in_progress",
                note="已定位问题商品；本地 Record 暂无匹配素材，先建立映射。",
                evidence={"page_url": "https://fxg.jinritemai.com/ffa/g/diagnose"},
            )

            self.assertEqual(updated["action_status"], "in_progress")
            self.assertIn("本地 Record 暂无匹配素材", updated["action_note"])
            self.assertEqual(updated["evidence"]["page_url"], "https://fxg.jinritemai.com/ffa/g/diagnose")

            in_progress = ledger.list_product_issue_actions(action_status="in_progress", limit=5)
            self.assertEqual(in_progress[0]["id"], action_id)
            self.assertEqual(in_progress[0]["evidence"]["page_url"], "https://fxg.jinritemai.com/ffa/g/diagnose")

            events = ledger.list_product_issue_action_events(action_id=action_id)
            self.assertEqual(events[0]["old_status"], "open")
            self.assertEqual(events[0]["new_status"], "in_progress")
            self.assertIn("已定位问题商品", events[0]["note"])

    def test_builds_product_record_mapping_without_forcing_unrelated_record(self) -> None:
        mappings = build_product_record_mappings(
            shop_products=[
                {
                    "action_id": 1,
                    "product_id": "3819238447663677663",
                    "title": "韩系波点中筒袜防臭夏天袜子白女夏季薄款甜美蕾丝花边棉袜堆堆袜",
                }
            ],
            local_records=[
                {
                    "record_id": 1,
                    "title": "女款动物图案浅口船袜春夏薄款可爱短袜单双装均码",
                    "path": "E:/Script Project/Dyin/beiufen/2.0/uploads/products/ID-638925643504",
                }
            ],
            min_confidence=0.72,
        )

        self.assertEqual(mappings[0]["match_status"], "unmatched")
        self.assertEqual(mappings[0]["record_id"], None)
        self.assertLess(mappings[0]["confidence"], 0.72)
        self.assertIn("没有达到自动匹配阈值", mappings[0]["reason"])

    def test_builds_product_record_mapping_for_close_title_match(self) -> None:
        mappings = build_product_record_mappings(
            shop_products=[
                {
                    "action_id": 2,
                    "product_id": "3811600816893198348",
                    "title": "songmu淞木 布标镂空无骨袜子女春夏新品薄款中筒袜韩系ins堆堆",
                }
            ],
            local_records=[
                {
                    "record_id": 12,
                    "title": "songmu淞木布标镂空无骨袜子女春夏新品薄款中筒袜韩系ins堆堆",
                    "path": "D:/products/songmu",
                }
            ],
            min_confidence=0.72,
        )

        self.assertEqual(mappings[0]["match_status"], "matched")
        self.assertEqual(mappings[0]["record_id"], 12)
        self.assertGreaterEqual(mappings[0]["confidence"], 0.72)

    def test_ledger_persists_product_record_mappings_utf8(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "ops.db"
            ledger = OpsLedger(db_path)
            mappings = build_product_record_mappings(
                shop_products=[
                    {
                        "action_id": 1,
                        "product_id": "3819238447663677663",
                        "title": "韩系波点中筒袜防臭夏天袜子白女夏季薄款甜美蕾丝花边棉袜堆堆袜",
                    }
                ],
                local_records=[
                    {
                        "record_id": 1,
                        "title": "女款动物图案浅口船袜春夏薄款可爱短袜单双装均码",
                        "path": "E:/Script Project/Dyin/beiufen/2.0/uploads/products/ID-638925643504",
                    }
                ],
            )

            saved = ledger.save_product_record_mappings(mappings)
            loaded = ledger.list_product_record_mappings(limit=5)

            self.assertEqual(saved[0]["match_status"], "unmatched")
            self.assertEqual(loaded[0]["product_id"], "3819238447663677663")
            self.assertEqual(loaded[0]["record_id"], None)
            self.assertIn("没有达到自动匹配阈值", loaded[0]["reason"])
            self.assertEqual(loaded[0]["evidence"]["matcher"], "normalized_title_sequence_ratio")

    def test_prioritizes_sales_product_without_trusted_material_mapping(self) -> None:
        plan = build_material_gap_plan(
            product_issue_actions=[
                {
                    "id": 1,
                    "product_id": "3819238447663677663",
                    "title": "韩系波点中筒袜防臭夏天袜子白女夏季薄款甜美蕾丝花边棉袜堆堆袜",
                    "recent_30d_sales": 7,
                    "action_status": "blocked",
                    "issues": ["商品缺少主图视频或主图视频质量不合格"],
                },
                {
                    "id": 4,
                    "product_id": "3676351545072550092",
                    "title": "无骨堆堆袜子纯棉女学院风夏季薄款白色女袜中筒袜灰色jk透气长袜",
                    "recent_30d_sales": 0,
                    "action_status": "open",
                    "issues": ["商品缺少规格图"],
                },
            ],
            product_record_mappings=[
                {
                    "id": 1,
                    "action_id": 1,
                    "product_id": "3819238447663677663",
                    "match_status": "unmatched",
                    "confidence": 0.18,
                    "reason": "没有达到自动匹配阈值 0.72，不能强行关联本地 Record",
                },
                {
                    "id": 4,
                    "action_id": 4,
                    "product_id": "3676351545072550092",
                    "match_status": "unmatched",
                    "confidence": 0.2,
                    "reason": "没有达到自动匹配阈值 0.72，不能强行关联本地 Record",
                },
            ],
        )

        self.assertEqual(plan["primary_focus"], "collect_verified_materials")
        self.assertTrue(plan["do_not_reuse_unmatched_record"])
        self.assertEqual(plan["blocked_revenue_products"][0]["action_id"], 1)
        self.assertEqual(plan["blocked_revenue_products"][0]["recent_30d_sales"], 7)
        self.assertFalse(plan["blocked_revenue_products"][0]["safe_to_optimize"])
        self.assertIn("不能强行关联本地 Record", plan["blocked_revenue_products"][0]["mapping_reason"])
        self.assertIn("main_images", plan["blocked_revenue_products"][0]["required_materials"])
        self.assertEqual(plan["open_missing_material_products"][0]["action_id"], 4)

    def test_keeps_brand_risk_products_out_of_material_reuse_queue(self) -> None:
        plan = build_material_gap_plan(
            product_issue_actions=[
                {
                    "id": 2,
                    "product_id": "3811600816893198348",
                    "title": "songmu淞木 布标镂空无骨袜子女春夏新品薄款中筒袜韩系ins堆堆",
                    "recent_30d_sales": 0,
                    "action_status": "blocked",
                    "issues": ["商品缺少主图视频或主图视频质量不合格"],
                },
                {
                    "id": 7,
                    "product_id": "3811596586392355102",
                    "title": "KIKISOCKS袜子女春夏薄款透气花边微压中筒韩系甜美少女风堆堆袜",
                    "recent_30d_sales": 0,
                    "action_status": "blocked",
                    "issues": ["商品缺少主图视频或主图视频质量不合格"],
                },
                {
                    "id": 8,
                    "product_id": "3811598443823104296",
                    "title": "袜子防臭夏天中筒袜女夏季薄款透气花边中筒韩系甜美少女风堆堆袜",
                    "recent_30d_sales": 0,
                    "action_status": "open",
                    "issues": ["商品缺少主图视频或主图视频质量不合格"],
                },
            ],
            product_record_mappings=[
                {"id": 2, "action_id": 2, "product_id": "3811600816893198348", "match_status": "unmatched"},
                {"id": 7, "action_id": 7, "product_id": "3811596586392355102", "match_status": "unmatched"},
                {"id": 8, "action_id": 8, "product_id": "3811598443823104296", "match_status": "unmatched"},
            ],
        )

        self.assertEqual([item["action_id"] for item in plan["brand_risk_products"]], [2, 7])
        self.assertEqual([item["action_id"] for item in plan["open_missing_material_products"]], [8])
        self.assertEqual(plan["brand_risk_products"][0]["required_next_action"], "只读确认品牌字段与标题来源")
        self.assertFalse(plan["brand_risk_products"][0]["safe_to_optimize"])

    def test_material_gap_plan_keeps_shop_and_ai_safety_gates(self) -> None:
        plan = build_material_gap_plan(
            product_issue_actions=[
                {
                    "id": 4,
                    "product_id": "3676351545072550092",
                    "title": "无骨堆堆袜子纯棉女学院风夏季薄款白色女袜中筒袜灰色jk透气长袜",
                    "recent_30d_sales": 0,
                    "action_status": "open",
                    "issues": ["商品缺少规格图"],
                }
            ],
            product_record_mappings=[],
        )

        self.assertIn("不保存、不发布、不投放、不付款", plan["safety_gates"])
        self.assertIn("不调用抖店官方 API", plan["safety_gates"])
        self.assertIn("不调用外部 AI 或第三方模型", plan["safety_gates"])
        self.assertIn("不强行复用未匹配的本地 Record", plan["safety_gates"])
        self.assertIn("只采集/导入/核验本地素材", plan["allowed_next_actions"])
        self.assertTrue(plan["ai_policy"]["external_ai_disabled"])

    def test_sourcing_profit_gate_rejects_low_price_single_pair_free_shipping(self) -> None:
        gate = build_sourcing_profit_gate(
            product={
                "action_id": 1,
                "product_id": "3819238447663677663",
                "title": "韩系波点中筒袜防臭夏天袜子白女夏季薄款甜美蕾丝花边棉袜堆堆袜",
                "observed_sale_price": 6.8,
                "recent_30d_sales": 7,
            },
            scenarios=[
                {
                    "scenario_id": "single_pair_free_shipping",
                    "sale_price": 6.8,
                    "pair_count": 1,
                    "shipping_cost": 3.0,
                    "packaging_cost": 0.3,
                    "platform_commission_rate": 0.05,
                    "refund_loss": 0.2,
                    "target_unit_profit": 2.0,
                    "minimum_supplier_cost_per_pair": 1.5,
                }
            ],
        )

        scenario = gate["scenarios"][0]
        self.assertEqual(gate["recommended_sourcing_mode"], "bundle_or_higher_aov_only")
        self.assertEqual(scenario["decision"], "reject_price_structure")
        self.assertEqual(scenario["max_supplier_cost_per_pair"], 0.96)
        self.assertIn("低于最低可采成本", scenario["reason"])
        self.assertFalse(gate["safe_to_purchase_stock"])

    def test_sourcing_profit_gate_accepts_bundle_only_after_verified_supplier_cost(self) -> None:
        gate = build_sourcing_profit_gate(
            product={
                "action_id": 1,
                "product_id": "3819238447663677663",
                "title": "韩系波点中筒袜防臭夏天袜子白女夏季薄款甜美蕾丝花边棉袜堆堆袜",
                "observed_sale_price": 6.8,
                "recent_30d_sales": 7,
            },
            scenarios=[
                {
                    "scenario_id": "five_pair_bundle",
                    "sale_price": 24.9,
                    "pair_count": 5,
                    "shipping_cost": 3.5,
                    "packaging_cost": 0.6,
                    "platform_commission_rate": 0.05,
                    "promotion_cost": 0.7,
                    "refund_loss": 0.5,
                    "target_unit_profit": 8.0,
                    "minimum_supplier_cost_per_pair": 1.5,
                    "supplier_cost_per_pair": 1.8,
                    "supplier_cost_verified": True,
                    "exact_material_verified": True,
                    "no_brand_verified": True,
                }
            ],
        )

        scenario = gate["scenarios"][0]
        self.assertEqual(scenario["decision"], "candidate_for_test_order")
        self.assertEqual(scenario["net_profit_per_order"], 9.35)
        self.assertEqual(scenario["daily_orders_for_500"], 54)
        self.assertTrue(scenario["supplier_cost_verified"])
        self.assertFalse(gate["safe_to_auto_purchase"])
        self.assertIn("小单测试", "；".join(gate["allowed_next_actions"]))

    def test_sourcing_profit_gate_keeps_procurement_safety_boundaries(self) -> None:
        gate = build_sourcing_profit_gate(
            product={"action_id": 1, "product_id": "3819238447663677663", "observed_sale_price": 6.8},
            scenarios=[],
        )

        self.assertIn("不调用抖店官方 API", gate["safety_gates"])
        self.assertIn("不调用外部 AI 或第三方模型", gate["safety_gates"])
        self.assertIn("不自动下单采购、不付款", gate["safety_gates"])
        self.assertIn("不保存、不发布、不投放", gate["safety_gates"])
        self.assertEqual(gate["brand_policy"]["required_value"], "无品牌")
        self.assertTrue(gate["ai_policy"]["external_ai_disabled"])

    def test_supplier_quote_plan_builds_actionable_inquiry_brief_from_profit_gate(self) -> None:
        profit_gate = build_sourcing_profit_gate(
            product={
                "action_id": 1,
                "product_id": "3819238447663677663",
                "title": "韩系波点中筒袜防臭夏天袜子白女夏季薄款甜美蕾丝花边棉袜堆堆袜",
                "observed_sale_price": 6.8,
                "recent_30d_sales": 7,
            },
            scenarios=[
                {
                    "scenario_id": "three_pair_bundle_quote_needed",
                    "sale_price": 16.9,
                    "pair_count": 3,
                    "shipping_cost": 3.5,
                    "packaging_cost": 0.5,
                    "platform_commission_rate": 0.05,
                    "promotion_cost": 0.5,
                    "refund_loss": 0.3,
                    "target_unit_profit": 5.0,
                    "minimum_supplier_cost_per_pair": 1.5,
                }
            ],
        )

        plan = build_supplier_quote_plan(
            product=profit_gate["product"],
            sourcing_profit_gate=profit_gate,
            supplier_candidates=[],
        )

        self.assertEqual(plan["product_id"], "3819238447663677663")
        self.assertEqual(plan["target_max_supplier_cost_per_pair"], 2.08)
        self.assertIn("波点", plan["required_same_style_features"])
        self.assertIn("蕾丝花边", plan["required_same_style_features"])
        self.assertIn("无品牌", plan["quote_questions"][0])
        self.assertIn("波点中筒袜 蕾丝花边 堆堆袜 防臭", plan["search_queries"][0])
        self.assertFalse(plan["safe_to_auto_purchase"])

    def test_supplier_quote_plan_rejects_partial_keyword_and_brand_risk_candidate(self) -> None:
        plan = build_supplier_quote_plan(
            product={
                "action_id": 1,
                "product_id": "3819238447663677663",
                "title": "韩系波点中筒袜防臭夏天袜子白女夏季薄款甜美蕾丝花边棉袜堆堆袜",
            },
            sourcing_profit_gate={
                "scenarios": [
                    {"scenario_id": "bundle", "max_supplier_cost_per_pair": 2.08, "decision": "needs_supplier_quote"}
                ]
            },
            supplier_candidates=[
                {
                    "candidate_id": "capture-dbd32317",
                    "title": "100%棉袜纯棉袜子女款夏薄款防脚气防臭中筒堆堆袜白色无骨月子袜",
                    "supplier_cost_per_pair": 1.6,
                    "no_brand_confirmed": False,
                    "exact_material_confirmed": False,
                    "source_brand_text": "袜觉",
                    "moq_pairs": 50,
                }
            ],
        )

        candidate = plan["candidate_evaluations"][0]
        self.assertEqual(candidate["decision"], "reject_direct_reuse")
        self.assertIn("missing_required_features", candidate["risk_flags"])
        self.assertIn("brand_risk", candidate["risk_flags"])
        self.assertTrue(candidate["cost_within_ceiling"])
        self.assertFalse(plan["has_purchase_ready_candidate"])

    def test_supplier_quote_plan_accepts_only_verified_low_moq_candidate_for_sample(self) -> None:
        plan = build_supplier_quote_plan(
            product={
                "action_id": 1,
                "product_id": "3819238447663677663",
                "title": "韩系波点中筒袜防臭夏天袜子白女夏季薄款甜美蕾丝花边棉袜堆堆袜",
            },
            sourcing_profit_gate={
                "scenarios": [
                    {"scenario_id": "bundle", "max_supplier_cost_per_pair": 2.08, "decision": "needs_supplier_quote"}
                ]
            },
            supplier_candidates=[
                {
                    "candidate_id": "supplier-a",
                    "title": "波点中筒袜女春夏薄款防臭蕾丝花边甜美堆堆袜",
                    "supplier_cost_per_pair": 1.85,
                    "shipping_cost_verified": True,
                    "no_brand_confirmed": True,
                    "exact_material_confirmed": True,
                    "material_evidence": "供应商水洗标：棉75% 聚酯纤维20% 氨纶5%",
                    "moq_pairs": 10,
                    "stock_colors": ["白色", "黑色", "粉色"],
                }
            ],
        )

        candidate = plan["candidate_evaluations"][0]
        self.assertEqual(candidate["decision"], "sample_order_candidate")
        self.assertGreaterEqual(candidate["score"], 80)
        self.assertTrue(candidate["cost_within_ceiling"])
        self.assertTrue(plan["has_purchase_ready_candidate"])
        self.assertIn("不自动下单采购、不付款", plan["safety_gates"])

    def test_supplier_quote_intake_turns_verified_quote_into_manual_sample_candidate(self) -> None:
        product = {
            "action_id": 1,
            "product_id": "3819238447663677663",
            "title": "韩系波点中筒袜防臭夏天袜子白女夏季薄款甜美蕾丝花边棉袜堆堆袜",
            "recent_30d_sales": 7,
        }
        profit_gate = build_sourcing_profit_gate(
            product=product,
            scenarios=[
                {
                    "scenario_id": "three_pair_bundle_quote_needed",
                    "sale_price": 16.9,
                    "pair_count": 3,
                    "shipping_cost": 3.5,
                    "packaging_cost": 0.5,
                    "platform_commission_rate": 0.05,
                    "promotion_cost": 0.5,
                    "refund_loss": 0.3,
                    "target_unit_profit": 5.0,
                    "minimum_supplier_cost_per_pair": 1.5,
                }
            ],
        )

        intake = build_supplier_quote_intake(
            product=product,
            sourcing_profit_gate=profit_gate,
            supplier_quote={
                "candidate_id": "supplier-a",
                "title": "波点中筒袜女春夏薄款防臭蕾丝花边甜美堆堆袜",
                "supplier_cost_per_pair": 1.85,
                "shipping_cost_verified": True,
                "no_brand_confirmed": True,
                "exact_material_confirmed": True,
                "material_evidence": "供应商水洗标：棉75% 聚酯纤维20% 氨纶5%",
                "moq_pairs": 10,
                "stock_colors": ["白色", "黑色", "粉色"],
            },
        )

        self.assertEqual(intake["decision"], "ready_for_manual_sample_order")
        self.assertTrue(intake["requires_user_confirmation"])
        self.assertFalse(intake["safe_to_auto_purchase"])
        self.assertFalse(intake["safe_to_bulk_stock"])
        self.assertEqual(intake["candidate_evaluation"]["decision"], "sample_order_candidate")
        self.assertEqual(intake["recommended_sample_order"]["max_pairs"], 10)
        self.assertEqual(intake["best_profit_projection"]["daily_orders_for_500"], 88)
        self.assertEqual(intake["best_profit_projection"]["net_profit_per_order"], 5.7)
        self.assertEqual(intake["brand_policy"]["required_value"], "无品牌")

    def test_supplier_quote_intake_rejects_brand_or_partial_same_style_risk(self) -> None:
        intake = build_supplier_quote_intake(
            product={
                "action_id": 1,
                "product_id": "3819238447663677663",
                "title": "韩系波点中筒袜防臭夏天袜子白女夏季薄款甜美蕾丝花边棉袜堆堆袜",
            },
            sourcing_profit_gate={
                "scenarios": [
                    {
                        "scenario_id": "three_pair_bundle",
                        "sale_price": 16.9,
                        "pair_count": 3,
                        "fixed_costs_before_goods": 5.15,
                        "max_supplier_cost_per_pair": 2.08,
                    }
                ]
            },
            supplier_quote={
                "candidate_id": "capture-dbd32317",
                "title": "100%棉袜纯棉袜子女款夏薄款防脚气防臭中筒堆堆袜白色无骨月子袜",
                "supplier_cost_per_pair": 1.6,
                "no_brand_confirmed": False,
                "exact_material_confirmed": False,
                "source_brand_text": "袜觉",
                "moq_pairs": 50,
            },
        )

        self.assertEqual(intake["decision"], "reject_quote")
        self.assertFalse(intake["requires_user_confirmation"])
        self.assertIn("brand_risk", intake["candidate_evaluation"]["risk_flags"])
        self.assertIn("missing_required_features", intake["candidate_evaluation"]["risk_flags"])
        self.assertFalse(intake["safe_to_auto_purchase"])

    def test_supplier_quote_intake_does_not_count_negated_feature_mentions_as_same_style(self) -> None:
        intake = build_supplier_quote_intake(
            product={
                "action_id": 19,
                "product_id": "3819238447663677663",
                "title": "韩系波点中筒袜防臭夏天袜子白女夏季薄款甜美蕾丝花边棉袜堆堆袜",
            },
            sourcing_profit_gate={
                "scenarios": [
                    {
                        "scenario_id": "three_pair_bundle",
                        "sale_price": 16.9,
                        "pair_count": 3,
                        "fixed_costs_before_goods": 5.15,
                        "max_supplier_cost_per_pair": 2.08,
                    }
                ]
            },
            supplier_quote={
                "candidate_id": "yiwubuy-957391648-2026-06-03",
                "title": "袜子女韩版卷边波点中筒袜棉袜夏季薄款百搭堆堆袜女袜子厂家批发",
                "description": "页面未确认无品牌供货、蕾丝花边、防臭/抗菌凭证、国内到手运费。",
                "supplier_cost_per_pair": 3.25,
                "no_brand_confirmed": False,
                "exact_material_confirmed": False,
                "shipping_cost_verified": False,
                "material_evidence": "页面标题含棉袜，但未给材质百分比、水洗标、吊牌或防臭/抗菌凭证",
                "moq_pairs": 10,
            },
        )

        evaluation = intake["candidate_evaluation"]
        self.assertEqual(intake["decision"], "reject_quote")
        self.assertIn("missing_required_features", evaluation["risk_flags"])
        self.assertIn("蕾丝花边", evaluation["missing_features"])
        self.assertIn("防臭", evaluation["missing_features"])
        self.assertNotIn("蕾丝花边", evaluation["matched_features"])
        self.assertNotIn("防臭", evaluation["matched_features"])

    def test_supplier_quote_plan_does_not_count_missing_evidence_phrase_as_feature(self) -> None:
        plan = build_supplier_quote_plan(
            product={
                "action_id": 19,
                "product_id": "3819238447663677663",
                "title": "韩系波点中筒袜防臭夏天袜子白女夏季薄款甜美蕾丝花边棉袜堆堆袜",
            },
            sourcing_profit_gate={
                "scenarios": [
                    {
                        "scenario_id": "three_pair_bundle",
                        "sale_price": 16.9,
                        "pair_count": 3,
                        "fixed_costs_before_goods": 5.15,
                        "max_supplier_cost_per_pair": 2.08,
                    }
                ]
            },
            supplier_candidates=[
                {
                    "candidate_id": "iyicaibao-403663-line293-zhangweichao",
                    "title": "袜子女春夏薄款二杠条纹堆堆袜ins日系学院风可爱波点卷边中筒袜",
                    "description": "列表未确认无品牌、防臭、蕾丝花边、材质成分、国内到手运费。",
                    "supplier_cost_per_pair": 4.56,
                    "no_brand_confirmed": False,
                    "exact_material_confirmed": False,
                    "shipping_cost_verified": False,
                    "material_evidence": "未提供材质百分比、水洗标、吊牌或防臭/抗菌凭证",
                    "moq_pairs": 1,
                }
            ],
        )

        evaluation = plan["candidate_evaluations"][0]
        self.assertIn("防臭", evaluation["missing_features"])
        self.assertIn("蕾丝花边", evaluation["missing_features"])
        self.assertNotIn("防臭", evaluation["matched_features"])
        self.assertNotIn("蕾丝花边", evaluation["matched_features"])

    def test_supplier_quote_plan_does_not_count_non_same_style_phrase_as_feature(self) -> None:
        plan = build_supplier_quote_plan(
            product={
                "action_id": 19,
                "product_id": "3819238447663677663",
                "title": "韩系波点中筒袜防臭夏天袜子白女夏季薄款甜美蕾丝花边棉袜堆堆袜",
            },
            sourcing_profit_gate={
                "scenarios": [
                    {
                        "scenario_id": "three_pair_bundle",
                        "sale_price": 16.9,
                        "pair_count": 3,
                        "fixed_costs_before_goods": 5.15,
                        "max_supplier_cost_per_pair": 2.08,
                    }
                ]
            },
            supplier_candidates=[
                {
                    "candidate_id": "iyicaibao-403663-line225-yangzi",
                    "title": "春然品牌7天防臭袜 展会 商场 超市特价10元模4双模式 1.4一双",
                    "description": "低价但非同款波点蕾丝花边中筒堆堆袜；1000件起批。",
                    "supplier_cost_per_pair": 1.40,
                    "no_brand_confirmed": False,
                    "exact_material_confirmed": False,
                    "shipping_cost_verified": False,
                    "material_evidence": "列表只显示全棉品质、防臭/抗菌文案，未提供水洗标、吊牌或质检凭证。",
                    "source_brand_text": "春然品牌",
                    "moq_pairs": 1000,
                }
            ],
        )

        evaluation = plan["candidate_evaluations"][0]
        self.assertIn("防臭", evaluation["matched_features"])
        self.assertIn("波点", evaluation["missing_features"])
        self.assertIn("蕾丝花边", evaluation["missing_features"])
        self.assertIn("中筒", evaluation["missing_features"])
        self.assertIn("堆堆袜", evaluation["missing_features"])

    def test_supplier_quote_plan_treats_zhongtong_as_mid_calf_synonym(self) -> None:
        plan = build_supplier_quote_plan(
            product={
                "action_id": 19,
                "product_id": "3819238447663677663",
                "title": "韩系波点中筒袜防臭夏天袜子白女夏季薄款甜美蕾丝花边棉袜堆堆袜",
            },
            sourcing_profit_gate={
                "scenarios": [
                    {
                        "scenario_id": "three_pair_bundle",
                        "sale_price": 16.9,
                        "pair_count": 3,
                        "fixed_costs_before_goods": 5.15,
                        "max_supplier_cost_per_pair": 2.08,
                    }
                ]
            },
            supplier_candidates=[
                {
                    "candidate_id": "iyicaibao-403663-line241-xinao",
                    "title": "l中统蕾丝船袜",
                    "description": "列表未确认无品牌、波点、防臭、春夏薄款、甜美韩系、材质成分、国内到手运费。",
                    "supplier_cost_per_pair": 2.00,
                    "no_brand_confirmed": False,
                    "exact_material_confirmed": False,
                    "shipping_cost_verified": False,
                    "material_evidence": "未提供材质百分比、水洗标、吊牌或防臭/抗菌凭证",
                    "moq_pairs": 600,
                }
            ],
        )

        evaluation = plan["candidate_evaluations"][0]
        self.assertIn("中筒", evaluation["matched_features"])
        self.assertIn("蕾丝花边", evaluation["matched_features"])
        self.assertIn("moq_too_high_or_missing", evaluation["risk_flags"])
        self.assertEqual(evaluation["decision"], "reject_direct_reuse")

    def test_supplier_quote_intake_keeps_procurement_and_ai_safety_boundaries(self) -> None:
        intake = build_supplier_quote_intake(
            product={"action_id": 1, "title": "波点中筒袜女春夏薄款防臭蕾丝花边甜美堆堆袜"},
            sourcing_profit_gate={
                "scenarios": [
                    {
                        "scenario_id": "three_pair_bundle",
                        "sale_price": 16.9,
                        "pair_count": 3,
                        "fixed_costs_before_goods": 5.15,
                        "max_supplier_cost_per_pair": 2.08,
                    }
                ]
            },
            supplier_quote={
                "candidate_id": "supplier-cost-high",
                "title": "波点中筒袜女春夏薄款防臭蕾丝花边甜美堆堆袜",
                "supplier_cost_per_pair": 2.5,
                "shipping_cost_verified": True,
                "no_brand_confirmed": True,
                "exact_material_confirmed": True,
                "material_evidence": "供应商水洗标：棉75% 聚酯纤维20% 氨纶5%",
                "moq_pairs": 10,
            },
        )

        self.assertEqual(intake["decision"], "needs_better_quote_or_evidence")
        self.assertIn("cost_over_or_missing", intake["candidate_evaluation"]["risk_flags"])
        self.assertTrue(intake["ai_policy"]["external_ai_disabled"])
        self.assertIn("不调用抖店官方 API", intake["safety_gates"])
        self.assertIn("不调用外部 AI 或第三方模型", intake["safety_gates"])
        self.assertIn("不自动采购、不付款、不批量备货", intake["safety_gates"])
        self.assertEqual(intake["brand_policy"]["required_value"], "无品牌")

    def test_ops_execution_queue_prioritizes_human_save_gate_before_supplier_quotes(self) -> None:
        actions = [
            {
                "id": 3,
                "product_id": "3811995393416364123",
                "title": "小雏菊碎花袜子女春夏新款镂空网眼中筒袜无骨甜美木耳边堆堆袜女",
                "action_status": "in_progress",
                "recent_30d_sales": 0,
                "issues": ["商品缺少主图视频或主图视频质量不合格"],
            },
            {
                "id": 1,
                "product_id": "3819238447663677663",
                "title": "韩系波点中筒袜防臭夏天袜子白女夏季薄款甜美蕾丝花边棉袜堆堆袜",
                "action_status": "open",
                "recent_30d_sales": 7,
                "issues": ["商品缺少主图视频或主图视频质量不合格"],
            },
        ]
        material_gap_plan = build_material_gap_plan(actions, [])
        supplier_quote_plan = {
            "plan_type": "supplier_quote_plan",
            "action_id": 1,
            "product_id": "3819238447663677663",
            "target_max_supplier_cost_per_pair": 2.08,
            "has_purchase_ready_candidate": False,
        }

        queue = build_ops_execution_queue(
            metrics={
                "snapshot_date": "2026-06-03",
                "product_exposure_count": 23,
                "product_click_count": 2,
                "orders_count": 0,
                "net_profit": 0,
                "net_profit_verified": False,
                "promotion_cost": 0,
            },
            product_issue_actions=actions,
            material_gap_plan=material_gap_plan,
            supplier_quote_plan=supplier_quote_plan,
        )

        self.assertEqual(queue["current_stage"], "detail_conversion_bottleneck")
        self.assertEqual(queue["goal_status"], "not_verified")
        self.assertTrue(queue["paid_ads_paused"])
        self.assertEqual(queue["primary_queue"][0]["task_id"], "request_human_save_confirmation_action_3")
        self.assertEqual(queue["primary_queue"][0]["action_id"], 3)
        self.assertTrue(queue["primary_queue"][0]["requires_user_confirmation"])
        self.assertFalse(queue["primary_queue"][0]["safe_to_auto_apply"])
        self.assertEqual(queue["primary_queue"][1]["task_id"], "collect_supplier_quotes_action_1")
        self.assertEqual(queue["primary_queue"][1]["target_max_supplier_cost_per_pair"], 2.08)
        self.assertTrue(queue["primary_queue"][1]["requires_supplier_evidence"])

    def test_ops_execution_queue_keeps_brand_risks_readonly_and_open_materials_collect_only(self) -> None:
        actions = [
            {
                "id": 2,
                "product_id": "3811600816893198348",
                "title": "songmu淞木 布标镂空无骨袜子女春夏新品薄款中筒袜",
                "action_status": "open",
                "recent_30d_sales": 5,
                "issues": ["商品缺少规格图"],
            },
            {
                "id": 7,
                "product_id": "3811596586392355102",
                "title": "KIKISOCKS袜子女春夏薄款透气花边微压中筒韩系甜美少女风",
                "action_status": "open",
                "recent_30d_sales": 0,
                "issues": ["商品缺少主图视频或主图视频质量不合格"],
            },
            {
                "id": 4,
                "product_id": "3810000000000000004",
                "title": "无骨堆堆袜子纯棉女学院风夏季薄款白色女袜中筒袜灰色jk透气长袜",
                "action_status": "open",
                "recent_30d_sales": 0,
                "issues": ["商品缺少主图视频或主图视频质量不合格"],
            },
        ]
        material_gap_plan = build_material_gap_plan(actions, [])

        queue = build_ops_execution_queue(
            metrics={
                "product_exposure_count": 23,
                "product_click_count": 2,
                "orders_count": 0,
                "net_profit_verified": False,
            },
            product_issue_actions=actions,
            material_gap_plan=material_gap_plan,
        )

        brand_task = next(item for item in queue["primary_queue"] if item["task_type"] == "readonly_brand_risk_check")
        material_task = next(item for item in queue["primary_queue"] if item["task_type"] == "collect_missing_materials")
        self.assertEqual(brand_task["action_ids"], [2, 7])
        self.assertEqual(brand_task["allowed_mode"], "readonly_only")
        self.assertFalse(brand_task["safe_to_auto_apply"])
        self.assertIn("只读确认", brand_task["allowed_next_action"])
        self.assertEqual(material_task["action_ids"], [4])
        self.assertEqual(material_task["allowed_mode"], "collect_local_materials_only")
        self.assertFalse(material_task["safe_to_auto_apply"])

    def test_ops_execution_queue_exposes_no_brand_and_external_ai_safety_gates(self) -> None:
        queue = build_ops_execution_queue(
            metrics={
                "net_profit": 0,
                "net_profit_verified": False,
                "orders_count": 0,
                "product_click_count": 0,
                "product_exposure_count": 0,
            },
            product_issue_actions=[],
        )

        self.assertEqual(queue["brand_policy"]["required_value"], "无品牌")
        self.assertFalse(queue["brand_policy"]["title_use_brand_name_required"])
        self.assertTrue(queue["ai_policy"]["external_ai_disabled"])
        self.assertIn("不调用抖店官方 API", queue["safety_gates"])
        self.assertIn("不调用外部 AI 或第三方模型", queue["safety_gates"])
        self.assertIn("品牌字段统一无品牌，标题不写品牌词", queue["safety_gates"])
        self.assertIn("不自动保存、不发布、不投放、不付款", queue["safety_gates"])

    def test_portfolio_path_to_500_prioritizes_action3_but_keeps_goal_unverified(self) -> None:
        plan = build_portfolio_path_to_500(
            metrics={
                "id": 22,
                "snapshot_date": "2026-06-03",
                "net_profit": 0,
                "net_profit_verified": False,
                "orders_count": 0,
                "product_exposure_count": 36,
                "product_click_count": 3,
                "search_exposure_count": 255,
                "promotion_cost": 0,
            },
            product_issue_actions=[
                {
                    "id": 3,
                    "product_id": "3811995393416364123",
                    "title": "小雏菊碎花袜子女春夏新款镂空网眼中筒袜无骨甜美木耳边堆堆袜女",
                    "recent_30d_sales": 1,
                    "action_status": "in_progress",
                    "evidence": {
                        "save_edit_human_gate": {
                            "ready_for_human_save_confirmation": True,
                            "safe_to_auto_save": False,
                        },
                        "profit_ladder_to_500": {
                            "best_case_minimum_daily_orders": 36,
                            "ready_for_paid_scale": False,
                        },
                        "conversion_asset_pack": {
                            "brand_policy": "无品牌",
                            "safe_to_auto_upload": False,
                        },
                    },
                },
                {
                    "id": 1,
                    "product_id": "3819238447663677663",
                    "title": "韩系波点中筒袜防臭夏天袜子白女夏季薄款甜美蕾丝花边棉袜堆堆袜",
                    "recent_30d_sales": 7,
                    "action_status": "blocked",
                    "action_note": "当前仍未找到可信本地Record/素材映射",
                },
            ],
        )

        self.assertEqual(plan["plan_type"], "portfolio_path_to_500")
        self.assertEqual(plan["goal_status"], "not_achieved")
        self.assertTrue(plan["paid_ads_paused"])
        self.assertFalse(plan["safe_to_auto_apply"])
        self.assertEqual(plan["portfolio_lanes"][0]["action_id"], 3)
        self.assertEqual(plan["portfolio_lanes"][0]["readiness"], "needs_human_save_confirmation")
        self.assertEqual(plan["portfolio_lanes"][0]["solo_daily_orders_for_500"], 36)
        self.assertFalse(plan["portfolio_lanes"][0]["ready_for_paid_scale"])
        self.assertEqual(plan["next_control_point"]["safety_gate"], "ops_save_edit_human_gate")
        self.assertIn("等待用户确认保存当前编辑页", plan["blockers"])
        self.assertEqual(plan["brand_policy"]["required_value"], "无品牌")
        self.assertTrue(plan["ai_policy"]["external_ai_disabled"])

    def test_portfolio_path_to_500_excludes_unverified_brand_and_material_lanes_from_scale(self) -> None:
        plan = build_portfolio_path_to_500(
            metrics={
                "net_profit": 0,
                "net_profit_verified": False,
                "orders_count": 0,
                "product_click_count": 0,
                "product_exposure_count": 0,
            },
            product_issue_actions=[
                {
                    "id": 1,
                    "product_id": "3819238447663677663",
                    "title": "韩系波点中筒袜防臭夏天袜子白女夏季薄款甜美蕾丝花边棉袜堆堆袜",
                    "recent_30d_sales": 7,
                    "action_status": "blocked",
                    "action_note": "未找到可信本地Record/素材映射",
                },
                {
                    "id": 7,
                    "product_id": "3811596586392355102",
                    "title": "KIKISOCKS袜子女春夏薄款透气花边微压中筒韩系甜美少女风堆堆袜",
                    "recent_30d_sales": 0,
                    "action_status": "blocked",
                    "action_note": "品牌残留风险",
                },
                {
                    "id": 8,
                    "product_id": "3811598443823104296",
                    "title": "袜子防臭夏天中筒袜女夏季薄款透气花边中筒韩系甜美少女风堆堆袜",
                    "recent_30d_sales": 0,
                    "action_status": "open",
                },
            ],
        )

        readiness_by_action = {lane["action_id"]: lane["readiness"] for lane in plan["portfolio_lanes"]}
        self.assertEqual(readiness_by_action[1], "needs_supplier_and_material_evidence")
        self.assertEqual(readiness_by_action[7], "readonly_brand_risk_check")
        self.assertEqual(readiness_by_action[8], "needs_material_collection")
        self.assertEqual(plan["validated_scale_lane_count"], 0)
        self.assertFalse(plan["ready_for_paid_scale"])
        self.assertIn("不自动采购、不批量备货", plan["safety_gates"])

    def test_first_order_decision_matrix_waits_for_human_save_before_reading_outcome(self) -> None:
        matrix = build_first_order_decision_matrix(
            baseline_metrics={
                "id": 22,
                "product_exposure_count": 36,
                "product_click_count": 3,
                "orders_count": 0,
                "net_profit_verified": False,
            },
            current_metrics={
                "product_exposure_count": 36,
                "product_click_count": 3,
                "orders_count": 0,
                "net_profit_verified": False,
            },
            action={
                "id": 3,
                "product_id": "3811995393416364123",
                "title": "小雏菊碎花袜子女春夏新款镂空网眼中筒袜无骨甜美木耳边堆堆袜女",
            },
            save_gate={
                "ready_for_human_save_confirmation": True,
                "safe_to_auto_save": False,
            },
            saved_confirmed=False,
        )

        self.assertEqual(matrix["plan_type"], "first_order_decision_matrix")
        self.assertEqual(matrix["precondition_status"], "awaiting_human_save_confirmation")
        self.assertEqual(matrix["decision"], "wait_for_human_save")
        self.assertFalse(matrix["safe_to_auto_save"])
        self.assertTrue(matrix["requires_user_confirmation_before_save"])
        self.assertIn("等待用户确认保存当前编辑页", matrix["next_actions"])
        self.assertEqual(matrix["brand_policy"]["required_value"], "无品牌")
        self.assertTrue(matrix["ai_policy"]["external_ai_disabled"])

    def test_first_order_decision_matrix_keeps_paid_ads_paused_when_clicks_increase_without_orders(self) -> None:
        matrix = build_first_order_decision_matrix(
            baseline_metrics={
                "id": 22,
                "product_exposure_count": 36,
                "product_click_count": 3,
                "orders_count": 0,
                "net_profit_verified": False,
            },
            current_metrics={
                "id": 23,
                "product_exposure_count": 80,
                "product_click_count": 8,
                "orders_count": 0,
                "net_profit": 0,
                "net_profit_verified": False,
            },
            action={"id": 3, "product_id": "3811995393416364123", "title": "小雏菊碎花袜子女"},
            save_gate={"ready_for_human_save_confirmation": True, "safe_to_auto_save": False},
            saved_confirmed=True,
        )

        self.assertEqual(matrix["precondition_status"], "save_confirmed_by_human")
        self.assertEqual(matrix["decision"], "conversion_bottleneck_after_save")
        self.assertTrue(matrix["paid_ads_paused"])
        self.assertFalse(matrix["ready_for_paid_scale"])
        self.assertEqual(matrix["delta"]["product_click_count"], 5)
        self.assertIn("复核详情页前半段、SKU、售价、运费和售后承诺", "；".join(matrix["next_actions"]))
        self.assertIn("订单仍为0，不能进入付费放量", matrix["blockers"])

    def test_first_order_decision_matrix_requires_profit_validation_after_first_order(self) -> None:
        matrix = build_first_order_decision_matrix(
            baseline_metrics={
                "product_exposure_count": 36,
                "product_click_count": 3,
                "orders_count": 0,
                "net_profit_verified": False,
            },
            current_metrics={
                "product_exposure_count": 92,
                "product_click_count": 9,
                "orders_count": 1,
                "net_profit": 0,
                "net_profit_verified": False,
            },
            action={"id": 3, "product_id": "3811995393416364123"},
            save_gate={"ready_for_human_save_confirmation": True, "safe_to_auto_save": False},
            saved_confirmed=True,
        )

        self.assertEqual(matrix["decision"], "profit_validation_required")
        self.assertTrue(matrix["requires_profit_validation"])
        self.assertFalse(matrix["ready_for_paid_scale"])
        self.assertIn("同步订单明细、成本、运费、佣金、推广费、退款和售后损失", "；".join(matrix["next_actions"]))
        self.assertIn("net_profit_verified=true 后才允许评估放量", matrix["blockers"])

    def test_post_save_conversion_monitor_waits_for_human_save_before_tracking_orders(self) -> None:
        monitor = build_post_save_conversion_monitor(
            metrics={
                "id": 21,
                "snapshot_date": "2026-06-03",
                "product_exposure_count": 24,
                "product_click_count": 2,
                "orders_count": 0,
                "net_profit": 0,
                "net_profit_verified": False,
                "promotion_cost": 0,
            },
            action={
                "id": 3,
                "product_id": "3811995393416364123",
                "title": "小雏菊碎花袜子女春夏新款镂空网眼中筒袜无骨甜美木耳边堆堆袜女",
                "action_status": "in_progress",
            },
            save_gate={
                "ready_for_human_save_confirmation": True,
                "safe_to_auto_save": False,
                "requires_human_confirmation": True,
                "allowed_next_action": "human_confirm_save_current_edit_page",
            },
        )

        self.assertEqual(monitor["plan_type"], "post_save_conversion_monitor")
        self.assertEqual(monitor["stage"], "detail_conversion_bottleneck")
        self.assertEqual(monitor["action_id"], 3)
        self.assertEqual(monitor["product_id"], "3811995393416364123")
        self.assertEqual(monitor["pre_save_status"], "awaiting_human_save_confirmation")
        self.assertTrue(monitor["requires_user_confirmation_before_save"])
        self.assertFalse(monitor["safe_to_auto_save"])
        self.assertTrue(monitor["paid_ads_paused"])
        self.assertEqual(monitor["baseline"]["snapshot_id"], 21)
        self.assertEqual(monitor["baseline"]["product_exposure_count"], 24)
        self.assertEqual(monitor["baseline"]["product_click_count"], 2)
        self.assertEqual(monitor["baseline"]["orders_count"], 0)
        self.assertFalse(monitor["baseline"]["net_profit_verified"])
        self.assertEqual(monitor["checkpoints"][0]["checkpoint"], "immediate_after_save")
        self.assertIn("orders_count", monitor["next_snapshot_metrics"])

    def test_post_save_conversion_monitor_keeps_profit_validation_blocked_until_net_profit_verified(self) -> None:
        monitor = build_post_save_conversion_monitor(
            metrics={
                "snapshot_date": "2026-06-03",
                "product_exposure_count": 30,
                "product_click_count": 4,
                "orders_count": 1,
                "net_profit": 0,
                "net_profit_verified": False,
                "promotion_cost": 0,
            },
            action={
                "id": 3,
                "product_id": "3811995393416364123",
                "title": "小雏菊碎花袜子女春夏新款镂空网眼中筒袜无骨甜美木耳边堆堆袜女",
            },
            save_gate={"ready_for_human_save_confirmation": False, "safe_to_auto_save": False},
            saved_confirmed=True,
        )

        self.assertEqual(monitor["stage"], "profit_validation")
        self.assertEqual(monitor["pre_save_status"], "save_confirmed_by_human")
        self.assertTrue(monitor["requires_profit_validation"])
        self.assertFalse(monitor["ready_for_paid_scale"])
        self.assertTrue(monitor["paid_ads_paused"])
        self.assertIn("同步订单明细、成本、运费、佣金、推广费、退款和售后损失", monitor["decision_rules"][0]["then"])
        self.assertIn("net_profit_verified=true 后才允许评估放量", monitor["blockers"])

    def test_post_save_conversion_monitor_preserves_no_brand_and_external_ai_safety_policy(self) -> None:
        monitor = build_post_save_conversion_monitor(
            metrics={
                "net_profit": 0,
                "net_profit_verified": False,
                "orders_count": 0,
                "product_click_count": 2,
                "product_exposure_count": 24,
            },
            action={"id": 3, "product_id": "3811995393416364123", "title": "小雏菊碎花袜子女"},
        )

        self.assertEqual(monitor["brand_policy"]["required_value"], "无品牌")
        self.assertFalse(monitor["brand_policy"]["title_use_brand_name_required"])
        self.assertTrue(monitor["ai_policy"]["external_ai_disabled"])
        self.assertIn("不调用抖店官方 API", monitor["safety_gates"])
        self.assertIn("不调用外部 AI 或第三方模型", monitor["safety_gates"])
        self.assertIn("品牌字段统一无品牌，标题不写品牌词", monitor["safety_gates"])
        self.assertIn("不自动保存、不发布、不投放、不付款", monitor["safety_gates"])

    def test_post_save_conversion_monitor_uses_save_gate_from_action_evidence(self) -> None:
        monitor = build_post_save_conversion_monitor(
            metrics={
                "product_exposure_count": 24,
                "product_click_count": 2,
                "orders_count": 0,
                "net_profit_verified": False,
            },
            action={
                "id": 3,
                "product_id": "3811995393416364123",
                "evidence": {
                    "save_edit_human_gate": {
                        "ready_for_human_save_confirmation": True,
                        "safe_to_auto_save": False,
                    }
                },
            },
        )

        self.assertEqual(monitor["pre_save_status"], "awaiting_human_save_confirmation")
        self.assertIn("等待用户确认保存当前编辑页", monitor["blockers"])

    def test_default_ledger_path_does_not_depend_on_cwd(self) -> None:
        old_cwd = Path.cwd()
        saved_env = {
            key: os.environ.get(key)
            for key in ("DOUYIN_DATA_DIR", "DOUYIN_RESOURCE_DIR", "DOUYIN_RUNTIME_ROOT")
        }
        try:
            for key in saved_env:
                os.environ.pop(key, None)
            os.chdir(PROJECT_ROOT / "tauri-app" / "python-sidecar")

            self.assertEqual(resolve_ops_ledger_path().resolve(), (PROJECT_ROOT / "ops_ledger.db").resolve())
        finally:
            os.chdir(old_cwd)
            for key, value in saved_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


class OpsEngineProductCandidateTest(unittest.TestCase):
    def test_apply_candidate_pricing_preserves_goods_cost(self) -> None:
        original_skus = [
            {"name": "动物白 / 均码", "path": "a.jpg", "price": 2.0},
            {"name": "动物粉 / 均码", "path": "b.jpg", "price": 2.0, "ops_goods_cost": 1.8},
        ]

        result = apply_candidate_pricing_to_skus(original_skus, sale_price=8.9)

        self.assertEqual(result["updated_count"], 2)
        self.assertEqual(result["skus"][0]["price"], 8.9)
        self.assertEqual(result["skus"][0]["ops_goods_cost"], 2.0)
        self.assertEqual(result["skus"][1]["ops_goods_cost"], 1.8)
        self.assertEqual(original_skus[0]["price"], 2.0)
        self.assertEqual(extract_sku_goods_costs(result["skus"]), [2.0, 1.8])

    def test_builds_candidate_from_sku_costs_and_recommended_sale_price(self) -> None:
        candidate = build_product_candidate(
            ProductCandidateInput(
                record_id=1,
                title="袜子女短袜韩国可爱日系春夏浅口船袜",
                sku_prices=[2.0, 2.0, 2.0],
                shipping_cost=3.0,
                packaging_cost=0.5,
                platform_commission_rate=0.05,
                target_net_margin=0.30,
            )
        )

        self.assertEqual(candidate["record_id"], 1)
        self.assertEqual(candidate["sku_count"], 3)
        self.assertEqual(candidate["goods_cost_source"], "sku_price_median")
        self.assertEqual(candidate["goods_cost"], 2.0)
        self.assertEqual(candidate["recommended_sale_price"], 8.9)
        self.assertEqual(candidate["evaluation"]["decision"], "test_launch")
        self.assertEqual(candidate["evaluation"]["target_daily_orders"], 170)
        self.assertEqual(candidate["stock_plan"]["total_recommended_stock"], 6)
        self.assertIn("当前 SKU 价格像拿货成本", "；".join(candidate["warnings"]))

    def test_candidate_uses_goods_costs_without_price_warning_after_pricing_is_applied(self) -> None:
        candidate = build_product_candidate(
            ProductCandidateInput(
                record_id=1,
                title="袜子女短袜韩国可爱日系春夏浅口船袜",
                sku_prices=[2.0, 2.0, 2.0],
                current_sku_prices=[8.9, 8.9, 8.9],
                shipping_cost=3.0,
                packaging_cost=0.5,
                platform_commission_rate=0.05,
                target_net_margin=0.30,
            )
        )

        self.assertEqual(candidate["goods_cost"], 2.0)
        self.assertEqual(candidate["recommended_sale_price"], 8.9)
        self.assertEqual(candidate["sku_price_min"], 8.9)
        self.assertEqual(candidate["sku_price_max"], 8.9)
        self.assertNotIn("当前 SKU 价格像拿货成本", "；".join(candidate["warnings"]))

    def test_sorts_candidates_by_lower_target_orders_first(self) -> None:
        candidates = build_product_candidate_list(
            [
                ProductCandidateInput(
                    record_id=1,
                    title="低利润款",
                    sku_prices=[4.0],
                    shipping_cost=3.0,
                    packaging_cost=0.5,
                    platform_commission_rate=0.05,
                    target_net_margin=0.30,
                ),
                ProductCandidateInput(
                    record_id=2,
                    title="高利润款",
                    sku_prices=[2.0],
                    shipping_cost=3.0,
                    packaging_cost=0.5,
                    platform_commission_rate=0.05,
                    target_net_margin=0.45,
                ),
            ]
        )

        self.assertEqual([item["record_id"] for item in candidates], [2, 1])

    def test_daily_review_combines_verified_metrics_and_top_candidate_actions(self) -> None:
        candidate = build_product_candidate(
            ProductCandidateInput(
                record_id=1,
                title="袜子女短袜韩国可爱日系春夏浅口船袜",
                sku_prices=[2.0] * 10,
                shipping_cost=3.0,
                packaging_cost=0.5,
                platform_commission_rate=0.05,
                target_net_margin=0.30,
            )
        )

        review = build_daily_review(
            metrics={
                "snapshot_date": "2026-06-02",
                "gross_sales": 0,
                "orders_count": 0,
                "promotion_cost": 0,
                "net_profit_verified": False,
            },
            candidates=[candidate],
        )

        self.assertEqual(review["goal_status"], "not_verified")
        self.assertFalse(review["verified_net_profit_achieved"])
        self.assertEqual(review["top_candidate"]["record_id"], 1)
        self.assertIn("market_context", review)
        self.assertEqual(review["market_context"]["brand_policy"], "no_brand_only_without_qualification")
        actions = "；".join(review["actions"])
        self.assertIn("建议售价 8.9 元", actions)
        self.assertIn("试卖备货 20 件", actions)
        self.assertIn("170 单", actions)


if __name__ == "__main__":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    unittest.main()

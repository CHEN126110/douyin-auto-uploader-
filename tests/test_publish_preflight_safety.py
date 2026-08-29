# -*- coding: utf-8 -*-

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.ops_engine import (  # noqa: E402
    build_main_video_upload_stop_gate,
    build_publish_preflight_evidence,
    build_publish_preflight_safety,
    build_save_edit_human_gate,
)


class PublishPreflightSafetyTest(unittest.TestCase):
    def test_blocks_when_page_is_not_expected_product_or_brand_is_unsafe(self) -> None:
        result = build_publish_preflight_safety(
            page_snapshot={
                "url": "https://fxg.jinritemai.com/ffa/g/create",
                "title": "抖店",
                "brand_text": "品牌 songmu淞木",
                "title_use_brand_name_checked": True,
                "visible_fields": [{"field_id": "商品标题", "text": "普通标题"}],
            },
            expected_product_id="3811995393416364123",
            expected_title="小雏菊碎花袜子女春夏新款镂空网眼中筒袜无骨甜美木耳边堆堆袜女",
            candidate_video_path="E:/missing/candidate-main-video.mp4",
        )

        self.assertFalse(result["ready_for_upload_preflight"])
        blocker_codes = {item["code"] for item in result["blockers"]}
        self.assertIn("not_expected_product_page", blocker_codes)
        self.assertIn("brand_not_confirmed_no_brand", blocker_codes)
        self.assertIn("title_use_brand_name_enabled", blocker_codes)
        self.assertIn("candidate_video_missing", blocker_codes)
        self.assertFalse(result["safe_to_save_or_publish"])

    def test_blocks_when_no_brand_only_appears_in_body_text_without_brand_field_evidence(self) -> None:
        result = build_publish_preflight_safety(
            page_snapshot={
                "url": "https://fxg.jinritemai.com/ffa/g/create?product_id=3811995393416364123&entrance=edit",
                "title": "抖店",
                "body_text": "*商品标题 60/60 使用品牌名 *类目属性 *品牌 无品牌",
                "brand_text": "*商品标题 60/60 使用品牌名",
                "title_use_brand_name_checked": False,
                "title_values": [
                    "小雏菊碎花袜子女春夏新款镂空网眼中筒袜无骨甜美木耳边堆堆袜女"
                ],
            },
            expected_product_id="3811995393416364123",
            expected_title="小雏菊碎花袜子女春夏新款镂空网眼中筒袜无骨甜美木耳边堆堆袜女",
        )

        self.assertFalse(result["ready_for_upload_preflight"])
        self.assertIn("brand_not_confirmed_no_brand", {item["code"] for item in result["blockers"]})

    def test_allows_only_upload_preflight_when_safety_evidence_is_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            video_path = Path(tmp_dir) / "candidate-main-video.mp4"
            video_path.write_bytes(b"fake-video")

            result = build_publish_preflight_safety(
                page_snapshot={
                    "url": "https://fxg.jinritemai.com/ffa/g/create?product_id=3811995393416364123&entrance=edit",
                    "title": "抖店",
                    "brand_text": "*品牌 无品牌",
                    "title_use_brand_name_checked": False,
                    "title_values": [
                        "小雏菊碎花袜子女春夏新款镂空网眼中筒袜无骨甜美木耳边堆堆袜女"
                    ],
                    "visible_controls": [
                        {"text": "保存"},
                        {"text": "发布商品"},
                        {"text": "保存草稿"},
                    ],
                },
                expected_product_id="3811995393416364123",
                expected_title="小雏菊碎花袜子女春夏新款镂空网眼中筒袜无骨甜美木耳边堆堆袜女",
                candidate_video_path=str(video_path),
            )

        self.assertTrue(result["ready_for_upload_preflight"])
        self.assertFalse(result["safe_to_save_or_publish"])
        self.assertEqual(result["blockers"], [])
        self.assertIn("保存", result["risky_controls_visible"])
        self.assertIn("发布商品", result["risky_controls_visible"])
        self.assertIn("无品牌", result["brand_policy"]["required_value"])

    def test_blocks_visible_interfering_overlay_before_upload_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            video_path = Path(tmp_dir) / "candidate-main-video.mp4"
            video_path.write_bytes(b"fake-video")

            result = build_publish_preflight_safety(
                page_snapshot={
                    "url": "https://fxg.jinritemai.com/ffa/g/create?product_id=3811995393416364123&entrance=edit",
                    "title": "抖店",
                    "brand_text": "*品牌 无品牌",
                    "title_use_brand_name_checked": False,
                    "title_values": [
                        "小雏菊碎花袜子女春夏新款镂空网眼中筒袜无骨甜美木耳边堆堆袜女"
                    ],
                    "visible_overlays": [
                        {"text": "模板功能上线啦！存储模板下次发品直接用 知道了"}
                    ],
                },
                expected_product_id="3811995393416364123",
                expected_title="小雏菊碎花袜子女春夏新款镂空网眼中筒袜无骨甜美木耳边堆堆袜女",
                candidate_video_path=str(video_path),
            )

        self.assertFalse(result["ready_for_upload_preflight"])
        self.assertIn("interfering_overlay_visible", {item["code"] for item in result["blockers"]})

    def test_main_video_upload_gate_allows_only_media_upload_after_no_brand_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            video_path = Path(tmp_dir) / "candidate-main-video.mp4"
            video_path.write_bytes(b"fake-video")
            preflight = build_publish_preflight_safety(
                page_snapshot={
                    "url": "https://fxg.jinritemai.com/ffa/g/create?product_id=3811995393416364123&entrance=edit",
                    "title": "抖店",
                    "brand_text": "*品牌 无品牌",
                    "title_use_brand_name_checked": False,
                    "title_values": [
                        "小雏菊碎花袜子女春夏新款镂空网眼中筒袜无骨甜美木耳边堆堆袜女"
                    ],
                },
                expected_product_id="3811995393416364123",
                expected_title="小雏菊碎花袜子女春夏新款镂空网眼中筒袜无骨甜美木耳边堆堆袜女",
                candidate_video_path=str(video_path),
            )

        gate = build_main_video_upload_stop_gate(preflight)

        self.assertTrue(gate["ready_to_attempt_upload"])
        self.assertEqual(gate["allowed_platform_mutation"], "main_video_upload_only")
        self.assertFalse(gate["save_publish_performed"])
        self.assertTrue(gate["no_save"])
        self.assertTrue(gate["no_publish"])
        self.assertEqual(gate["brand_policy"]["required_value"], "无品牌")

    def test_main_video_upload_gate_blocks_any_branded_preflight_policy(self) -> None:
        preflight = {
            "ready_for_upload_preflight": True,
            "safe_to_save_or_publish": False,
            "candidate_video_path": "E:/video.mp4",
            "candidate_video_exists": True,
            "brand_policy": {
                "required_value": "songmu淞木",
                "title_use_brand_name_required": True,
            },
        }

        gate = build_main_video_upload_stop_gate(preflight)

        self.assertFalse(gate["ready_to_attempt_upload"])
        self.assertIn("brand_policy_not_no_brand", {item["code"] for item in gate["blockers"]})

    def test_main_video_upload_gate_blocks_when_save_publish_gate_is_not_locked(self) -> None:
        preflight = {
            "ready_for_upload_preflight": True,
            "safe_to_save_or_publish": True,
            "candidate_video_path": "E:/video.mp4",
            "candidate_video_exists": True,
            "brand_policy": {
                "required_value": "无品牌",
                "title_use_brand_name_required": False,
            },
        }

        gate = build_main_video_upload_stop_gate(preflight)

        self.assertFalse(gate["ready_to_attempt_upload"])
        self.assertIn("save_publish_gate_not_locked", {item["code"] for item in gate["blockers"]})

    def test_publish_preflight_evidence_preserves_existing_video_upload_mutation(self) -> None:
        existing = {
            "mutation_type": "main_video_upload_only",
            "shop_mutation": True,
            "upload_result": {
                "upload_triggered": True,
                "upload_confirmed": True,
            },
            "no_save": True,
            "no_publish": True,
            "no_ad_or_payment": True,
        }
        preflight = {
            "ready_for_upload_preflight": True,
            "safe_to_save_or_publish": False,
            "brand_policy": {
                "required_value": "无品牌",
                "title_use_brand_name_required": False,
            },
        }

        evidence = build_publish_preflight_evidence(
            preflight,
            record={"record_id": 1},
            issue_action={"id": 3, "evidence": {"old": "nested"}},
            existing_evidence=existing,
        )

        self.assertEqual(evidence["mutation_type"], "main_video_upload_only")
        self.assertTrue(evidence["shop_mutation"])
        self.assertTrue(evidence["upload_result"]["upload_triggered"])
        self.assertEqual(evidence["latest_preflight"], preflight)
        self.assertNotIn("evidence", evidence["issue_action"])

    def test_save_edit_human_gate_requires_confirmed_video_upload_and_no_brand_preflight(self) -> None:
        preflight = {
            "ready_for_upload_preflight": True,
            "safe_to_save_or_publish": False,
            "brand_policy": {
                "required_value": "无品牌",
                "title_use_brand_name_required": False,
            },
        }
        upload_evidence = {
            "mutation_type": "main_video_upload_only",
            "upload_result": {
                "upload_triggered": True,
                "upload_confirmed": True,
            },
            "no_save": True,
            "no_publish": True,
            "no_ad_or_payment": True,
        }
        page_snapshot = {
            "url": "https://fxg.jinritemai.com/ffa/g/create?product_id=3811995393416364123&entrance=edit",
            "title": "抖店",
            "main_video_field": {
                "exists": True,
                "has_success_card": True,
                "upload_busy": False,
            },
        }

        gate = build_save_edit_human_gate(preflight, upload_evidence=upload_evidence, page_snapshot=page_snapshot)

        self.assertTrue(gate["ready_for_human_save_confirmation"])
        self.assertFalse(gate["safe_to_auto_save"])
        self.assertTrue(gate["requires_human_confirmation"])
        self.assertEqual(gate["allowed_next_action"], "human_confirm_save_current_edit_page")
        self.assertTrue(gate["no_publish"])
        self.assertTrue(gate["no_ad_or_payment"])

    def test_save_edit_human_gate_blocks_without_video_success_card(self) -> None:
        preflight = {
            "ready_for_upload_preflight": True,
            "safe_to_save_or_publish": False,
            "brand_policy": {
                "required_value": "无品牌",
                "title_use_brand_name_required": False,
            },
        }
        upload_evidence = {
            "mutation_type": "main_video_upload_only",
            "upload_result": {
                "upload_triggered": True,
                "upload_confirmed": True,
            },
        }

        gate = build_save_edit_human_gate(
            preflight,
            upload_evidence=upload_evidence,
            page_snapshot={"main_video_field": {"exists": True, "has_success_card": False}},
        )

        self.assertFalse(gate["ready_for_human_save_confirmation"])
        self.assertIn("main_video_success_card_missing", {item["code"] for item in gate["blockers"]})


if __name__ == "__main__":
    unittest.main()

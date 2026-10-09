# -*- coding: utf-8 -*-
"""映射与校验测试。

图片校验用 Pillow 现场生成合成图，不依赖任何真实商品素材。
"""

from __future__ import annotations

import unittest

from _helpers import make_image, make_temp_dir

from taobao_publish.constants import CONTRACT_RULES, EVIDENCE_UNKNOWN
from taobao_publish.contracts import load_contract, load_contracts
from taobao_publish.errors import SEVERITY_WARNING
from taobao_publish.mapping import (
    INTENT_ALL,
    build_platform_payload,
    build_publish_item,
    collect_unmapped_fields,
    match_freight_template,
    validate_images,
    validate_skus,
    validate_title,
)
from taobao_publish.models import ImageSet, LocalProduct, LocalSku, PublishItem, SkuEntry


def make_item(**overrides) -> PublishItem:
    defaults = dict(
        record_id=1,
        record_name="ID-1",
        title="小雏菊碎花袜子女春夏新款中筒袜",
        skus=[SkuEntry(spec_values={"颜色": "白色"}, price=9.9, stock=100)],
        images=ImageSet(),
    )
    defaults.update(overrides)
    return PublishItem(**defaults)


class BuildPublishItemTest(unittest.TestCase):
    def setUp(self) -> None:
        self.contracts = load_contracts()
        self.local = LocalProduct(
            record_id=7,
            record_name="ID-976666440420",
            title="本地标题",
            shipping_template="中通包邮",
            main_images=["/a.jpg"],
            detail_images=["/b.jpg"],
            white_bg_image="/w.jpg",
            skus=[LocalSku(name="白色", path="/sku/1.jpg", price=4.8)],
        )

    def test_request_title_overrides_local_title(self) -> None:
        outcome = build_publish_item(
            self.local, {"title": "请求标题", "skus": []}, contracts=self.contracts
        )
        assert outcome.item is not None
        self.assertEqual(outcome.item.title, "请求标题")

    def test_falls_back_to_local_title_when_request_is_blank(self) -> None:
        outcome = build_publish_item(self.local, {"title": "  "}, contracts=self.contracts)
        assert outcome.item is not None
        self.assertEqual(outcome.item.title, "本地标题")

    def test_local_images_are_used_when_request_omits_them(self) -> None:
        outcome = build_publish_item(self.local, {}, contracts=self.contracts)
        assert outcome.item is not None
        self.assertEqual(outcome.item.images.main, ["/a.jpg"])
        self.assertEqual(outcome.item.images.detail, ["/b.jpg"])
        self.assertEqual(outcome.item.images.white_bg, "/w.jpg")

    def test_explicit_empty_main_list_is_respected_not_overridden(self) -> None:
        """``images.main = []`` 表示「不要主图」，不能被回落到本地图片。

        用 ``or`` 做回落会把这种情况变成「用户说不要，我们却传了上去」。
        """

        outcome = build_publish_item(
            self.local, {"images": {"main": []}}, contracts=self.contracts
        )
        assert outcome.item is not None
        self.assertEqual(outcome.item.images.main, [])

    def test_explicit_main_list_replaces_local_list(self) -> None:
        outcome = build_publish_item(
            self.local, {"images": {"main": ["/other.jpg"]}}, contracts=self.contracts
        )
        assert outcome.item is not None
        self.assertEqual(outcome.item.images.main, ["/other.jpg"])

    def test_absent_key_still_falls_back(self) -> None:
        outcome = build_publish_item(
            self.local, {"images": {"detail": ["/d.jpg"]}}, contracts=self.contracts
        )
        assert outcome.item is not None
        self.assertEqual(outcome.item.images.main, ["/a.jpg"])
        self.assertEqual(outcome.item.images.detail, ["/d.jpg"])

    def test_local_freight_name_is_carried_over(self) -> None:
        outcome = build_publish_item(self.local, {}, contracts=self.contracts)
        assert outcome.item is not None
        self.assertEqual(outcome.item.freight_template_name, "中通包邮")

    def test_sku_fields_are_coerced(self) -> None:
        outcome = build_publish_item(
            self.local,
            {"skus": [{"spec_values": {"颜色": "黑"}, "price": "12.5", "stock": "30"}]},
            contracts=self.contracts,
        )
        assert outcome.item is not None
        sku = outcome.item.skus[0]
        self.assertEqual(sku.price, 12.5)
        self.assertEqual(sku.stock, 30)

    def test_non_numeric_price_becomes_none_not_zero(self) -> None:
        """解析不出来就留 ``None``，绝不默认成 0——0 元商品会被平台当成真价格。"""

        outcome = build_publish_item(
            self.local, {"skus": [{"price": "abc", "stock": 1}]}, contracts=self.contracts
        )
        assert outcome.item is not None
        self.assertIsNone(outcome.item.skus[0].price)

    def test_malformed_sku_entry_is_reported(self) -> None:
        outcome = build_publish_item(self.local, {"skus": ["not-an-object"]}, contracts=self.contracts)
        codes = {item.code for item in outcome.blockers}
        self.assertIn("SKU_INVALID", codes)


class ValidateTitleTest(unittest.TestCase):
    def setUp(self) -> None:
        self.contracts = load_contracts()

    def test_empty_title_blocks(self) -> None:
        blockers = validate_title(make_item(title=""), self.contracts)
        self.assertTrue(any(item.code == "REQUIRED_FIELD_MISSING" for item in blockers))

    def test_over_limit_title_blocks(self) -> None:
        blockers = validate_title(make_item(title="袜" * 61), self.contracts)
        self.assertEqual(len(blockers), 1)
        self.assertIn("超过上限 60", blockers[0].detail)

    def test_verified_rule_gets_no_hedge_in_message(self) -> None:
        """上限已实证时，提示里不该再加「证据等级为 …」的免责话术。

        这条是反向守卫：2026-10-03 把 title_max_chars 从 candidate 升到 verified
        之后，如果代码仍无条件拼接那句提示，就说明实现没跟上证据状态。
        """

        blockers = validate_title(make_item(title="袜" * 61), self.contracts)
        self.assertNotIn("证据等级为", blockers[0].detail)

    def test_candidate_rule_still_carries_the_hedge(self) -> None:
        """还没实证的数值必须如实带出等级，别让用户以为平台一定拒绝。"""

        from taobao_publish.contracts import Contracts, RulesContract

        payload = load_contract(CONTRACT_RULES)
        payload["rules"]["title_max_chars"]["evidence"]["level"] = "candidate"
        payload["rules"]["title_max_chars"]["evidence"]["source"] = ""
        loose = Contracts(
            field_mapping=self.contracts.field_mapping,
            selectors=self.contracts.selectors,
            rules=RulesContract(payload),
            publish_item_schema=self.contracts.publish_item_schema,
        )
        blockers = validate_title(make_item(title="袜" * 61), loose)
        self.assertEqual(len(blockers), 1)
        self.assertIn("证据等级为 candidate", blockers[0].detail)

    def test_exactly_at_limit_passes(self) -> None:
        self.assertEqual(validate_title(make_item(title="袜" * 30), self.contracts), [])


class ValidateSkusTest(unittest.TestCase):
    def setUp(self) -> None:
        self.contracts = load_contracts()

    def test_missing_price_and_stock_both_block(self) -> None:
        blockers = validate_skus(make_item(skus=[SkuEntry(spec_values={})]), self.contracts)
        fields = {item.field for item in blockers}
        self.assertIn("skus[0].price", fields)
        self.assertIn("skus[0].stock", fields)

    def test_non_positive_price_blocks(self) -> None:
        item = make_item(skus=[SkuEntry(spec_values={}, price=0.0, stock=1)])
        blockers = validate_skus(item, self.contracts)
        self.assertTrue(any(item.code == "PRICE_INVALID" for item in blockers))

    def test_negative_stock_blocks(self) -> None:
        item = make_item(skus=[SkuEntry(spec_values={}, price=1.0, stock=-5)])
        blockers = validate_skus(item, self.contracts)
        self.assertTrue(any(item.code == "PRICE_INVALID" for item in blockers))

    def test_duplicate_spec_combo_blocks(self) -> None:
        item = make_item(
            skus=[
                SkuEntry(spec_values={"颜色": "黑"}, price=1.0, stock=1),
                SkuEntry(spec_values={"颜色": "黑"}, price=2.0, stock=2),
            ]
        )
        blockers = validate_skus(item, self.contracts)
        self.assertTrue(any("重复" in item.detail for item in blockers))

    def test_inconsistent_spec_dimensions_block(self) -> None:
        item = make_item(
            skus=[
                SkuEntry(spec_values={"颜色": "黑", "尺码": "均码"}, price=1.0, stock=1),
                SkuEntry(spec_values={"颜色": "白"}, price=1.0, stock=1),
            ]
        )
        blockers = validate_skus(item, self.contracts)
        self.assertTrue(any("维度不一致" in item.detail for item in blockers))

    def test_mixed_empty_and_filled_specs_block(self) -> None:
        item = make_item(
            skus=[
                SkuEntry(spec_values={"颜色": "黑"}, price=1.0, stock=1),
                SkuEntry(spec_values={}, price=1.0, stock=1),
            ]
        )
        blockers = validate_skus(item, self.contracts)
        self.assertTrue(any("没有任何销售属性" in item.detail for item in blockers))

    def test_single_sku_without_specs_is_allowed(self) -> None:
        """单条无规格 SKU 是合法的（平台会给默认规格）。"""

        item = make_item(skus=[SkuEntry(spec_values={}, price=1.0, stock=1)])
        self.assertEqual(validate_skus(item, self.contracts), [])

    def test_too_many_skus_is_warning_not_blocker(self) -> None:
        skus = [
            SkuEntry(spec_values={"颜色": f"c{i}"}, price=1.0, stock=1) for i in range(41)
        ]
        blockers = validate_skus(make_item(skus=skus), self.contracts)
        self.assertTrue(blockers)
        self.assertTrue(all(item.severity == SEVERITY_WARNING for item in blockers))

    def test_empty_sku_list_blocks(self) -> None:
        blockers = validate_skus(make_item(skus=[]), self.contracts)
        self.assertTrue(any("至少需要" in item.detail for item in blockers))


class ValidateImagesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.contracts = load_contracts()

    def test_missing_main_image_blocks(self) -> None:
        blockers = validate_images(make_item(images=ImageSet()), self.contracts)
        self.assertTrue(any(item.code == "REQUIRED_FIELD_MISSING" for item in blockers))

    def test_valid_square_image_passes(self) -> None:
        directory = make_temp_dir(self)
        path = make_image(directory / "m1.jpg", (800, 800))
        blockers = validate_images(make_item(images=ImageSet(main=[str(path)])), self.contracts)
        self.assertEqual(blockers, [], [item.render() for item in blockers])

    def test_too_small_image_blocks(self) -> None:
        directory = make_temp_dir(self)
        path = make_image(directory / "small.jpg", (200, 200))
        blockers = validate_images(make_item(images=ImageSet(main=[str(path)])), self.contracts)
        self.assertTrue(any("最小边" in item.detail for item in blockers))

    def test_non_square_image_blocks(self) -> None:
        directory = make_temp_dir(self)
        path = make_image(directory / "tall.jpg", (800, 1200))
        blockers = validate_images(make_item(images=ImageSet(main=[str(path)])), self.contracts)
        self.assertTrue(any("宽高比" in item.detail for item in blockers))

    def test_missing_file_blocks(self) -> None:
        blockers = validate_images(
            make_item(images=ImageSet(main=["/definitely/not/here.jpg"])), self.contracts
        )
        self.assertTrue(any("文件不存在" in item.detail for item in blockers))

    def test_too_many_main_images_blocks(self) -> None:
        directory = make_temp_dir(self)
        paths = [str(make_image(directory / f"m{i}.jpg", (800, 800))) for i in range(6)]
        blockers = validate_images(make_item(images=ImageSet(main=paths)), self.contracts)
        self.assertTrue(any("最多" in item.detail for item in blockers))


class MatchFreightTemplateTest(unittest.TestCase):
    OPTIONS = [
        {"id": "111", "name": "中通包邮"},
        {"id": "222", "name": "顺丰到付"},
    ]

    def test_exact_unique_match_succeeds(self) -> None:
        result = match_freight_template("中通包邮", self.OPTIONS)
        self.assertFalse(result.blocked)
        self.assertEqual(result.matched_id, "111")

    def test_no_match_blocks_and_never_returns_default(self) -> None:
        result = match_freight_template("圆通包邮", self.OPTIONS)
        self.assertTrue(result.blocked)
        self.assertEqual(result.matched_id, "")
        self.assertIn("不存在", result.reason)

    def test_ambiguous_exact_match_blocks(self) -> None:
        """两个同名模板时必须拒绝，而不是取第一个——猜错会把运费算错。"""

        options = [
            {"id": "1", "name": "包邮"},
            {"id": "2", "name": "包邮"},
        ]
        result = match_freight_template("包邮", options)
        self.assertTrue(result.blocked)
        self.assertIn("同名", result.reason)

    def test_ambiguous_contains_match_blocks(self) -> None:
        options = [
            {"id": "1", "name": "中通包邮A"},
            {"id": "2", "name": "中通包邮B"},
        ]
        result = match_freight_template("中通包邮", options)
        self.assertTrue(result.blocked)
        self.assertIn("拒绝猜测", result.reason)

    def test_unique_contains_match_succeeds(self) -> None:
        options = [{"id": "9", "name": "中通快递包邮模板"}]
        result = match_freight_template("中通", options)
        self.assertFalse(result.blocked)
        self.assertEqual(result.matched_id, "9")

    def test_empty_name_blocks(self) -> None:
        self.assertTrue(match_freight_template("", self.OPTIONS).blocked)
        self.assertTrue(match_freight_template("   ", self.OPTIONS).blocked)

    def test_empty_options_block(self) -> None:
        result = match_freight_template("中通包邮", [])
        self.assertTrue(result.blocked)
        self.assertIn("未返回任何可用运费模板", result.reason)

    def test_options_missing_ids_are_ignored(self) -> None:
        result = match_freight_template("中通包邮", [{"name": "中通包邮"}])
        self.assertTrue(result.blocked)


class ContractGateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.contracts = load_contracts()

    def test_intents_are_covered_by_the_dom_route_so_none_is_blocked(self) -> None:
        """**字段证据认两条路线**（2026-10-03 修正）。

        协议路线靠 ``platform_field`` + ``verified``；DOM 路线靠**该字段所属阶段的
        写关键选择器全部就位**。``field_mapping.json`` 里的 ``blocker_hint``
        本来就写着「**或在 DOM 路线中确认……**」，这里把那句话落到实处。

        实测：修正前 16 个 intent 全部被判为不可写，真实写入永远被拦；
        修正后全部由 DOM 路线覆盖。
        """

        blockers = collect_unmapped_fields(self.contracts, INTENT_ALL)
        self.assertEqual(blockers, [], [item.render() for item in blockers])
        # 「不阻塞」必须能逐条解释：每个 intent 要么协议路线可写，要么阶段 DOM 就绪。
        dom_stages = self.contracts.selectors.dom_ready_stages()
        for intent in INTENT_ALL:
            spec = self.contracts.field_mapping.maybe(intent)
            self.assertIsNotNone(spec, intent)
            self.assertTrue(
                spec.write_eligible or (spec.stage and spec.stage in dom_stages),
                "{} 两条路线都没有证据，却不在阻塞项里".format(intent),
            )

    def test_a_field_with_no_evidence_on_either_route_is_still_blocked(self) -> None:
        """**核心安全属性**：两条路线都没证据时必须阻塞。

        用合成契约验，不依赖真实契约当前的缺口状态——
        否则这条用例会随着证据补齐而失去意义。
        """

        import copy
        import json
        from pathlib import Path

        from taobao_publish.constants import CONTRACT_FIELD_MAPPING
        from taobao_publish.contracts import Contracts, FieldMappingContract

        raw = json.loads((Path(__file__).resolve().parents[1] / CONTRACT_FIELD_MAPPING)
                         .read_text(encoding="utf-8"))
        patched = copy.deepcopy(raw)
        hit = False
        for entry in patched["fields"]:
            if entry["intent"] == "item.title":
                # 换成一个**没有任何写关键选择器**的阶段名：
                # 于是协议路线（platform_field 为 None）与 DOM 路线都不成立。
                # 顺手清掉 blocker_hint，确认判定靠的是证据而不是文案。
                entry["stage"] = "a_stage_with_no_selectors"
                entry["blocker_hint"] = ""
                hit = True
        self.assertTrue(hit, "契约里应当有 item.title")

        synthetic = Contracts(
            field_mapping=FieldMappingContract(patched),
            selectors=self.contracts.selectors,
            rules=self.contracts.rules,
            publish_item_schema=self.contracts.publish_item_schema,
        )
        blockers = collect_unmapped_fields(synthetic, ["item.title"])
        self.assertEqual(len(blockers), 1, "两条路线都没证据，必须阻塞")
        self.assertEqual(blockers[0].code, "EVIDENCE_INSUFFICIENT")
        self.assertIn("两条路线都没有", blockers[0].detail)

    def test_dom_route_evidence_comes_from_the_fields_own_stage(self) -> None:
        """DOM 路线的证据必须来自**该字段自己的阶段**，不能沾别的阶段的光。"""

        dom_stages = self.contracts.selectors.dom_ready_stages()
        self.assertTrue(dom_stages, "当前应当有 DOM 就绪的阶段")
        for intent in INTENT_ALL:
            spec = self.contracts.field_mapping.maybe(intent)
            if spec.write_eligible:
                continue
            self.assertIn(
                spec.stage, dom_stages,
                "{} 被判为有 DOM 证据，但它的阶段 {} 不在就绪集合里".format(intent, spec.stage),
            )

    def test_severity_can_be_downgraded_to_warning(self) -> None:
        blockers = collect_unmapped_fields(self.contracts, INTENT_ALL, severity=SEVERITY_WARNING)
        self.assertTrue(all(item.severity == SEVERITY_WARNING for item in blockers))
        self.assertFalse(any(item.is_blocking for item in blockers))

    def test_unknown_intent_is_reported_as_contract_problem(self) -> None:
        blockers = collect_unmapped_fields(self.contracts, ["item.does_not_exist"])
        self.assertEqual(blockers[0].code, "CONTRACT_INVALID")

    def test_build_platform_payload_is_empty_and_blocked(self) -> None:
        """当前没有任何字段可写，因此载荷必须为空且全部进阻塞项。"""

        payload, blockers = build_platform_payload(make_item(), self.contracts)
        self.assertEqual(payload, {})
        self.assertGreater(len(blockers), 0)
        self.assertTrue(all(item.code == "EVIDENCE_INSUFFICIENT" for item in blockers))

    def test_intent_list_has_no_duplicates(self) -> None:
        self.assertEqual(len(INTENT_ALL), len(set(INTENT_ALL)))


if __name__ == "__main__":
    unittest.main()

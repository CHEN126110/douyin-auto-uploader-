# -*- coding: utf-8 -*-
"""契约加载与自检测试。

契约是本子项目的**事实来源**：平台字段名、选择器、平台硬约束都只在那里。
这些测试保证契约不会悄悄退化成「随便什么形状都行」。
"""

from __future__ import annotations

import json
import unittest

from taobao_publish.constants import (
    CONTRACT_FIELD_MAPPING,
    CONTRACT_PUBLISH_ITEM_SCHEMA,
    CONTRACT_RULES,
    CONTRACT_SELECTORS,
    EVIDENCE_UNKNOWN,
    EVIDENCE_VERIFIED,
    STAGE_ORDER,
)
from taobao_publish.contracts import (
    SUBPROJECT_ROOT,
    load_contract,
    load_contracts,
    validate_contracts,
    write_route_status,
)


class ContractFileTest(unittest.TestCase):
    def test_data_contract_files_exist_and_parse(self) -> None:
        """三个数据契约必须带 ``contract_version``，便于 diff 时判断兼容性。"""

        for relative in (CONTRACT_FIELD_MAPPING, CONTRACT_SELECTORS, CONTRACT_RULES):
            payload = load_contract(relative)
            self.assertIsInstance(payload, dict, relative)
            self.assertIn("contract_version", payload, relative)

    def test_json_schema_contract_is_a_valid_draft07_schema(self) -> None:
        schema = load_contract(CONTRACT_PUBLISH_ITEM_SCHEMA)
        self.assertIsInstance(schema, dict)
        self.assertIn("$schema", schema)
        self.assertEqual(schema["type"], "object")
        self.assertIn("title", schema)

    def test_missing_contract_raises_instead_of_returning_empty(self) -> None:
        with self.assertRaises(ValueError):
            load_contract("contracts/definitely_not_here.json")


class ContractSelfCheckTest(unittest.TestCase):
    def test_validate_contracts_reports_no_problems(self) -> None:
        problems = validate_contracts()
        self.assertEqual(problems, [], "契约自检必须干净；问题：" + "；".join(problems))

    def test_detects_bad_evidence_level(self) -> None:
        data = load_contracts()
        payload = load_contract(CONTRACT_FIELD_MAPPING)
        payload["fields"][0]["evidence"]["level"] = "totally_made_up"
        from taobao_publish.contracts import Contracts, FieldMappingContract

        broken = Contracts(
            field_mapping=FieldMappingContract(payload),
            selectors=data.selectors,
            rules=data.rules,
            publish_item_schema=data.publish_item_schema,
        )
        problems = validate_contracts(broken)
        self.assertTrue(any("evidence.level 非法" in item for item in problems))

    def test_detects_verified_without_source(self) -> None:
        data = load_contracts()
        payload = load_contract(CONTRACT_FIELD_MAPPING)
        payload["fields"][0]["evidence"]["level"] = EVIDENCE_VERIFIED
        payload["fields"][0]["evidence"]["source"] = ""
        from taobao_publish.contracts import Contracts, FieldMappingContract

        broken = Contracts(
            field_mapping=FieldMappingContract(payload),
            selectors=data.selectors,
            rules=data.rules,
            publish_item_schema=data.publish_item_schema,
        )
        problems = validate_contracts(broken)
        self.assertTrue(any("没有 evidence.source" in item for item in problems))

    def test_detects_selector_filled_but_evidence_unknown(self) -> None:
        data = load_contracts()
        payload = load_contract(CONTRACT_SELECTORS)
        # 必须挑一个**证据确实是 unknown** 的条目。
        #
        # 早先这里挑的是「第一个 selector 为 null 的条目」，隐含假设「没填 selector 就是
        # 没取证」。契约新增 label 字段之后这个假设不成立了：有些条目 selector 为 null
        # 但靠 label 定位、证据是 verified（例如提交按钮）。挑到那种条目就不会触发
        # 本要检验的告警，测试会假失败。
        #
        # 2026-10-03 起**全部 30 条都已取证**，真实契约里不再有 unknown 样本，
        # 所以这里显式**造一个** unknown 条目——自检本身要一直被测，不能因为
        # 证据补齐就失去覆盖。
        payload["selectors"].append({
            "key": "test.synthetic_unknown",
            "stage": "precheck",
            "purpose": "自检用例专用：验证「填了 selector 却标 unknown」会被检出",
            "write_critical": False,
            "evidence": {"level": "unknown", "source": "", "note": ""},
        })
        target = next(
            item for item in payload["selectors"]
            if item["key"] == "test.synthetic_unknown"
        )
        target["selector"] = "div#title"
        from taobao_publish.contracts import Contracts, SelectorContract

        broken = Contracts(
            field_mapping=data.field_mapping,
            selectors=SelectorContract(payload),
            rules=data.rules,
            publish_item_schema=data.publish_item_schema,
        )
        problems = validate_contracts(broken)
        self.assertTrue(any("已填选择器但证据仍是 unknown" in item for item in problems))


class FieldMappingContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.contracts = load_contracts()

    def test_no_duplicate_intents(self) -> None:
        raw = load_contract(CONTRACT_FIELD_MAPPING)
        intents = [item["intent"] for item in raw["fields"]]
        self.assertEqual(len(intents), len(set(intents)))

    def test_all_stages_are_known(self) -> None:
        for spec in self.contracts.field_mapping.fields.values():
            if spec.stage:
                self.assertIn(spec.stage, STAGE_ORDER, spec.intent)

    def test_write_eligible_requires_verified_evidence(self) -> None:
        """写门规则：只有 ``verified`` 才允许真实写。"""

        for spec in self.contracts.field_mapping.fields.values():
            if spec.write_eligible:
                self.assertEqual(
                    spec.evidence_level,
                    EVIDENCE_VERIFIED,
                    f"{spec.intent} 不是 verified 却可写",
                )

    def test_required_fields_all_carry_a_blocker_hint(self) -> None:
        for spec in self.contracts.field_mapping.fields.values():
            if spec.required and not spec.write_eligible:
                self.assertTrue(spec.blocker_hint, f"{spec.intent} 缺少 blocker_hint")

    def test_required_unmapped_is_exactly_the_known_gap_list(self) -> None:
        """把当前证据缺口钉死成一份显式清单。

        这份清单变短 = 有进展；变长 = 有人加了必填字段却没取证。
        两种情况都应该让人看到 diff，而不是悄悄变化。
        """

        expected = {
            "item.title",
            "item.category_id",
            "item.props",
            "item.sale_props",
            "item.sale_prop_values",
            "sku.price",
            "sku.stock",
            "media.main_images",
            "logistics.freight_template_id",
            "publish.listing_mode",
        }
        actual = {spec.intent for spec in self.contracts.field_mapping.required_unmapped()}
        self.assertEqual(actual, expected)

    def test_evidence_summary_totals_match_field_count(self) -> None:
        summary = self.contracts.field_mapping.evidence_summary()
        self.assertEqual(sum(summary.values()), len(self.contracts.field_mapping.fields))


class SelectorContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.contracts = load_contracts()

    def test_no_duplicate_keys(self) -> None:
        raw = load_contract(CONTRACT_SELECTORS)
        keys = [item["key"] for item in raw["selectors"]]
        self.assertEqual(len(keys), len(set(keys)))

    def test_dom_write_route_is_ready_at_contract_level(self) -> None:
        """DOM 写路线的**选择器**已全部取证（2026-10-03 起）。

        这条原先叫 ``..._is_not_ready_yet``，断言 ``dom_write_route_ready()`` 为假
        ——那是在写关键选择器还有多个 ``unknown`` 的时候。
        随着 ``freight.template_option``（2026-10-03）与 ``skus.sku_row``
        （2026-10-03）转为 ``verified``，最后一个 ``unknown`` 只剩
        ``common.blocking_overlay``，而它**不是写关键**。

        注意这条只说明**证据面**就绪：``upload_images`` 与 ``fill_skus``
        两个阶段的**实现**仍未完成。两者是不同的事情，不要把这条读成「可以发布了」。
        """

        self.assertTrue(
            self.contracts.selectors.dom_write_route_ready(),
            "写关键选择器都已取证，DOM 写路线在契约层面应当就绪",
        )
        # 「就绪」必须能逐项解释：每个写关键选择器都得是 verified。
        for spec in self.contracts.selectors.selectors.values():
            if spec.write_critical:
                self.assertEqual(spec.evidence_level, EVIDENCE_VERIFIED, spec.key)
        self.assertEqual(
            [spec.key for spec in self.contracts.selectors.missing_write_critical()], [],
            "不应再有未取证的写关键选择器",
        )


class RulesContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.contracts = load_contracts()

    def test_numbers_are_usable(self) -> None:
        rules = self.contracts.rules
        self.assertEqual(rules.integer("title_max_chars"), 60)
        self.assertEqual(rules.integer("main_image_min_count"), 1)
        self.assertEqual(rules.integer("main_image_max_count"), 5)
        self.assertEqual(rules.integer("main_image_min_side_px"), 480)
        self.assertEqual(rules.integer("sku_min_count"), 1)
        self.assertAlmostEqual(rules.number("sku_price_min"), 0.01)

    def test_unknown_rules_are_recorded_not_silently_ignored(self) -> None:
        names = {item["name"] for item in self.contracts.rules.unknown_rules}
        self.assertIn("标题违禁词词表", names)
        self.assertIn("管控类目资质清单", names)
        # 2026-10-03 实拍新加的两条：类目级价格下限、标题上限随类目变化
        self.assertIn("类目级价格上下限", names)
        self.assertIn("标题长度上限", names)

    def test_image_format_rule_is_a_string_list(self) -> None:
        """允许的图片格式是枚举，用标量列表表达。"""

        formats = self.contracts.rules.get("main_image_formats").strings()
        self.assertEqual(formats, ("png", "jpg", "jpeg"))
        # 平台不支持 webp / bmp——这条决定了上传阶段要不要转格式
        self.assertNotIn("webp", formats)
        self.assertNotIn("bmp", formats)

    def test_strings_rejects_non_list_values(self) -> None:
        """不做「单值当单元素列表」的隐式兜底——那会让写错的契约看起来能用。"""

        spec = self.contracts.rules.get("title_max_chars")
        with self.assertRaises(ValueError):
            spec.strings()

    def test_strings_rejects_non_string_items(self) -> None:
        from taobao_publish.contracts import RuleSpec

        spec = RuleSpec(
            name="x",
            value=["png", 3],
            unit="",
            hard=True,
            evidence_level="verified",
            evidence_source="s",
            evidence_note="",
        )
        with self.assertRaises(ValueError):
            spec.strings()

    def test_evidence_summary_totals_match_rule_count(self) -> None:
        summary = self.contracts.rules.evidence_summary()
        self.assertEqual(sum(summary.values()), len(self.contracts.rules.rules))


class RouteStatusTest(unittest.TestCase):
    def test_reports_dom_route_ready_but_protocol_route_blocked(self) -> None:
        """两条写路线的状态**不同**，必须分开报告。

        * **协议路线**仍不可用：官方 API 对集市卖家关闭，字段映射也还没有实证；
        * **DOM 路线**在契约层面就绪（写关键选择器全部 ``verified``），
          但 ``upload_images`` / ``fill_skus`` 两个阶段尚未实现。

        「选择器就绪」与「阶段实现完成」是两件事，这条把两者都钉住。
        """

        status = write_route_status()
        self.assertFalse(status["protocol_write_ready"], "协议路线不该被误报为可用")
        self.assertTrue(status["dom_write_ready"], "写关键选择器都已取证")
        self.assertGreater(
            len(status["blocked_required_fields"]), 0,
            "平台必填字段的映射仍未实证，这一项应当继续报阻塞",
        )
        self.assertEqual(
            status["blocked_write_critical_selectors"], [],
            "不应再有未取证的写关键选择器",
        )
        json.dumps(status, ensure_ascii=False)  # 必须可序列化


class PublishItemSchemaTest(unittest.TestCase):
    def test_schema_is_draft07_object_with_required_keys(self) -> None:
        schema = load_contract(CONTRACT_PUBLISH_ITEM_SCHEMA)
        self.assertEqual(schema["type"], "object")
        for key in ("record_id", "title", "skus"):
            self.assertIn(key, schema["required"])

    def test_schema_contains_no_taobao_field_names(self) -> None:
        """入参契约是平台无关层，禁止出现淘宝字段名。"""

        raw = json.dumps(load_contract(CONTRACT_PUBLISH_ITEM_SCHEMA), ensure_ascii=False)
        for forbidden in ("sku_prices", "sku_quantities", "postage_id", "pic_path", "input_pids"):
            self.assertNotIn(forbidden, raw, f"入参契约里不应出现平台字段名 {forbidden}")

    def test_validation_accepts_a_minimal_valid_payload(self) -> None:
        try:
            import jsonschema  # type: ignore
        except ImportError:  # pragma: no cover - 本机已装，缺了也不该失败
            self.skipTest("jsonschema 不可用")
        schema = load_contract(CONTRACT_PUBLISH_ITEM_SCHEMA)
        payload = {
            "record_id": 1,
            "title": "测试标题",
            "skus": [{"price": 9.9, "stock": 100}],
        }
        jsonschema.validate(payload, schema)

    def test_validation_rejects_non_positive_price(self) -> None:
        try:
            import jsonschema  # type: ignore
        except ImportError:  # pragma: no cover
            self.skipTest("jsonschema 不可用")
        schema = load_contract(CONTRACT_PUBLISH_ITEM_SCHEMA)
        payload = {
            "record_id": 1,
            "title": "测试标题",
            "skus": [{"price": 0, "stock": 100}],
        }
        with self.assertRaises(Exception):
            jsonschema.validate(payload, schema)


class ContractGateBoundaryTest(unittest.TestCase):
    """契约门的边界。

    对抗性审查（2026-10-02，F7/F8）实测出两个洞，现在都用测试钉住：

    * ``platform_field`` 只做 ``bool()``，纯空白 / 非字符串也算「有字段名」；
    * ``validate_contracts`` 的问题**没有任何强制消费点**，「标为 verified 但没有
      ``evidence.source``」被检出却照样进载荷、``describe_readiness`` 还报
      ``publish_route_ready=True``。
    """

    def _adversarial(self, platform_field, level: str = "verified", source: str = "captures/x.json"):
        from taobao_publish.contracts import Contracts, FieldMappingContract, RulesContract, SelectorContract

        payload = load_contract(CONTRACT_FIELD_MAPPING)
        payload["fields"][0]["platform_field"] = platform_field
        payload["fields"][0]["evidence"]["level"] = level
        payload["fields"][0]["evidence"]["source"] = source
        base = load_contracts()
        return Contracts(
            field_mapping=FieldMappingContract(payload),
            selectors=SelectorContract(load_contract(CONTRACT_SELECTORS)),
            rules=RulesContract(load_contract(CONTRACT_RULES)),
            publish_item_schema=base.publish_item_schema,
        )

    def test_write_eligible_rejects_blank_and_non_string_platform_field(self) -> None:
        for bad in ("", "   ", 123, ["cid"], None):
            adv = self._adversarial(bad)
            spec = adv.field_mapping.get("item.title")
            self.assertFalse(spec.write_eligible, f"platform_field={bad!r} 不应可写")
            self.assertTrue(validate_contracts(adv), f"platform_field={bad!r} 应被自检报出")

    def test_write_eligible_requires_evidence_source(self) -> None:
        adv = self._adversarial("title", source="")
        self.assertFalse(adv.field_mapping.get("item.title").write_eligible)
        self.assertTrue(
            any("没有 evidence.source" in item for item in validate_contracts(adv)),
            "缺 source 的 verified 必须被自检报出",
        )

    def test_platform_payload_refuses_when_contracts_have_problems(self) -> None:
        """自检非空 → 拒绝组装载荷。否则自检就只是打印，没有强制力。"""

        from taobao_publish.mapping import build_platform_payload
        from taobao_publish.models import ImageSet, PublishItem, SkuEntry

        adv = self._adversarial("title", source="")
        item = PublishItem(
            record_id=1,
            record_name="ID-1",
            title="小标题",
            skus=[SkuEntry(spec_values={"颜色": "白"}, price=9.9, stock=1)],
            images=ImageSet(main=["/a.jpg"]),
        )
        payload, blockers = build_platform_payload(item, adv)
        self.assertEqual(payload, {})
        self.assertTrue(any(entry.code == "CONTRACT_INVALID" for entry in blockers))

    def test_problems_block_reported_publish_readiness(self) -> None:
        from taobao_publish.contracts import write_route_status

        adv = self._adversarial("title", source="")
        status = write_route_status(adv)
        self.assertTrue(status["contract_problems"])
        self.assertFalse(status["protocol_write_ready"], "自检报错的契约不得宣称写路线可用")
        self.assertFalse(status["dom_write_ready"])

    def test_clean_contracts_still_report_not_ready_for_other_reasons(self) -> None:
        """契约干净也不等于能发布——其他必填字段仍然没有证据。"""

        from taobao_publish.contracts import write_route_status

        adv = self._adversarial("title")  # 只有 title 取证，且 source 齐全
        status = write_route_status(adv)
        self.assertEqual(status["contract_problems"], [])
        self.assertFalse(status["protocol_write_ready"])
        self.assertIn("item.category_id", status["blocked_required_fields"])


class SubprojectLayoutTest(unittest.TestCase):
    def test_contracts_dir_is_where_we_think(self) -> None:
        self.assertTrue((SUBPROJECT_ROOT / "contracts").is_dir())
        self.assertTrue((SUBPROJECT_ROOT / "taobao_publish").is_dir())


if __name__ == "__main__":
    unittest.main()

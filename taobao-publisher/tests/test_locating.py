# -*- coding: utf-8 -*-
"""标签定位的不变量测试。

这些用例保护的是「不会把值写到错误的行」这条红线：命中数不为 1 时必须失败，
而不是「找一个看起来像的」凑合写下去。

用例全部离线，不连浏览器、不碰平台。
"""

from __future__ import annotations

import json
import re
import unittest

from taobao_publish import locating


class ExpressionGenerationTest(unittest.TestCase):
    def test_embeds_the_label_as_a_js_literal(self) -> None:
        expression = locating.locate_row_expression("材质成分")
        self.assertIn(json.dumps("材质成分", ensure_ascii=False), expression)
        # 直接内联中文而不是 \\uXXXX 转义——页面里按文本比对，转义了反而对不上
        self.assertIn("材质成分", expression)

    def test_uses_the_verified_row_and_label_selectors(self) -> None:
        expression = locating.locate_row_expression("面料")
        self.assertIn(locating.ROW_SELECTOR, expression)
        self.assertIn(locating.LABEL_SELECTOR, expression)
        # 行容器必须用实测到的那个；换成 .next-form-item 会命中 0 个
        self.assertNotIn(".next-form-item", expression)

    def test_never_falls_back_to_positional_lookup(self) -> None:
        """禁止按位置定位——页面增删字段会整体错位，且每步都「成功」。"""

        expression = locating.locate_row_expression("一口价")
        for forbidden in ("nth-child", "querySelectorAll('input')[", "children[0]"):
            self.assertNotIn(forbidden, expression)

    def test_label_is_escaped_so_it_cannot_break_out(self) -> None:
        """标签名当前来自契约常量，但不因此放松转义。"""

        hostile = 'a"; alert(1); //'
        expression = locating.locate_row_expression(hostile)
        self.assertIn(json.dumps(hostile, ensure_ascii=False), expression)
        # 恶意串必须整段待在字符串字面量里，不能变成可执行代码
        self.assertNotIn('alert(1); //"', expression.replace(json.dumps(hostile, ensure_ascii=False), ""))

    def test_quotes_and_backslashes_survive(self) -> None:
        for label in ('带"双引号', "带'单引号", "带\\反斜杠", "带\n换行"):
            with self.subTest(label=label):
                expression = locating.locate_row_expression(label)
                self.assertIn(json.dumps(label, ensure_ascii=False), expression)

    def test_rejects_blank_labels(self) -> None:
        for value in ("", "   ", None, 123):
            with self.subTest(value=value), self.assertRaises(ValueError):
                locating.locate_row_expression(value)  # type: ignore[arg-type]


class DescribePayloadTest(unittest.TestCase):
    def test_maps_a_unique_hit(self) -> None:
        row = locating.describe_located_row({
            "label": "面料", "hitCount": 1, "matchMode": "exact",
            "controlCount": 1, "rowClass": "sell-component-info-wrapper-wrap",
        })
        self.assertTrue(row.unique)
        self.assertEqual(row.hit_count, 1)
        self.assertEqual(row.reason, "")

    def test_missing_label_is_not_treated_as_usable(self) -> None:
        row = locating.describe_located_row({"label": "不存在", "hitCount": 0, "matchMode": "none"})
        self.assertFalse(row.unique)
        self.assertIn("没有定位到行", row.reason)

    def test_ambiguous_hit_is_not_treated_as_usable(self) -> None:
        row = locating.describe_located_row({"label": "重复", "hitCount": 3, "matchMode": "exact"})
        self.assertFalse(row.unique)
        self.assertIn("多行", row.reason)

    def test_garbage_payload_does_not_crash_or_look_usable(self) -> None:
        for payload in (None, [], "x", 42, {"hitCount": "1"}, {"hitCount": -1}):
            with self.subTest(payload=payload):
                row = locating.describe_located_row(payload)
                self.assertFalse(row.unique, "无法解析的结果绝不能算作可用")


class RequireUniqueTest(unittest.TestCase):
    def test_passes_a_single_hit_through(self) -> None:
        row = locating.LocatedRow("面料", 1, "exact", 1, "cls")
        self.assertIs(locating.require_unique(row), row)

    def test_raises_not_found_on_zero(self) -> None:
        row = locating.LocatedRow("面料", 0, "none", 0, "")
        with self.assertRaises(locating.LabelNotFound):
            locating.require_unique(row)

    def test_raises_ambiguous_on_multiple(self) -> None:
        """这条是核心：命中多行时必须失败，不能挑第一个写下去。"""

        row = locating.LocatedRow("面料", 2, "exact", 1, "")
        with self.assertRaises(locating.LabelAmbiguous) as ctx:
            locating.require_unique(row)
        self.assertIn("命中 2 行", str(ctx.exception))

    def test_ambiguous_and_not_found_are_distinct_types(self) -> None:
        # 调用方需要区分「字段不在这」和「字段重复了」——处置方式完全不同
        self.assertFalse(issubclass(locating.LabelAmbiguous, locating.LabelNotFound))
        self.assertTrue(issubclass(locating.LabelAmbiguous, LookupError))
        self.assertTrue(issubclass(locating.LabelNotFound, LookupError))


class OperateRowExpressionTest(unittest.TestCase):
    def test_embeds_the_action_and_keeps_the_uniqueness_gate(self) -> None:
        expression = locating.operate_row_expression("宝贝标题", "control.value = 'x';")
        self.assertIn("control.value = 'x';", expression)
        # 唯一性判定必须在动作之前，且命中数不为 1 时提前 return
        gate = expression.index("hits.length !== 1")
        self.assertLess(gate, expression.index("control.value = 'x';"))
        self.assertIn("label_ambiguous", expression)
        self.assertIn("label_not_found", expression)

    def test_rejects_an_empty_action(self) -> None:
        for action in ("", "   ", None, 5):
            with self.subTest(action=action), self.assertRaises(ValueError):
                locating.operate_row_expression("面料", action)  # type: ignore[arg-type]


class ButtonLocatingTest(unittest.TestCase):
    """按钮同样没有唯一属性——「提交宝贝信息」与「保存草稿」的区别**只在文本**。"""

    def test_embeds_the_button_text(self) -> None:
        expression = locating.locate_button_expression("提交宝贝信息")
        self.assertIn(json.dumps("提交宝贝信息", ensure_ascii=False), expression)
        self.assertIn("querySelectorAll('button')", expression)

    def test_reports_visibility_separately_from_existence(self) -> None:
        """按钮存在但在别的 tab 里是常态，必须能区分。"""

        expression = locating.locate_button_expression("保存草稿")
        self.assertIn("visibleCount", expression)
        self.assertIn("getBoundingClientRect", expression)

    def test_rejects_blank_button_text(self) -> None:
        for value in ("", "   ", None, 7):
            with self.subTest(value=value), self.assertRaises(ValueError):
                locating.locate_button_expression(value)  # type: ignore[arg-type]

    def test_describe_marks_missing_and_ambiguous_as_unusable(self) -> None:
        self.assertFalse(locating.describe_located_button({"text": "x", "hitCount": 0}).unique)
        self.assertFalse(locating.describe_located_button({"text": "x", "hitCount": 3}).unique)
        self.assertTrue(
            locating.describe_located_button(
                {"text": "x", "hitCount": 1, "visibleCount": 1}
            ).unique
        )

    def test_invisible_button_is_reported_not_silently_clicked(self) -> None:
        button = locating.describe_located_button({"text": "保存草稿", "hitCount": 1, "visibleCount": 0})
        self.assertIn("不可见", button.reason)
        with self.assertRaises(locating.LabelNotFound):
            locating.require_unique_button(button)

    def test_require_unique_button_raises_on_ambiguity(self) -> None:
        button = locating.describe_located_button({"text": "确认", "hitCount": 2, "visibleCount": 2})
        with self.assertRaises(locating.LabelAmbiguous):
            locating.require_unique_button(button)

    def test_operate_button_gates_before_the_action(self) -> None:
        expression = locating.operate_button_expression("提交宝贝信息", "button.click();")
        gate = expression.index("hits.length !== 1 || usable.length !== 1")
        self.assertLess(gate, expression.index("button.click();"))

    def test_operate_button_rejects_empty_action(self) -> None:
        with self.assertRaises(ValueError):
            locating.operate_button_expression("保存草稿", "")


class MeasuredMapTest(unittest.TestCase):
    """实测的页面地图。改错会导致必填项漏填，而发布会在平台侧才失败。"""

    def test_required_rows_include_platform_mandatory_ones(self) -> None:
        required = {k for k, v in locating.MEASURED_ROW_LABELS.items() if v.get("required")}
        for label in ("当前类目", "宝贝标题", "一口价", "总库存", "上架时间", "发货时间", "提取方式", "宝贝详情"):
            self.assertIn(label, required, "{} 是平台必填项".format(label))

    def test_rows_without_inline_controls_are_recorded_honestly(self) -> None:
        """行内没有控件的字段不能用通用控件定位——必须在地图里写清楚。"""

        for label in ("材质成分", "销售规格", "宝贝详情", "1:1主图"):
            self.assertEqual(locating.MEASURED_ROW_LABELS[label]["controls"], 0)
        self.assertIn("添加材质成分", locating.MEASURED_ROW_LABELS["材质成分"]["note"])
        self.assertIn("创建规格", locating.MEASURED_ROW_LABELS["销售规格"]["note"])

    def test_submit_and_draft_buttons_are_marked_as_writes(self) -> None:
        self.assertTrue(locating.MEASURED_BUTTONS["提交宝贝信息"]["write"])
        self.assertTrue(locating.MEASURED_BUTTONS["保存草稿"]["write"])

    def test_non_mutating_buttons_are_not_marked_as_writes(self) -> None:
        # 「预览」「切换类目」不改变平台状态，标成写会让调用方白白加锁
        self.assertFalse(locating.MEASURED_BUTTONS["预览"]["write"])
        self.assertFalse(locating.MEASURED_BUTTONS["切换类目"]["write"])

    def test_product_attributes_row_is_flagged_as_a_parent(self) -> None:
        self.assertEqual(locating.MEASURED_ROW_LABELS["商品属性"]["controls"], 21)
        self.assertIn("父行", locating.MEASURED_ROW_LABELS["商品属性"]["note"])


class TextAnchorLocatingTest(unittest.TestCase):
    """类名是 CSS Modules 哈希时，只能按文本锚点定位。

    实测：运费模板的容器是 ``div.template-lzNicC``、标签是 ``div.label-HElTNK``——
    这两个类名每次构建都会变，写进契约等于埋雷。
    """

    def test_embeds_the_anchor_text(self) -> None:
        expression = locating.locate_text_anchor_expression("运费模板")
        self.assertIn(json.dumps("运费模板", ensure_ascii=False), expression)

    def test_does_not_rely_on_any_class_name(self) -> None:
        """锚点定位的全部意义就是**不认类名**。"""

        expression = locating.locate_text_anchor_expression("运费模板")
        self.assertNotIn("template-", expression)
        self.assertNotIn("label-HElTNK", expression)
        # 不能把哈希类名硬编码进去
        self.assertNotIn("lzNicC", expression)

    def test_walks_up_and_reports_every_level(self) -> None:
        expression = locating.locate_text_anchor_expression("运费模板")
        self.assertIn("parentElement", expression)
        self.assertIn("candidates", expression)
        self.assertIn("controlCount", expression)

    def test_rejects_out_of_range_hops(self) -> None:
        for hops in (0, -1, 9, 100):
            with self.subTest(hops=hops), self.assertRaises(ValueError):
                locating.locate_text_anchor_expression("运费模板", max_hops=hops)

    def test_describe_reports_the_chosen_level(self) -> None:
        anchor = locating.describe_located_anchor({
            "anchor": "运费模板", "found": True, "hitCount": 1,
            "chosen": {"hop": 1, "className": "template-lzNicC", "controlCount": 1},
        })
        self.assertTrue(anchor.unique)
        self.assertEqual(anchor.chosen_hop, 1)
        self.assertEqual(anchor.chosen_control_count, 1)

    def test_anchor_missing_is_rejected(self) -> None:
        anchor = locating.describe_located_anchor({"anchor": "不存在", "found": False, "hitCount": 0})
        with self.assertRaises(locating.LabelNotFound):
            locating.require_unique_anchor(anchor)

    def test_no_level_with_exactly_one_control_is_rejected(self) -> None:
        """如果每层要么 0 个要么 ≥2 个控件，就不能猜——必须失败。"""

        anchor = locating.describe_located_anchor({"anchor": "运费模板", "found": True, "hitCount": 0})
        with self.assertRaises(locating.LabelNotFound) as ctx:
            locating.require_unique_anchor(anchor)
        self.assertIn("恰好 1 个可见控件", str(ctx.exception))

    def test_multiple_qualifying_levels_is_rejected(self) -> None:
        anchor = locating.describe_located_anchor({"anchor": "运费模板", "found": True, "hitCount": 2})
        with self.assertRaises(locating.LabelAmbiguous):
            locating.require_unique_anchor(anchor)

    def test_garbage_payload_is_not_usable(self) -> None:
        for payload in (None, [], "x", 5):
            with self.subTest(payload=payload):
                self.assertFalse(locating.describe_located_anchor(payload).unique)

    def test_freight_template_is_documented_as_text_anchor_only(self) -> None:
        entry = locating.TEXT_ANCHOR_ONLY.get("运费模板")
        self.assertIsNotNone(entry, "运费模板必须登记在「只能按文本锚点定位」名单里")
        self.assertIn("哈希", entry["reason"])


class VerifiedLabelsTest(unittest.TestCase):
    def test_only_evidenced_labels_are_exposed(self) -> None:
        """阶段只能使用实测确认过的标签；没确认的阶段必须返回空。"""

        for stage in ("fill_base", "fill_props", "fill_price_stock"):
            labels = locating.verified_labels_for(stage)
            self.assertTrue(labels, "{} 应有已确认标签".format(stage))
            self.assertNotIn("材质成分", locating.verified_labels_for("upload_images"))

    def test_unknown_stage_yields_nothing_instead_of_guessing(self) -> None:
        self.assertEqual(locating.verified_labels_for("submit"), [])
        self.assertEqual(locating.verified_labels_for(""), [])
        self.assertEqual(locating.verified_labels_for("not_a_stage"), [])

    def test_required_category_props_are_covered(self) -> None:
        # 「上市年份季节」是实测带 * 的必填项，必须在名单里，否则必填校验会漏
        self.assertIn("上市年份季节", locating.verified_labels_for("fill_props"))
        self.assertIn("宝贝标题", locating.verified_labels_for("fill_base"))
        self.assertIn("一口价", locating.verified_labels_for("fill_price_stock"))
        self.assertIn("总库存", locating.verified_labels_for("fill_price_stock"))

    def test_verified_labels_do_not_overlap_between_stages(self) -> None:
        seen: dict[str, str] = {}
        for stage in locating.VERIFIED_LABELS:
            for label in locating.verified_labels_for(stage):
                self.assertNotIn(label, seen, "{} 与 {} 都声明了 {!r}".format(stage, seen.get(label), label))
                seen[label] = stage


class SelectorContractTest(unittest.TestCase):
    """选择器常量必须与真实页面一致；改错会让所有阶段静默命中 0 行。"""

    def test_row_selector_matches_the_measured_structure(self) -> None:
        self.assertEqual(locating.ROW_SELECTOR, ".sell-component-info-wrapper-wrap")
        self.assertEqual(locating.LABEL_SELECTOR, ".sell-component-info-wrapper-label")

    def test_control_selector_covers_the_measured_control_kinds(self) -> None:
        for fragment in ("input", "textarea", "select"):
            self.assertIn(fragment, locating.CONTROL_SELECTOR)
        self.assertIn("combobox", locating.CONTROL_SELECTOR)

    def test_module_documents_why_positional_lookup_is_banned(self) -> None:
        doc = locating.__doc__ or ""
        self.assertIn("禁止", doc)
        self.assertIn("唯一", doc)


if __name__ == "__main__":
    unittest.main()

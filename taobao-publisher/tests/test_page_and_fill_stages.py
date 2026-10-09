# -*- coding: utf-8 -*-
"""页面交互层与填表阶段的不变量测试。

保护的红线：**不许把值写到错误的行**、**不许在没回读核对的情况下报成功**、
**不许对未实测的属性凭猜填写**。

用例全部离线：页面被替换成内存替身，不连浏览器、不碰平台。
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path
from typing import Optional
from unittest import mock

from taobao_publish import locating, page, stages
from taobao_publish.authorization import WriteAuthorization
from taobao_publish.constants import STAGE_WRITE_OPERATION
from taobao_publish.models import PublishItem, PropEntry, SkuEntry, StepRecord


class FakeClient:
    """内存替身：记录收到的表达式，按预设脚本返回值。"""

    def __init__(self, responses=None):
        self.responses = list(responses or [])
        self.expressions = []
        self.closed = False

    def evaluate(self, expression, timeout=15.0):
        self.expressions.append(expression)
        if not self.responses:
            raise AssertionError("替身没有更多预设响应")
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def close(self):
        self.closed = True


class ExpressionBuildingTest(unittest.TestCase):
    def test_set_expression_uses_the_native_setter_and_fires_events(self) -> None:
        """直接改 input.value 不会触发 React 的 onChange——界面有字、提交是空的。"""

        expression = page.build_set_expression("宝贝标题", "测试标题")
        self.assertIn("HTMLInputElement.prototype", expression)
        self.assertIn("setter.call(control", expression)
        self.assertIn("new Event('input'", expression)
        self.assertIn("new Event('change'", expression)
        self.assertIn(json.dumps("测试标题", ensure_ascii=False), expression)

    def test_read_expression_does_not_install_a_global(self) -> None:
        """读回值用局部变量，不往用户页面上挂 window 属性。"""

        expression = page.build_read_expression("一口价")
        self.assertNotIn("window.", expression)
        self.assertIn("readBack", expression)

    def test_both_expressions_go_through_label_locating(self) -> None:
        for expression in (page.build_set_expression("面料", "棉"), page.build_read_expression("面料")):
            self.assertIn(locating.ROW_SELECTOR, expression)
            self.assertIn(locating.LABEL_SELECTOR, expression)

    def test_value_is_escaped(self) -> None:
        hostile = '"; alert(1); //'
        expression = page.build_set_expression("款号", hostile)
        self.assertIn(json.dumps(hostile, ensure_ascii=False), expression)

    def test_rejects_non_string_values(self) -> None:
        for value in (None, 5, [], {}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                page.build_set_expression("款号", value)  # type: ignore[arg-type]


class FillTextFieldTest(unittest.TestCase):
    def test_writes_then_reads_back(self) -> None:
        client = FakeClient([{"ok": True, "label": "款号"}, {"ok": True, "label": "款号", "value": "A1"}])
        result = page.fill_text_field(client, "款号", "A1")
        self.assertEqual(result["read_back"], "A1")
        self.assertEqual(len(client.expressions), 2, "写入之后必须再读一次")

    def test_mismatch_is_a_failure_not_a_success(self) -> None:
        """表单可能格式化或干脆没接受值。只报「已写入」等于把结果交给运气。"""

        client = FakeClient([{"ok": True}, {"ok": True, "value": "被改过了"}])
        with self.assertRaises(page.FieldMismatchError) as ctx:
            page.fill_text_field(client, "一口价", "16.80")
        self.assertIn("回读不一致", str(ctx.exception))

    def test_ambiguous_label_is_rejected_before_writing(self) -> None:
        client = FakeClient([{"ok": False, "reason": "label_ambiguous", "hitCount": 3}])
        with self.assertRaises(locating.LabelAmbiguous):
            page.fill_text_field(client, "重复标签", "x")
        self.assertEqual(len(client.expressions), 1, "被拒绝后不得再发读回请求")

    def test_missing_label_is_rejected(self) -> None:
        # **两条响应**：第一条给 `read_text_field`（发布页组合，定位不到），
        # 第二条给属性行退路 `read_prop_value`——两条都读不到才叫读不到。
        client = FakeClient([
            {"ok": False, "reason": "label_not_found", "hitCount": 0},
            {"ok": False, "hitCount": 0},
        ])
        with self.assertRaises(locating.LabelNotFound):
            page.fill_text_field(client, "不存在的字段", "x")

    def test_unparsable_payload_is_not_treated_as_success(self) -> None:
        for payload in (None, [], "ok", 7):
            with self.subTest(payload=payload):
                client = FakeClient([payload])
                with self.assertRaises(page.PageError):
                    page.fill_text_field(client, "款号", "x")

    def test_verify_can_be_skipped_explicitly(self) -> None:
        client = FakeClient([{"ok": True}])
        result = page.fill_text_field(client, "款号", "A1", verify=False)
        self.assertIsNone(result["read_back"])
        self.assertEqual(len(client.expressions), 1)

    def test_read_helper_returns_none_for_null(self) -> None:
        client = FakeClient([{"ok": True, "value": None}])
        self.assertIsNone(page.read_text_field(client, "款号"))


class StageFillBaseTest(unittest.TestCase):
    def _ctx(self, **kwargs):
        item = PublishItem(record_id=1, record_name="测试商品", **kwargs)
        return stages.PipelineContext(item=item, dry_run=False)

    def test_empty_title_is_a_structured_failure(self) -> None:
        outcome = stages.stage_fill_base(self._ctx(title="   "))
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.error_code, "EVIDENCE_INSUFFICIENT")

    def test_overlong_title_is_rejected_before_any_page_call(self) -> None:
        with mock.patch.object(stages, "_open_publish_page") as opener:
            outcome = stages.stage_fill_base(self._ctx(title="长" * 61))
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.error_code, "TITLE_TOO_LONG")
        opener.assert_not_called()

    def test_title_at_the_limit_is_accepted(self) -> None:
        client = FakeClient([{"ok": True}, {"ok": True, "value": "长" * 30}])
        with mock.patch.object(stages, "_open_publish_page", return_value=client):
            outcome = stages.stage_fill_base(self._ctx(title="长" * 30))
        self.assertTrue(outcome.ok)
        self.assertIn("宝贝标题", outcome.summary)

    def test_outer_id_is_skipped_when_absent_and_said_so(self) -> None:
        client = FakeClient([{"ok": True}, {"ok": True, "value": "标题"}])
        with mock.patch.object(stages, "_open_publish_page", return_value=client):
            outcome = stages.stage_fill_base(self._ctx(title="标题"))
        self.assertTrue(outcome.ok)
        self.assertIn("商家编码", outcome.data["skipped"][0])
        self.assertEqual(len(client.expressions), 2, "只应写标题并读回一次")

    def test_client_is_closed_on_failure(self) -> None:
        # 同上：退路会多调一次，替身要备两条。
        client = FakeClient([
            {"ok": False, "reason": "label_not_found"},
            {"ok": False, "hitCount": 0},
        ])
        with mock.patch.object(stages, "_open_publish_page", return_value=client):
            outcome = stages.stage_fill_base(self._ctx(title="标题"))
        self.assertFalse(outcome.ok)
        self.assertTrue(client.closed)


class StageFillPropsTest(unittest.TestCase):
    def _ctx(self, props):
        item = PublishItem(record_id=1, record_name="测试商品", title="标题", props=props)
        return stages.PipelineContext(item=item, dry_run=False)

    def test_unknown_prop_name_is_refused_instead_of_guessed(self) -> None:
        """不在实测地图里的属性**不许猜**——猜错会写到别的字段上，且每步都「成功」。"""

        with mock.patch.object(stages, "_open_publish_page") as opener:
            outcome = stages.stage_fill_props(self._ctx([PropEntry("不存在的属性", "某值")]))
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.error_code, "EVIDENCE_INSUFFICIENT")
        self.assertIn("不存在的属性", outcome.summary)
        opener.assert_not_called()

    def test_prop_row_without_inline_control_is_refused(self) -> None:
        # 材质成分实测行内 0 个控件，必须走专用入口而不是通用控件定位
        outcome = stages.stage_fill_props(self._ctx([PropEntry("材质成分", "棉")]))
        self.assertFalse(outcome.ok)
        self.assertIn("材质成分", outcome.summary)

    def test_empty_property_overrides_preserve_existing_values_for_final_required_readback(self) -> None:
        outcome = stages.stage_fill_props(self._ctx([]))
        self.assertTrue(outcome.ok)
        self.assertEqual(outcome.status, "skipped")
        self.assertIn("最终回读", outcome.summary)

    def test_known_props_are_written_and_verified(self) -> None:
        """验的是**写入 + 回读校验**这套机制，不是某个属性真的可写。

        ⚠️ **`classify_row` 是打桩的，而且必须打桩。**
        2026-10-03 的只读实测：`面料`**不在这页**（地图是跨类目并集），
        `上市年份季节`定位得到但控件是 `input[role=combobox]`（可搜索下拉）。
        两者都不该被文本方式写进去——`fill_props` 现在会正确地拒绝。

        所以这里强制分类为 `text`，把机制本身单独测出来；
        「按控件类型拒绝」由 `tests/test_prop_row_classification.py` 覆盖。
        """

        client = FakeClient([
            {"ok": True}, {"ok": True, "value": "棉"},
            {"ok": True}, {"ok": True, "value": "秋冬"},
        ])
        text_shape = {"located": True, "profile": "publish_form",
                      "controlCount": 1, "kind": "text", "hitCount": 1}
        with mock.patch.object(stages, "_open_publish_page", return_value=client):
            with mock.patch("taobao_publish.page.classify_row", return_value=text_shape):
                outcome = stages.stage_fill_props(self._ctx([
                    PropEntry("面料", "棉"), PropEntry("上市年份季节", "秋冬"),
                ]))
        self.assertTrue(outcome.ok)
        self.assertEqual(len(outcome.data["props"]), 2)


class StageFillPriceStockTest(unittest.TestCase):
    def _ctx(self, skus):
        item = PublishItem(record_id=1, record_name="测试商品", title="标题", skus=skus)
        return stages.PipelineContext(item=item, dry_run=False)

    def test_missing_price_is_refused(self) -> None:
        outcome = stages.stage_fill_price_stock(self._ctx([SkuEntry({"颜色": "黑"}, price=None, stock=5)]))
        self.assertFalse(outcome.ok)
        self.assertIn("价格", outcome.summary)

    def test_missing_stock_is_refused(self) -> None:
        outcome = stages.stage_fill_price_stock(self._ctx([SkuEntry({"颜色": "黑"}, price=9.9, stock=None)]))
        self.assertFalse(outcome.ok)
        self.assertIn("库存", outcome.summary)

    def test_price_below_contract_floor_is_refused(self) -> None:
        with mock.patch.object(stages, "_open_publish_page") as opener:
            outcome = stages.stage_fill_price_stock(
                self._ctx([SkuEntry({"颜色": "黑"}, price=0.001, stock=1)]))
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.error_code, "PRICE_TOO_LOW")
        opener.assert_not_called()

    def test_picks_the_lowest_price_and_sums_stock(self) -> None:
        client = FakeClient([
            {"ok": True, "value": "1"},          # 写入前回读总库存（UI 预填 1）
            {"ok": True}, {"ok": True, "value": "34.00"},
            {"ok": True}, {"ok": True, "value": "30"},
        ])
        with mock.patch.object(stages, "_open_publish_page", return_value=client):
            outcome = stages.stage_fill_price_stock(self._ctx([
                SkuEntry({"颜色": "黑"}, price=16.8, stock=10),
                SkuEntry({"颜色": "白"}, price=19.9, stock=20),
            ]))
        self.assertTrue(outcome.ok)
        self.assertEqual(outcome.data["price"], 34)
        self.assertEqual(outcome.data["stock"], 30)
        self.assertEqual(outcome.data["stock_before"], "1", "必须记下写入前的既有值")

    def test_price_formatting_is_stable(self) -> None:
        """回读是逐字符比对，格式不稳会让校验随机失败。"""

        self.assertEqual(stages._format_price(16.8), "16.80")
        self.assertEqual(stages._format_price(16.80), "16.80")
        self.assertEqual(stages._format_price(16), "16.00")
        self.assertEqual(stages._format_price(16.799), "16.80")


class ExpressionBuildersSmokeTest(unittest.TestCase):
    """**每个**表达式构造器都必须能跑通。

    这条用例是有来历的：``confirm_category_and_read_id`` 里原先内联了一段 JS，
    开头写成单花括号 ``(() => {``，``str.format`` 直接抛
    ``unexpected '{' in field name``。内联时它不在任何单测覆盖里，直到实机跑才炸。
    把构造器都提出来并逐个调用，这类错误就不用等到实机。
    """

    def test_every_builder_runs_without_raising(self) -> None:
        builders = [
            ("set_value", lambda: page.build_set_expression("款号", "X")),
            ("read_value", lambda: page.build_read_expression("款号")),
            ("click_unique_text", lambda: page.build_click_unique_text_expression(".x", "y")),
            ("select_brand", lambda: page.build_select_brand_expression("B")),
            ("pick_brand_option", lambda: page.build_pick_brand_option_expression("B")),
            ("search_in_brand_dropdown", lambda: page.build_search_in_brand_dropdown_expression("B")),
            ("click_confirm_next", lambda: page.build_click_confirm_next_expression()),
            ("open_freight", lambda: page.build_open_freight_expression()),
            ("read_freight_options", lambda: page.build_read_freight_options_expression()),
            ("pick_freight_option", lambda: page.build_pick_freight_option_expression("T")),
            ("read_freight_value", lambda: page.build_read_freight_value_expression()),
            ("locate_row", lambda: locating.locate_row_expression("面料")),
            ("operate_row", lambda: locating.operate_row_expression("面料", "0;")),
            ("locate_button", lambda: locating.locate_button_expression("保存草稿")),
            ("operate_button", lambda: locating.operate_button_expression("保存草稿", "0;")),
            ("locate_anchor", lambda: locating.locate_text_anchor_expression("运费模板")),
        ]
        for name, builder in builders:
            with self.subTest(builder=name):
                result = builder()
                self.assertIsInstance(result, str)
                self.assertTrue(result.strip())

    def test_no_javascript_is_built_inline_inside_page_module(self) -> None:
        """**凡是要过 ``.format`` 的 JS，一律写成命名构造器。**

        这条规则是踩出来的：单花括号 ``(() => {`` 会让 ``str.format`` 抛
        ``unexpected '{' in field name``，而**内联的表达式不在任何单测覆盖里**——
        同一类错误在这个模块里出现过**三次**（`confirm_category_and_read_id`、
        `read_freight_template`、`PageClient.set_file_input_files`），
        三次都是直到实机才炸。

        第三次的教训：只查 ``evaluate(\"\"\"`` 不够。那次是
        ``"(() => { ... }})()".format(...)``——字符串拼接后直接 ``.format()``，
        既没有三引号也不在构造器里，静态检查漏掉了，于是 `upload_images` 一跑就炸。

        ⚠️ **判定要认「是不是 JS」，不能见 ``.format()`` 就报**：
        本模块里绝大多数 ``.format()`` 是**中文错误消息**的占位符替换，完全正常。
        所以这里只在字符串**带有 JS 特征**（箭头函数、``document.``、
        ``getBoundingClientRect``、``querySelector``）时才判定为内联 JS。
        用 ``tests/check_all_builders.py`` 真的调一遍，是这条静态检查的运行时补充。
        """

        import ast

        js_markers = ("(() =>", "=>", "document.", "getBoundingClientRect", "querySelector")

        def js_literal_source(node: ast.AST) -> Optional[str]:
            """字符串字面量（含隐式/显式拼接、f-string）里若有 JS 特征就返回它。"""

            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                return node.value
            if isinstance(node, ast.JoinedStr):
                return "".join(
                    part.value for part in node.values
                    if isinstance(part, ast.Constant) and isinstance(part.value, str)
                )
            if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
                left = js_literal_source(node.left)
                right = js_literal_source(node.right)
                if left is None or right is None:
                    return None
                return left + right
            return None

        def looks_like_js(text: Optional[str]) -> bool:
            return bool(text) and any(marker in text for marker in js_markers)

        source = (Path(__file__).resolve().parents[1] / "taobao_publish" / "page.py").read_text(encoding="utf-8")
        tree = ast.parse(source)

        offenders: list = []
        for function in ast.walk(tree):
            if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            # 构造器允许（它们就是干这个的），而且 check_all_builders.py 会真的调一遍
            if function.name.startswith("build_"):
                continue
            for node in ast.walk(function):
                # ① 对 JS 字符串直接 .format()
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                        and node.func.attr == "format" \
                        and looks_like_js(js_literal_source(node.func.value)):
                    offenders.append("{}() 第 {} 行：内联 JS 后直接 .format()".format(
                        function.name, node.lineno))
                # ② 把 JS 存进变量再交给 evaluate
                if isinstance(node, ast.Assign) and looks_like_js(
                        js_literal_source(node.value)) and isinstance(node.value, (ast.Constant, ast.JoinedStr)):
                    offenders.append("{}() 第 {} 行：内联 JS 赋值给变量".format(
                        function.name, node.lineno))

        self.assertEqual(
            offenders, [],
            "以下位置仍内联 JS 表达式，请提成命名构造器以便被本用例与 "
            "tests/check_all_builders.py 覆盖：\n  " + "\n  ".join(offenders),
        )

    def test_inline_evaluate_calls_are_extracted(self) -> None:
        """``evaluate(\"\"\"`` 这种内联写法同样不允许。"""

        source = (Path(__file__).resolve().parents[1] / "taobao_publish" / "page.py").read_text(encoding="utf-8")
        offenders = [
            index + 1 for index, line in enumerate(source.splitlines())
            if "evaluate(" in line and '"""' in line
        ]
        self.assertEqual(
            offenders, [],
            "page.py 第 {} 行仍内联 JS 表达式；请提成命名构造器以便被本用例覆盖".format(offenders),
        )

    def test_no_unformatted_double_braces_leak_into_output(self) -> None:
        """``.format`` 之后不该再残留 ``{{``/``}}``——那说明有地方漏了转义。"""

        for name, builder in [
            ("set_value", lambda: page.build_set_expression("款号", "X")),
            ("click_confirm_next", lambda: page.build_click_confirm_next_expression()),
            ("select_brand", lambda: page.build_select_brand_expression("B")),
            ("locate_row", lambda: locating.locate_row_expression("面料")),
        ]:
            with self.subTest(builder=name):
                output = builder()
                self.assertNotIn("{{", output, "{} 残留了未转义的花括号".format(name))
                self.assertNotIn("}}", output, "{} 残留了未转义的花括号".format(name))

    def test_confirm_next_expression_targets_the_measured_button_text(self) -> None:
        expression = page.build_click_confirm_next_expression()
        self.assertIn(json.dumps(page.CONFIRM_NEXT_TEXT, ensure_ascii=False), expression)
        # 禁用时不得点击
        self.assertIn("btns[0].disabled", expression)


class CategoryPageActionsTest(unittest.TestCase):
    def test_click_unique_text_rejects_zero_matches(self) -> None:
        client = FakeClient([{"ok": False, "reason": "no_match", "seen": []}])
        with self.assertRaises(page.CandidateNotFound):
            page.click_unique_text(client, ".x", "不存在")

    def test_click_unique_text_rejects_ambiguity(self) -> None:
        """实测「一次性袜子」同时是两个候选的结尾——包含匹配会随机命中一个。"""

        client = FakeClient([{"ok": False, "reason": "ambiguous", "hitCount": 2}])
        with self.assertRaises(locating.LabelAmbiguous):
            page.click_unique_text(client, ".x", "一次性袜子")

    def test_click_unique_text_returns_the_clicked_text(self) -> None:
        client = FakeClient([{"ok": True, "clickedText": "甲", "clickedClass": "c"}])
        result = page.click_unique_text(client, ".x", "甲")
        self.assertEqual(result["clickedText"], "甲")

    def test_candidate_selector_targets_the_text_element_not_an_ancestor(self) -> None:
        """实测教训：handler 在文本元素自己身上，点祖先卡片静默无效。"""

        self.assertEqual(page.CATEGORY_CANDIDATE_SELECTOR, ".sell-rich-text.path-text")
        self.assertNotIn("result-item", page.CATEGORY_CANDIDATE_SELECTOR)
        self.assertNotIn("wrap", page.CATEGORY_CANDIDATE_SELECTOR)

    def test_find_exact_candidate_requires_exactly_one(self) -> None:
        client = FakeClient([{"target": "甲", "hitCount": 0, "candidates": ["乙", "丙"]}])
        with self.assertRaises(page.CandidateNotFound) as ctx:
            page.find_exact_category_candidate(client, "甲")
        self.assertIn("精确命中 0 个", str(ctx.exception))

    def test_select_brand_reports_what_it_saw_when_missing(self) -> None:
        """品牌选错会直接挂错品牌，所以失败时必须报出当时可见的选项。"""

        client = FakeClient([
            {"ok": True},                                   # 展开
            {"ok": True, "typed": "B"},                     # 搜索
            {"ok": False, "reason": "no_match", "shown": ["A", "C"]},  # 未命中
        ])
        with mock.patch("taobao_publish.page.time.sleep"), self.assertRaises(page.CandidateNotFound) as ctx:
            page.select_brand(client, "B", wait=0)
        self.assertIn("A", str(ctx.exception))

    def test_select_brand_raises_when_the_dropdown_cannot_open(self) -> None:
        client = FakeClient([{"ok": False, "step": "locate-brand-row", "reason": "not_found"}])
        with self.assertRaises(page.CandidateNotFound):
            page.select_brand(client, "B", wait=0)

    def test_wait_for_selected_category_polls_until_it_matches(self) -> None:
        """「点完马上读」会拿到空数组，看起来像点击没生效——实测踩过。"""

        client = FakeClient([
            "[]",                                              # 太早
            json.dumps(["甲", "乙"]),                           # 还是不全
            json.dumps(["甲", "乙", "丙"]),                     # 对了
        ])
        with mock.patch("taobao_publish.page.time.sleep"):
            result = page.wait_for_selected_category(client, ["甲", "乙", "丙"], timeout=5.0)
        self.assertEqual(result, ["甲", "乙", "丙"])
        self.assertEqual(len(client.expressions), 3, "应当轮询而不是只读一次")

    def test_wait_for_selected_category_returns_last_read_on_timeout(self) -> None:
        # 轮询会一直读到超时，所以这里需要「永远返回同一个值」的替身，
        # 而不是 FakeClient（它按预设列表逐条消费，耗尽即断言失败）。
        class AlwaysEmpty:
            def __init__(self):
                self.calls = 0

            def evaluate(self, expression, timeout=15.0):
                self.calls += 1
                return "[]"

        client = AlwaysEmpty()
        with mock.patch("taobao_publish.page.time.sleep"):
            result = page.wait_for_selected_category(client, ["甲"], timeout=0.001)
        self.assertEqual(result, [])
        self.assertGreaterEqual(client.calls, 1)


class StageSelectCategoryTest(unittest.TestCase):
    def _ctx(self, path=("甲", "乙")):
        item = PublishItem(record_id=1, record_name="x", title="标题")
        item.category.path = path
        return stages.PipelineContext(item=item, dry_run=False)

    def test_missing_target_path_is_a_structured_failure(self) -> None:
        with mock.patch.object(stages, "_open_publish_page") as opener:
            outcome = stages.stage_select_category(self._ctx(path=()))
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.error_code, "EVIDENCE_INSUFFICIENT")
        opener.assert_not_called()

    def test_stage_delegates_to_the_page_layer(self) -> None:
        """阶段必须走 page 里的动作，而不是自己拼表达式。"""

        source = __import__("inspect").getsource(stages.stage_select_category)
        for name in ("search_category", "switch_category_tab",
                     "find_exact_category_candidate", "click_unique_text",
                     "wait_for_selected_category", "confirm_category_and_read_id"):
            self.assertIn(name, source, "阶段应当调用 page.{}".format(name))

    def test_brand_comes_from_the_props_entry(self) -> None:
        source = __import__("inspect").getsource(stages.stage_select_category)
        self.assertIn('prop_name == "品牌"', source)

    def test_brand_required_is_reported_instead_of_silently_proceeding(self) -> None:
        """不选品牌时「确认，下一步」永远 disabled——必须报出来，不能装作走过去了。"""

        source = __import__("inspect").getsource(stages.stage_select_category)
        self.assertIn("BRAND_REQUIRED", source)

    def test_selection_is_confirmed_before_proceeding(self) -> None:
        source = __import__("inspect").getsource(stages.stage_select_category)
        self.assertIn("SELECTION_NOT_CONFIRMED", source)


class ExpectedFieldValuesTest(unittest.TestCase):
    """填表与回读必须用**同一份**期望值，否则「回读总对不上」会让人先去怀疑页面。"""

    def _ctx(self, **kwargs):
        item = PublishItem(record_id=1, record_name="x", **kwargs)
        return stages.PipelineContext(item=item, dry_run=False)

    def test_title_and_outer_id_are_included_when_present(self) -> None:
        ctx = self._ctx(title="标题", outer_id="OUT-1")
        labels = {e["label"]: e["value"] for e in stages.expected_field_values(ctx)}
        self.assertEqual(labels["宝贝标题"], "标题")
        self.assertEqual(labels["商家编码"], "OUT-1")

    def test_blank_outer_id_is_omitted(self) -> None:
        ctx = self._ctx(title="标题", outer_id="   ")
        labels = [e["label"] for e in stages.expected_field_values(ctx)]
        self.assertNotIn("商家编码", labels)

    def test_props_are_included(self) -> None:
        ctx = self._ctx(title="标题", props=[PropEntry("面料", "棉"), PropEntry("厚薄", "常规")])
        labels = {e["label"]: e["value"] for e in stages.expected_field_values(ctx)}
        self.assertEqual(labels["面料"], "棉")
        self.assertEqual(labels["厚薄"], "常规")

    def test_price_uses_the_lowest_and_stock_the_sum(self) -> None:
        ctx = self._ctx(title="标题", skus=[
            SkuEntry({"颜色": "黑"}, price=19.9, stock=5),
            SkuEntry({"颜色": "白"}, price=16.8, stock=7),
        ])
        labels = {e["label"]: e["value"] for e in stages.expected_field_values(ctx)}
        self.assertEqual(labels["一口价"], "34.00")
        self.assertEqual(labels["总库存"], "12")

    def test_price_formatting_matches_the_fill_stage(self) -> None:
        """回读是逐字符比对，两边格式必须完全一致。"""

        ctx = self._ctx(title="标题", skus=[SkuEntry({"颜色": "黑"}, price=16.8, stock=1)])
        labels = {e["label"]: e["value"] for e in stages.expected_field_values(ctx)}
        self.assertEqual(labels["一口价"], stages._format_price(34))

    def test_empty_item_yields_nothing(self) -> None:
        """空 item **没有字段类期望**。

        ⚠️ 但**结构性那一项仍在**（「提交按钮」）——它本来就不依赖 item 有没有内容：
        空表单跑出来的结果恰恰是「按钮不可点」，那正是要报出来的东西。
        """

        entries = stages.expected_field_values(
            stages.PipelineContext(
                item=PublishItem(record_id=1, record_name="x"), dry_run=False))
        field_like = [e for e in entries if e["kind"] not in ("submit_ready",)]
        self.assertEqual(field_like, [], "空 item 不该有字段类期望")
        self.assertEqual([e["kind"] for e in entries], ["submit_ready"])

    def setUp(self) -> None:
        # ⚠️ **统一打桩提交按钮状态。**
        #
        # `readback` 现在**总是**核对「提交按钮」（平台自身的完整性判断，
        # 见 `tests/test_readback_submit_ready.py`）。这些用例验的是**逐字段核对**，
        # 不该因为多了一项而到处补脚本响应。
        #
        # 想让新项失败的用例，去 `test_readback_submit_ready.py`。
        patcher = mock.patch.object(
            page, "read_submit_state",
            return_value={"submit": {"present": True, "disabled": False,
                                     "visible": True}})
        patcher.start()
        self.addCleanup(patcher.stop)

        required_patcher = mock.patch.object(page, "read_required_properties", return_value={
            "known": True, "rowCount": 1, "scope": "visible_property_label_required",
            "completePage": False, "required": [],
        })
        required_patcher.start()
        self.addCleanup(required_patcher.stop)
        form_patcher = mock.patch.object(page, "read_required_form", return_value={'known': True, 'scope': 'visible_publish_rows_required', 'completePage': False, 'rowCount': 1, 'required': [], 'unownedRequiredCount': 0})
        form_patcher.start()
        self.addCleanup(form_patcher.stop)

    def _ctx(self, **kwargs):
        item = PublishItem(record_id=1, record_name="x", **kwargs)
        return stages.PipelineContext(item=item, dry_run=False)

    def test_all_matching_passes(self) -> None:
        # read_text_field 期望 evaluate 返回 {ok, label, value} 结构
        client = FakeClient([
            {"ok": True, "label": "宝贝标题", "value": "标题"},
            {"ok": True, "label": "商家编码", "value": "OUT-1"},
        ])
        with mock.patch.object(stages, "_open_publish_page", return_value=client):
            outcome = stages.stage_readback(self._ctx(title="标题", outer_id="OUT-1"))
        self.assertTrue(outcome.ok)
        self.assertIn("全部一致", outcome.summary)

    def test_mismatch_is_a_blocker_not_a_warning(self) -> None:
        """「填了但没生效」必须报出来——只报成功等于把结果交给运气。"""

        client = FakeClient([{"ok": True, "label": "宝贝标题", "value": "被平台改过了"}])
        with mock.patch.object(stages, "_open_publish_page", return_value=client):
            outcome = stages.stage_readback(self._ctx(title="我的标题"))
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.error_code, "READBACK_FAILED")
        codes = {b.code for b in outcome.blockers}
        self.assertIn("READBACK_MISMATCH", codes)
        self.assertIn("被平台改过了", outcome.blockers[0].detail)

    def test_unreadable_field_is_also_a_blocker(self) -> None:
        """定位失效或字段不在了，同样不能当作通过。"""

        # **两条响应**：第一条给 `read_text_field`（发布页组合，定位不到），
        # 第二条给属性行退路 `read_prop_value`——两条都读不到才叫读不到。
        client = FakeClient([
            {"ok": False, "reason": "label_not_found", "hitCount": 0},
            {"ok": False, "hitCount": 0},
        ])
        with mock.patch.object(stages, "_open_publish_page", return_value=client):
            outcome = stages.stage_readback(self._ctx(title="标题"))
        self.assertFalse(outcome.ok)
        self.assertIn("READBACK_UNREADABLE", {b.code for b in outcome.blockers})

    def test_whitespace_only_difference_is_accepted(self) -> None:
        """下拉框读回的是显示文本，平台可能补空格——比对前 strip 是必要的宽容。"""

        # 只放一条期望值：期望值条数必须与替身响应对齐
        client = FakeClient([{"ok": True, "label": "面料", "value": "  棉  "}])
        with mock.patch.object(stages, "_open_publish_page", return_value=client):
            outcome = stages.stage_readback(self._ctx(props=[PropEntry("面料", "棉")]))
        self.assertTrue(outcome.ok)

    def test_no_expectations_is_a_structured_failure(self) -> None:
        """「没有可核对的东西」必须**显式失败**，不能静默通过。

        ⚠️ 这条路径现在**走不到了**——`expected_field_values` 总会给出
        「提交按钮」那一项（结构性检查，不依赖 item 有没有内容）。

        **但守卫要留**（防御性的：将来若它又可能返回空），所以这里
        直接验守卫的语义，而不是靠构造一个空 item。
        """

        real = stages.expected_field_values

        with mock.patch.object(stages, "expected_field_values", return_value=[]):
            with mock.patch.object(stages, "_open_publish_page") as opener:
                outcome = stages.stage_readback(self._ctx(title="标题"))
        self.assertFalse(outcome.ok)
        # 实际用的是 EVIDENCE_INSUFFICIENT——「没有可核对的东西」属于证据不足
        self.assertEqual(outcome.error_code, "EVIDENCE_INSUFFICIENT")
        # 没有可核对的东西时**不该去开页面**
        opener.assert_not_called()
        self.assertTrue(real)  # 保留引用，避免被 lint 当成未使用

    def test_client_is_always_closed(self) -> None:
        # 同上：属性行退路会多调一次，替身要备两条。
        client = FakeClient([
            {"ok": False, "reason": "label_not_found"},
            {"ok": False, "hitCount": 0},
        ])
        with mock.patch.object(stages, "_open_publish_page", return_value=client):
            stages.stage_readback(self._ctx(title="标题"))
        self.assertTrue(client.closed)

    def test_readback_is_registered_as_read_only_and_runs_in_dry_run(self) -> None:
        spec = stages.STAGE_HANDLERS["readback"]
        self.assertIsNone(spec.write_operation)
        self.assertFalse(spec.mutates_page, "readback 只读，dry-run 下应当照常执行")


    def test_read_freight_value_prefers_aria_valuetext(self) -> None:
        """实测：Fusion 的 Select 把选中项放在 **``aria-valuetext``**，``input.value`` 是空的。

        只看 ``value`` 会永远读到空，然后把「读不到」误判成「选择没生效」——
        这正是实机第一次跑 ``fill_freight`` 时报 ``READBACK_MISMATCH`` 的原因。
        """

        expression = page.build_read_freight_value_expression()
        self.assertIn("aria-valuetext", expression)
        # 三个来源都要试，且 aria 优先
        self.assertLess(expression.index("aria-valuetext"), expression.index("c.value"))
        self.assertIn("em", expression)

    def test_freight_dropdown_container_covers_both_variants(self) -> None:
        """两种下拉容器类名不同——只认一种会报「下拉没打开」，而它其实开了。"""

        joined = " ".join(page.FREIGHT_DROPDOWN_SELECTORS)
        self.assertIn("next-select-single-menu", joined)
        self.assertIn("next-select-popup-wrap", joined)
        # 不要 .next-menu 本身：那会抓到顶部导航栏
        self.assertNotIn(".next-menu ", joined)
        self.assertNotIn('".next-menu"', joined)

    def test_pick_freight_option_reports_available_names(self) -> None:
        """选错模板会按别人的运费规则发货，失败时必须报出可选项。"""

        client = FakeClient([{"ok": False, "reason": "no_match", "shown": ["极兔快递", "系统模板-商家默认模板"]}])
        with self.assertRaises(page.OptionNotFound) as ctx:
            page.pick_freight_option(client, "不存在")
        self.assertIn("极兔快递", str(ctx.exception))

    def test_pick_freight_option_rejects_ambiguity(self) -> None:
        client = FakeClient([{"ok": False, "reason": "ambiguous", "hitCount": 2}])
        with self.assertRaises(page.OptionNotFound):
            page.pick_freight_option(client, "同名模板")


class StageFillFreightTest(unittest.TestCase):
    def _ctx(self, name=""):
        item = PublishItem(record_id=1, record_name="x", title="标题", freight_template_name=name)
        return stages.PipelineContext(item=item, dry_run=False)

    def test_missing_template_name_is_a_structured_failure(self) -> None:
        client = FakeClient([{"ok": True, "value": ""}])
        with mock.patch.object(stages, "_open_publish_page", return_value=client) as opener:
            outcome = stages.stage_fill_freight(self._ctx(""))
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.error_code, "EVIDENCE_INSUFFICIENT")
        opener.assert_called_once()

    def test_name_not_in_options_is_refused_with_the_available_list(self) -> None:
        """**这条是 fail-closed 的核心**：模板名对不上时把可选项列出来，不猜一个最接近的。"""

        client = FakeClient([
            {"ok": True, "value": "极兔快递"},                       # read_freight_template
            {"ok": True, "current": "极兔快递"},                      # open
            {"ok": True, "options": [{"text": "极兔快递"}, {"text": "系统模板-商家默认模板"}]},
        ])
        with mock.patch.object(stages, "_open_publish_page", return_value=client):
            outcome = stages.stage_fill_freight(self._ctx("根本不存在的模板"))
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.error_code, "FREIGHT_TEMPLATE_NOT_FOUND")
        self.assertIn("极兔快递", outcome.summary)

    def test_empty_option_list_is_refused(self) -> None:
        client = FakeClient([
            {"ok": True, "value": "极兔快递"},
            {"ok": True, "current": "极兔快递"},
            {"ok": False, "reason": "no_visible_dropdown"},
        ])
        with mock.patch.object(stages, "_open_publish_page", return_value=client):
            outcome = stages.stage_fill_freight(self._ctx("极兔快递"))
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.error_code, "EVIDENCE_INSUFFICIENT")

    def test_readback_mismatch_is_refused(self) -> None:
        """选完回读对不上时必须失败——不要在这个状态下继续发布。"""

        # 回读走的是**轮询**（wait_for_freight_value），预设响应会被耗尽；
        # 所以这里用「耗尽后重复最后一条」的替身，模拟「值一直没变」。
        class StickyClient:
            def __init__(self, responses):
                self.responses = list(responses)

            def evaluate(self, expression, timeout=15.0):
                if len(self.responses) > 1:
                    return self.responses.pop(0)
                return self.responses[0]

            def close(self):
                pass

        client = StickyClient([
            {"ok": True, "value": "极兔快递"},          # read_freight_template（写入前）
            {"ok": True, "current": "极兔快递"},          # open
            {"ok": True, "options": [{"text": "极兔快递"}, {"text": "系统模板-商家默认模板"}]},
            {"ok": True, "picked": "系统模板-商家默认模板"},
            {"ok": True, "value": "极兔快递"},           # 之后一直是旧值 → 回读必然不一致
        ])
        with mock.patch.object(stages, "_open_publish_page", return_value=client), \
                mock.patch("taobao_publish.page.time.sleep"):
            outcome = stages.stage_fill_freight(self._ctx("系统模板-商家默认模板"))
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.error_code, "READBACK_MISMATCH")


class SubmitButtonTest(unittest.TestCase):
    """提交是唯一真正把商品推上平台的动作，守卫要最严。"""

    def test_read_state_expression_is_read_only(self) -> None:
        expression = page.build_read_submit_state_expression()
        self.assertIn("getBoundingClientRect", expression)
        self.assertNotIn(".click()", expression)

    def test_click_expression_gates_before_clicking(self) -> None:
        expression = page.build_click_submit_expression()
        gate = expression.index("btns.length !== 1 || visible.length !== 1")
        self.assertLess(gate, expression.index(".click()"))
        # 禁用状态也必须在点击之前拦住
        self.assertIn("disabled", expression)

    def test_click_refuses_when_disabled(self) -> None:
        client = FakeClient([{"ok": False, "reason": "disabled", "hitCount": 1, "visibleCount": 1}])
        with self.assertRaises(page.PageError) as ctx:
            page.click_submit_button(client)
        self.assertIn("disabled", str(ctx.exception))

    def test_click_refuses_on_ambiguity(self) -> None:
        client = FakeClient([{"ok": False, "reason": "ambiguous", "hitCount": 2, "visibleCount": 2}])
        with self.assertRaises(page.PageError):
            page.click_submit_button(client)

    def test_outcome_reader_does_not_judge_success(self) -> None:
        """读结果只报「看到了什么」，不判断成功与否——判断交给人工。"""

        expression = page.build_read_submit_outcome_expression()
        self.assertIn("messages", expression)
        self.assertNotIn("success", expression.lower())

    def test_all_expression_builders_run(self) -> None:
        for builder in (page.build_read_submit_state_expression,
                        page.build_click_submit_expression,
                        page.build_read_submit_outcome_expression):
            with self.subTest(builder=builder.__name__):
                output = builder()
                self.assertTrue(output.strip())
                self.assertNotIn("{{", output)


class StageSubmitTest(unittest.TestCase):
    def _ctx(self, *, readback_passed: bool = True):
        """造一个上下文。

        ⚠️ **默认塞入一份「回读通过」的结果**：`submit` 现在把回读当作
        **硬前置条件**（见 `test_submit_guards.py`），没有它就直接拒绝。
        这些用例验的是提交阶段本身的行为，所以要把前置条件补齐——
        它们原先能过，正是因为当时**没有**这道守卫。
        """

        item = PublishItem(record_id=1, record_name="x", title="标题")
        ctx = stages.PipelineContext(item=item, dry_run=False)
        if readback_passed:
            ctx.scratch["readback"] = {
                "matched": [{"label": "宝贝标题", "value": "标题"}],
                "mismatched": [],
                "unreadable": [],
            }
        return ctx

    def test_missing_button_is_a_structured_failure(self) -> None:
        client = FakeClient([{"submit": {"present": False, "hitCount": 0}}])
        with mock.patch.object(stages, "_open_publish_page", return_value=client):
            outcome = stages.stage_submit(self._ctx())
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.error_code, "PAGE_ERROR")

    def test_disabled_button_is_refused_without_clicking(self) -> None:
        """禁用通常意味着必填项没填完。这里不猜是哪一项，也不硬点。"""

        client = FakeClient([{"submit": {"present": True, "disabled": True}}])
        with mock.patch.object(stages, "_open_publish_page", return_value=client):
            outcome = stages.stage_submit(self._ctx())
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.error_code, "SUBMIT_BLOCKED_BY_FORM")
        # 只读了一次状态，没有发点击请求
        self.assertEqual(len(client.expressions), 1)

    def test_never_claims_publish_success(self) -> None:
        """**核心不变量**：点了按钮 ≠ 发布成功。

        提交通道的成功特征尚未实证，所以任何情况下都不能把 ok=True 报成「已上架」。
        """

        client = FakeClient([
            {"submit": {"present": True, "disabled": False}, "href": "https://item.upload.taobao.com/sell/v2/publish.htm?catId=1"},
            # 点击**前**的基线：现在会先读一次提示，做差用。
            # 这些是页面本来就有的说明文字——**不能**当成「提交的结果」。
            {"href": "https://item.upload.taobao.com/sell/v2/publish.htm?catId=1", "messages": [{"text": "页面本来就有的说明文字"}]},
            {"ok": True},                                     # click
            {"href": "https://item.upload.taobao.com/sell/v2/publish.htm?catId=1&done=1",
             "messages": []},                                 # outcome：URL 变了
        ])
        with mock.patch.object(stages, "_open_publish_page", return_value=client), \
                mock.patch("taobao_publish.page.time.sleep"):
            outcome = stages.stage_submit(self._ctx())
        self.assertTrue(outcome.ok)
        self.assertIs(outcome.data["publish_confirmed"], False)
        self.assertIn("不声称发布成功", outcome.summary)
        self.assertIn("卖家中心", outcome.data["confirmation_required"])

    def test_no_observable_change_is_reported_honestly(self) -> None:
        """点完什么都没变时，如实说「没观察到变化」，不说成功也不说失败。"""

        same = "https://item.upload.taobao.com/sell/v2/publish.htm"
        client = FakeClient([
            {"submit": {"present": True, "disabled": False}, "href": same},
            {"href": same, "messages": [{"text": "本来就有的"}]},
            {"ok": True},
            {"href": same, "messages": []},   # 之后一直如此
        ])

        class Sticky:
            def __init__(self, responses):
                self.responses = list(responses)

            def evaluate(self, expression, timeout=15.0):
                if len(self.responses) > 1:
                    return self.responses.pop(0)
                return self.responses[0]

            def close(self):
                pass

        sticky = Sticky([
            {"submit": {"present": True, "disabled": False}, "href": same},
            # 点击**前**的基线：页面本来就有的提示，**不能**当成「提交的结果」。
            {"href": same, "messages": [{"text": "本来就有的说明文字"}]},
            {"ok": True},
            {"href": same, "messages": []},
        ])
        _ = client
        with mock.patch.object(stages, "_open_publish_page", return_value=sticky), \
                mock.patch("taobao_publish.page.time.sleep"):
            outcome = stages.stage_submit(self._ctx())
        self.assertTrue(outcome.ok)
        self.assertIs(outcome.data["navigated"], False)
        self.assertIn("没有观察到页面变化", outcome.summary)
        self.assertIs(outcome.data["publish_confirmed"], False)

    def test_enabled_button_is_not_treated_as_a_valid_form(self) -> None:
        """**实测反直觉事实**：按钮可用 ≠ 表单填完了。

        2026-10-03 的守卫验证里，宝贝标题是空的、提交按钮却仍是 enabled——
        平台是在点击之后才做校验的。所以「按钮禁用」是否决信号，
        但「按钮可用」**不是**放行信号；真正的前置校验归 readback 阶段。

        ⚠️ 这条用例原先断言的是「readback 没跑过也照样放行，只是如实报 0」——
        **那正是被关掉的那个洞**。现在没有通过的回读核对就直接拒绝，
        连页面都不连。见 `test_submit_guards.py`。
        """

        ctx = self._ctx(readback_passed=False)
        with mock.patch.object(stages, "_open_publish_page") as opener:
            outcome = stages.stage_submit(ctx)
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.error_code, "SUBMIT_WITHOUT_READBACK")
        self.assertFalse(opener.called, "前置条件不满足时不该去连页面")

    def test_readback_result_is_carried_into_submit(self) -> None:
        ctx = self._ctx()
        ctx.scratch["readback"] = {"matched": [{"label": "宝贝标题"}] * 4,
                                   "mismatched": [], "unreadable": []}
        same = "https://item.upload.taobao.com/sell/publish.htm"
        client = FakeClient([
            {"submit": {"present": True, "disabled": False}, "href": same},
            {"href": same, "messages": [{"text": "本来就有的"}]},
            {"ok": True},
            {"href": same + "?done=1", "messages": []},
        ])
        with mock.patch.object(stages, "_open_publish_page", return_value=client), \
                mock.patch("taobao_publish.page.time.sleep"):
            outcome = stages.stage_submit(ctx)
        self.assertEqual(outcome.data["readback_checked_fields"], 4)

    def test_submit_is_registered_as_the_most_guarded_operation(self) -> None:
        spec = stages.STAGE_HANDLERS["submit"]
        self.assertEqual(spec.write_operation, "submit_publish")
        self.assertTrue(spec.mutates_page)


class SubmitAuthorizationTest(unittest.TestCase):
    """两把锁：``TAOBAO_UPLOAD_ALLOW_WRITE`` 含 submit_publish **且** ALLOW_SUBMIT 为 "1"。"""

    def _ctx(self, granted, submit_unlocked):
        item = PublishItem(record_id=1, record_name="x", title="标题")
        ctx = stages.PipelineContext(
            item=item, dry_run=False,
            authorization=WriteAuthorization(granted=frozenset(granted), submit_unlocked=submit_unlocked),
        )
        # 这些用例验的是**授权门**，所以要先把「回读通过」这个前置条件补齐，
        # 否则会因为 SUBMIT_WITHOUT_READBACK 提前返回，测不到授权那一段。
        ctx.scratch["readback"] = {
            "matched": [{"label": "宝贝标题", "value": "标题"}],
            "mismatched": [], "unreadable": [],
        }
        return ctx

    def test_write_lock_alone_is_not_enough(self) -> None:
        ctx = self._ctx({"save_draft", "submit_publish"}, submit_unlocked=False)
        run = stages.run_stage("submit", ctx, index=0, total=1, steps=[StepRecord(name="submit")])
        self.assertFalse(run.outcome.ok)
        self.assertEqual(run.outcome.error_code, "SUBMIT_NOT_AUTHORIZED")

    def test_submit_lock_alone_is_not_enough(self) -> None:
        ctx = self._ctx({"save_draft"}, submit_unlocked=True)
        run = stages.run_stage("submit", ctx, index=0, total=1, steps=[StepRecord(name="submit")])
        self.assertFalse(run.outcome.ok)
        self.assertEqual(run.outcome.error_code, "WRITE_NOT_AUTHORIZED")

    def test_both_locks_together_allow_execution(self) -> None:
        """两把锁齐了才放行——放行后会真的点提交，所以这里只验证「不因授权被拒」。"""

        ctx = self._ctx({"save_draft", "submit_publish"}, submit_unlocked=True)
        client = FakeClient([{"submit": {"present": True, "disabled": True}}])
        with mock.patch.object(stages, "_open_publish_page", return_value=client):
            outcome = stages.stage_submit(ctx)
        # 授权过了，卡在「表单没填完」——这正是期望的顺序
        self.assertEqual(outcome.error_code, "SUBMIT_BLOCKED_BY_FORM")

    def test_dry_run_skips_submit_even_with_both_locks(self) -> None:
        item = PublishItem(record_id=1, record_name="x", title="标题")
        ctx = stages.PipelineContext(
            item=item, dry_run=True,
            authorization=WriteAuthorization(frozenset({"submit_publish"}), submit_unlocked=True),
        )
        run = stages.run_stage("submit", ctx, index=0, total=1, steps=[StepRecord(name="submit")])
        self.assertTrue(run.skipped_for_dry_run)


class ScriptedSkuClient:
    """模拟规格抽屉行为的替身。

    两个设计要点，都是被前两版坑出来的：

    1. **按表达式内容分派**，不按调用顺序。``pick_spec_value`` 一次发**两个**调用
       （先开输入框、再点候选），``wait_for_sku_table`` 又会轮询不定次数——
       手数的响应序列一改实现就红。
    2. **状态是会变的**。头一版每次都返回同一份静态状态，于是「加完值」之后
       计数还是 0，把「提交前硬校验」误触发了。这里真的维护一份值表：
       加行就是加一个空行，选值就是往当前行填值。
    """

    def __init__(self, attrs=None, selected=None, values=None, table=None,
                 drawer_opens=True, open_result=None, pick_result=None,
                 confirm_result=None, pick_fails=None, counts=None):
        #: attr 名 → 值列表（None 表示空行）
        self.values = {k: list(v) for k, v in (values or {}).items()}
        for name in (attrs or []):
            self.values.setdefault(name, [])
        #: 被勾选的属性
        self.selected = list(selected if selected is not None else self.values.keys())
        self.attrs = list(attrs or self.values.keys())
        #: 覆盖 header 上的计数，用来模拟「行里有文本但没提交」——E-094 那种状态。
        #: 不覆盖时计数 = 非空行数。
        self.counts = dict(counts or {})
        self.table = table if table is not None else {
            "found": True, "drawerOpen": False, "tableCount": 1,
            "rowCount": max(1, sum(len(v) for v in self.values.values())),
            "rows": [], "tableCount_": 1,
        }
        self.drawer_opens = drawer_opens
        self.open_result = open_result or {"ok": True}
        self.pick_result = pick_result
        #: 让某些值「选不上」：{值: 失败原因}
        self.pick_fails = pick_fails or {}
        self.confirm_result = confirm_result or {"ok": True}
        self.calls: list = []
        self.expressions: list = []
        self._current_attr: Optional[str] = None
        self.sku_numbers = [{"specs": row.get("specs") or [], "price": "", "stock": ""}
                            for row in self.table.get("rows") or []]

    # --- 内部：把值表渲染成页面状态 -------------------------------------
    def _blocks(self):
        return [
            {"name": name,
             "count": self.counts.get(name, sum(1 for v in self.values[name] if v)),
             "rowCount": len(self.values[name]),
             "rowValues": [v or "" for v in self.values[name]]}
            for name in self.attrs
        ]

    def _state(self):
        return {
            "open": self.drawer_opens,
            "props": [{"name": n, "selected": n in self.selected} for n in self.attrs],
            "blocks": self._blocks(),
        }

    def evaluate(self, expression, timeout=15.0):
        self.expressions.append(expression)

        if "let price = null, stock = null" in expression:
            return {"ok": True, "rows": self.sku_numbers}
        if "const setValue =" in expression:
            index = int(re.search(r"const tr = trs\[(\d+)\]", expression).group(1))
            self.sku_numbers[index]["price"] = re.search(r"price: setValue\(controls.price\[0\], '([^']*)'\)", expression).group(1)
            self.sku_numbers[index]["stock"] = re.search(r"stock: setValue\(controls.stock\[0\], '([^']*)'\)", expression).group(1)
            return {"ok": True, "set": {"price": True, "stock": True}}

        if "tableCount" in expression and ".sell-sku-table-wrapper-new" in expression:
            self.calls.append("read_table")
            return self.table
        if "+ 创建规格" in expression:
            self.calls.append("open_drawer")
            return self.open_result
        if "WANT_SELECTED" in expression:
            self.calls.append("set_prop")
            name = re.search(r'const WANT = "([^"]*)"', expression)
            want = "const WANT_SELECTED = true;" in expression
            if name:
                target = name.group(1)
                if want and target not in self.selected:
                    self.selected.append(target)
                    self.values.setdefault(target, [])
                    if target not in self.attrs:
                        self.attrs.append(target)
                elif not want and target in self.selected:
                    self.selected.remove(target)
            return {"ok": True, "changed": True}
        if "button.add" in expression and "no_block" in expression:
            self.calls.append("add_row")
            name = re.search(r'const WANT = "([^"]*)"', expression)
            attr = name.group(1) if name else None
            self.values.setdefault(attr, []).append(None)
            return {"ok": True}
        if "popupsBeforeClick" in expression:
            self.calls.append("open_value_input")
            name = re.search(r'const WANT = "([^"]*)"', expression)
            self._current_attr = name.group(1) if name else None
            return {"ok": True, "popupsBeforeClick": 0}
        if "pops[pops.length - 1]" in expression:
            self.calls.append("pick")
            want = re.search(r'const WANT = "([^"]*)"', expression)
            value = want.group(1) if want else ""
            if value in self.pick_fails:
                return {"ok": False, "reason": self.pick_fails[value], "hitCount": 0, "shown": []}
            rows = self.values.setdefault(self._current_attr, [])
            for index in range(len(rows) - 1, -1, -1):
                if rows[index] is None:
                    rows[index] = value
                    break
            if self.pick_result is not None:
                return self.pick_result
            return {"ok": True, "picked": value}
        if "确认创建" in expression and "no_footer" in expression:
            self.calls.append("confirm")
            return self.confirm_result
        self.calls.append("read_state")
        return self._state()

    def close(self):
        pass


class StageFillSkusTest(unittest.TestCase):
    """``fill_skus``：创建销售规格。

    这里最要紧的两条不变量：
    1. **不需要的属性必须被显式取消勾选**——否则 E-097 的静默失败会挡住创建；
    2. **「点到了确认创建」不算成功**——唯一判据是表格出现且行数符合预期。
    """

    def _ctx(self, skus):
        item = PublishItem(record_id=1, record_name="x", title="标题", skus=skus)
        return stages.PipelineContext(item=item, dry_run=False)

    def _skus(self, specs):
        return [SkuEntry(spec_values=dict(s)) for s in specs]

    def _run(self, client, skus):
        with mock.patch.object(stages, "_open_publish_page", return_value=client), \
                mock.patch("taobao_publish.page.time.sleep"):
            return stages.stage_fill_skus(self._ctx(skus))

    def test_no_spec_values_is_a_structured_failure(self) -> None:
        with mock.patch.object(stages, "_open_publish_page") as opener:
            outcome = stages.stage_fill_skus(self._ctx([SkuEntry(spec_values={})]))
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.error_code, "EVIDENCE_INSUFFICIENT")
        opener.assert_not_called()

    def test_desired_specs_preserves_first_seen_order(self) -> None:
        """表格行序跟着值的加入顺序走，回读要按同样顺序比对。"""

        item = PublishItem(record_id=1, record_name="x", title="t", skus=self._skus([
            {"尺码": "L", "颜色": "黑"},
            {"尺码": "M", "颜色": "白"},
            {"尺码": "L", "颜色": "白"},
        ]))
        desired = stages._desired_specs(item)
        self.assertEqual(list(desired.keys()), ["尺码", "颜色"])
        self.assertEqual(desired["尺码"], ["L", "M"], "重复值只留一次，顺序按首次出现")
        self.assertEqual(desired["颜色"], ["黑", "白"])

    def test_blank_names_and_values_are_dropped(self) -> None:
        item = PublishItem(record_id=1, record_name="x", title="t", skus=self._skus([
            {"尺码": "L", "": "x", "颜色": ""},
        ]))
        desired = stages._desired_specs(item)
        self.assertEqual(list(desired.keys()), ["尺码"])

    def test_unneeded_selected_prop_is_deselected(self) -> None:
        """E-097 的直接对策：`item` 里没有的属性要显式取消勾选。

        否则它会以「已勾选但 0 个值」的状态挡住「确认创建」。
        """

        client = ScriptedSkuClient(
            attrs=["颜色分类", "尺码"],
            selected=["颜色分类", "尺码"],
            values={"颜色分类": [], "尺码": ["L"]},
            table={"found": True, "drawerOpen": False, "tableCount": 1, "rowCount": 1,
                   "rows": [{"specs": ["L"], "inputs": []}]},
        )
        outcome = self._run(client, self._skus([{"尺码": "L"}]))
        self.assertTrue(outcome.ok, outcome.summary)
        self.assertEqual(outcome.data["deselected"], ["颜色分类"])
        self.assertEqual(outcome.data["row_count"], 1)
        # 值已经在块里了，不该再加行
        self.assertNotIn("add_row", client.calls)

    def test_missing_value_triggers_add_row_then_pick(self) -> None:
        """加值必须走 `button.add`（E-095）——不能复用块里已有的输入。"""

        client = ScriptedSkuClient(
            attrs=["尺码"], selected=["尺码"], values={"尺码": []},
            table={"found": True, "drawerOpen": False, "tableCount": 1, "rowCount": 1,
                   "rows": [{"specs": ["L"], "inputs": []}]},
        )
        outcome = self._run(client, self._skus([{"尺码": "L"}]))
        self.assertTrue(outcome.ok, outcome.summary)
        self.assertIn("add_row", client.calls)
        self.assertIn("pick", client.calls)
        self.assertLess(client.calls.index("add_row"), client.calls.index("pick"))

    def test_pick_failure_stops_before_confirming(self) -> None:
        """候选里没有这个值时必须失败——不能默默跳过然后接着创建。

        规格值必须来自平台标准候选项（E-085），自由文本进不去。
        """

        client = ScriptedSkuClient(
            attrs=["尺码"], selected=["尺码"], values={"尺码": []},
            pick_fails={"均码": "no_match"},
        )
        outcome = self._run(client, self._skus([{"尺码": "均码"}]))
        self.assertFalse(outcome.ok)
        self.assertNotIn("confirm", client.calls, "选不上就不该继续点确认创建")

    def test_starved_selected_prop_blocks_before_confirming(self) -> None:
        """**核心保护**：已勾选但没值的属性 → 直接失败，不点确认创建。

        这里模拟的正是 E-094 那种真实状态：**行里有文本，但计数是 0**
        （值填进了输入框却**没有提交**）。这种状态下：

        * 阶段会认为「值已经在块里」，于是**不会**再加行；
        * 但计数仍是 0 → 守卫必须拦住，否则「确认创建」会静默失败（E-097）。

        点下去只会得到一个不出现的结果，所以要在点之前拦住并说清原因。
        """

        client = ScriptedSkuClient(
            attrs=["颜色分类", "尺码"],
            selected=["颜色分类", "尺码"],
            values={"颜色分类": ["黑"], "尺码": ["L"]},
            counts={"颜色分类": 0, "尺码": 1},
        )
        outcome = self._run(client, self._skus([{"尺码": "L", "颜色分类": "黑"}]))
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.error_code, "SKU_SPEC_VALUE_MISSING")
        self.assertIn("颜色分类", outcome.summary)
        # 关键：**没有**去点确认创建
        self.assertNotIn("confirm", client.calls)
        # 值「看起来已经在块里」，所以不该再加行
        self.assertNotIn("add_row", client.calls)

    def test_confirm_without_table_is_a_silent_failure_not_success(self) -> None:
        """点了确认创建但表格没出现 → 必须报失败，不能因为「点到了」就报成功。"""

        client = ScriptedSkuClient(
            attrs=["尺码"], selected=["尺码"], values={"尺码": ["L"]},
            table={"found": True, "drawerOpen": True, "tableCount": 0},
        )
        outcome = self._run(client, self._skus([{"尺码": "L"}]))
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.error_code, "SKU_CREATE_SILENT_FAILURE")
        self.assertIn("confirm", client.calls, "确实点过确认创建——是点了没生效，不是没点")

    def test_row_count_mismatch_is_refused(self) -> None:
        """行数不符说明属性值没全部生效，不能继续往下填价格库存。"""

        client = ScriptedSkuClient(
            attrs=["尺码"], selected=["尺码"], values={"尺码": ["L", "M"]},
            table={"found": True, "drawerOpen": False, "tableCount": 1, "rowCount": 1,
                   "rows": [{"specs": ["L"], "inputs": []}]},
        )
        outcome = self._run(client, self._skus([{"尺码": "L"}, {"尺码": "M"}]))
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.error_code, "READBACK_MISMATCH")
        self.assertIn("期望 2 行", outcome.summary)

    def test_drawer_not_opening_is_a_page_error(self) -> None:
        client = ScriptedSkuClient(
            attrs=["尺码"], values={"尺码": []}, drawer_opens=False,
            open_result={"ok": False, "reason": "not_found", "hitCount": 0},
        )
        outcome = self._run(client, self._skus([{"尺码": "L"}]))
        self.assertFalse(outcome.ok)
        self.assertIn(outcome.error_code, ("CANDIDATE_NOT_FOUND", "PAGE_ERROR"))


class SkuExpressionBuilderTest(unittest.TestCase):
    def test_every_sku_builder_runs_without_raising(self) -> None:
        builders = [
            ("open_drawer", lambda: page.build_open_sku_drawer_expression()),
            ("read_drawer_state", lambda: page.build_read_sku_drawer_state_expression()),
            ("add_spec_row", lambda: page.build_add_spec_row_expression("尺码")),
            ("open_value_input", lambda: page.build_open_spec_value_input_expression("尺码")),
            ("pick_spec_value", lambda: page.build_pick_spec_value_expression("L")),
            ("set_prop_true", lambda: page.build_set_prop_selected_expression("颜色分类", True)),
            ("set_prop_false", lambda: page.build_set_prop_selected_expression("颜色分类", False)),
            ("confirm", lambda: page.build_confirm_sku_expression()),
            ("read_table", lambda: page.build_read_sku_table_expression()),
        ]
        for name, builder in builders:
            with self.subTest(builder=name):
                output = builder()
                self.assertTrue(output.strip())
                self.assertNotIn("{{", output, name)
                self.assertNotIn("}}", output, name)

    def test_pick_takes_the_last_popup(self) -> None:
        """**必须取最后一个弹层**：残留旧弹层时点到的是上次渲染的节点，
        值会填进输入框但不会提交（实测踩过）。"""

        expression = page.build_pick_spec_value_expression("L")
        self.assertIn("pops[pops.length - 1]", expression)
        self.assertIn(".options-item", expression)
        self.assertIn(".info-content", expression)

    def test_pick_uses_standard_option_structure_not_the_freight_one(self) -> None:
        """规格值候选是 `.options-item`/`.info-content`，**不是**运费模板那套
        `li.next-menu-item`/`.next-menu-item-text`（E-090）。"""

        expression = page.build_pick_spec_value_expression("L")
        self.assertNotIn("next-menu-item", expression)

    def test_add_row_uses_the_plus_button(self) -> None:
        """加值必须走 `button.add`——块里的 combobox 是所在行的编辑器，
        反复用它只会改掉同一行的值（E-095）。"""

        expression = page.build_add_spec_row_expression("尺码")
        self.assertIn("button.add", expression)

    def test_read_table_does_not_treat_the_wrapper_as_evidence(self) -> None:
        """容器没创建规格时也存在，所以必须看 table 数量，不能看容器在不在。"""

        expression = page.build_read_sku_table_expression()
        self.assertIn("tableCount", expression)
        self.assertIn(".sell-sku-table-wrapper-new", expression)

    def test_set_prop_false_emits_boolean_literal(self) -> None:
        self.assertIn("const WANT_SELECTED = false;",
                      page.build_set_prop_selected_expression("颜色分类", False))
        self.assertIn("const WANT_SELECTED = true;",
                      page.build_set_prop_selected_expression("颜色分类", True))


class MediaSelectionTest(unittest.TestCase):
    """图片上传/选图。**判据是主图位已填数，不是弹层开不开**（E-109）。"""

    def test_every_media_builder_runs_without_raising(self) -> None:
        builders = [
            ("open_popup", lambda: page.build_open_media_popup_expression()),
            ("open_popup_34", lambda: page.build_open_media_popup_expression("3:4主图")),
            ("read_popup", lambda: page.build_read_media_popup_expression()),
            ("click_entry", lambda: page.build_click_media_entry_expression("本地上传")),
            ("read_file_input", lambda: page.build_read_media_file_input_expression()),
            ("read_space", lambda: page.build_read_media_space_images_expression()),
            ("select_image", lambda: page.build_select_media_image_expression("详情_004.jpg")),
            ("read_slots", lambda: page.build_read_main_slots_expression("1:1主图")),
            ("close_popup", lambda: page.build_close_media_popup_expression()),
        ]
        for name, builder in builders:
            with self.subTest(builder=name):
                output = builder()
                self.assertTrue(output.strip())
                self.assertNotIn("{{", output, name)
                self.assertNotIn("}}", output, name)

    def test_open_popup_keeps_an_already_open_popup(self) -> None:
        """弹层已经开着时不能再点空位——重复点会把已选的图清掉。"""

        expression = page.build_open_media_popup_expression()
        self.assertIn("already: true", expression)
        self.assertLess(
            expression.index("already: true"),
            expression.index("slot.click()"),
            "「已经开着」的判定必须在点击之前",
        )

    def test_select_image_matches_by_filename_and_reports_samples(self) -> None:
        """命中不到时必须把当时可见的卡片列出来——否则不知道是名字不对还是没加载。"""

        expression = page.build_select_media_image_expression("不存在.jpg")
        self.assertIn("PicList_pic_background", expression)
        self.assertIn("cardCount", expression)

    def test_media_card_selector_uses_substring_not_exact_class(self) -> None:
        """**必须用子串匹配，不能用精确类名。**

        实测类名是 `PicList_pic_background__pGTdV`——CSS Modules 的**哈希后缀**。
        写成 `.PicList_pic_background` 是精确匹配，**永远匹配不上**，
        表现为「卡片数 0、报 no_cards」，而列表里明明有 144 张图（实测踩过）。
        """

        self.assertIn("class*=", page.MEDIA_IMAGE_CARD)
        self.assertIn("PicList_pic_background", page.MEDIA_IMAGE_CARD)
        self.assertFalse(
            page.MEDIA_IMAGE_CARD.startswith("."),
            "MEDIA_IMAGE_CARD 不能是精确类名选择器——类名带哈希后缀",
        )

    def test_select_image_scrolls_the_virtualized_list(self) -> None:
        """列表是**虚拟化**的（容器 h=5419 / 可视 384，只渲染约 144 张），
        目标图很可能不在当前窗口里——必须滚动查找，否则会误报 no_match。"""

        expression = page.build_select_media_image_expression("主图_01_1x1.jpg")
        self.assertIn("scrollTop", expression)
        self.assertIn("scrollHeight", expression)

    def test_media_existence_checks_whole_dom_not_the_rendered_window(self) -> None:
        """判断图在不在空间里要查**整页 DOM**，不能只数渲染窗口里的卡片。

        实测列表虚拟化后只渲染约 144 张，而 `innerHTML` 里能找到更多。
        """

        expression = page.build_has_media_image_expression("主图_01_1x1.jpg")
        self.assertIn("innerHTML", expression)
        self.assertIn("includes", expression)

    def test_read_slots_counts_filled_not_popup(self) -> None:
        """**判据是「已填位数」**：实测选完图弹层还开着，看弹层会得出错误结论。"""

        expression = page.build_read_main_slots_expression("1:1主图")
        self.assertIn(".sell-component-material-item-view", expression)
        self.assertIn("image-empty", expression)
        self.assertIn("filled", expression)

    def test_close_popup_is_explicitly_needed(self) -> None:
        """选完图弹层**不会自动关**，后面的阶段会点不到底下的表单。"""

        expression = page.build_close_media_popup_expression()
        self.assertIn("Escape", expression)
        self.assertIn("already: true", expression)

    def test_media_constants_are_the_measured_ones(self) -> None:
        self.assertEqual(page.MEDIA_POPUP, ".sell-component-image-v2-media-popup")
        self.assertEqual(page.MEDIA_SLOT, ".image-empty")
        # 按 URL 匹配 frame，不按 origin（market.m.taobao.com 下有 3 个 iframe）
        self.assertEqual(page.MEDIA_IFRAME_URL_HINT, "sucai-selector-ng")
        self.assertEqual(page.MEDIA_LOCAL_UPLOAD_TEXT, "本地上传")

    def test_frame_context_collects_events_while_enabling_runtime(self) -> None:
        """**不能用 ``send("Runtime.enable")``**：``send`` 丢弃沿途事件，
        而 ``executionContextCreated`` 是在响应**之前**批量发出的——
        用 ``send`` 会把它们全丢掉，表现为「找不到 iframe 上下文」而 iframe 明明开着。
        """

        import ast
        import inspect
        import textwrap

        source = inspect.getsource(page.PageClient.find_frame_context)
        # 去掉 docstring 再看代码——否则会匹配到文档里那句「不能用 self.send(...)」
        tree = ast.parse(textwrap.dedent(source))
        function = tree.body[0]
        body = function.body[1:] if ast.get_docstring(function) else function.body
        code = "\n".join(ast.unparse(node) for node in body)
        self.assertNotIn('self.send("Runtime.enable"', code)
        self.assertIn("Runtime.executionContextCreated", code)

    def test_isolated_world_fallback_exists(self) -> None:
        """事件时序不可靠时要有确定性后备。"""

        self.assertTrue(hasattr(page.PageClient, "create_frame_context"))
        self.assertTrue(hasattr(page.PageClient, "frame_id_for_url"))
        import inspect

        self.assertIn("Page.createIsolatedWorld",
                      inspect.getsource(page.PageClient.create_frame_context))

    def test_set_file_input_files_uses_the_cdp_command(self) -> None:
        """上传走 ``DOM.setFileInputFiles``，绕开原生文件框。"""

        import inspect

        source = inspect.getsource(page.PageClient.set_file_input_files)
        self.assertIn("DOM.setFileInputFiles", source)
        self.assertIn("DOM.requestNode", source)


class StageUploadImagesTest(unittest.TestCase):
    def test_upload_uses_native_batch_capability_and_waits_for_queue(self) -> None:
        """E-118结论已被后续证据纠正；原生能力决定批次，实际队列决定成功。

        行为正反例由test_media_queue_batches覆盖，不能再等待完成前不存在的图库图片。
        """

        import inspect

        source = inspect.getsource(page._upload_staged_files_to_media)
        self.assertIn("inputs[0].get('multiple')", source)
        self.assertIn("client.set_file_input_files(", source)
        self.assertIn("wait_for_media_upload_queue(", source)
        self.assertNotIn("wait_for_media_images", page._upload_staged_files_to_media.__code__.co_names)

    def test_upload_reports_confirmed_and_failed_separately(self) -> None:
        """部分成功必须能被看清——不能只给一个「成功/失败」。"""

        import inspect

        source = inspect.getsource(page._upload_staged_files_to_media)
        for key in ('"confirmed"', '"failed"', '"attempts"'):
            self.assertIn(key, source)


    def _ctx(self, images):
        item = PublishItem(record_id=1, record_name="x", title="t")
        item.images.main = list(images)
        return stages.PipelineContext(item=item, dry_run=False)

    def test_no_images_is_a_structured_failure(self) -> None:
        with mock.patch.object(stages, "_open_publish_page") as opener:
            outcome = stages.stage_upload_images(self._ctx([]))
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.error_code, "EVIDENCE_INSUFFICIENT")
        opener.assert_not_called()

    def test_missing_files_are_refused_before_touching_the_page(self) -> None:
        """文件不存在就早退，别把一个无效路径塞进 file input。"""

        with mock.patch.object(stages, "_open_publish_page") as opener:
            outcome = stages.stage_upload_images(self._ctx([r"C:\definitely\not\here.jpg"]))
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.error_code, "REQUIRED_FIELD_MISSING")
        opener.assert_not_called()



    def test_readback_skips_in_dry_run(self) -> None:
        """**dry-run 下回读没有意义**：写阶段全被跳过，页面是上一次留下的状态。

        实测踩过：一次校对模式的任务以「总库存 期望 '200'，实际 '0'」告终，
        看起来像流水线坏了，其实**什么都没写，本来就无从核对**。
        """

        import inspect

        source = inspect.getsource(stages.stage_readback)
        self.assertIn("ctx.dry_run", source, "回读必须识别 dry-run")
        self.assertLess(source.index("ctx.dry_run"), source.index("expected_field_values("),
                        "dry-run 判定必须在取期望值之前")

class UploadPanelAndSelectionRegressionTest(unittest.TestCase):
    """E-123 / E-124 / E-125 的回归测试。

    这三条都是**实机踩出来的**，而且都属于「代码看起来对、行为却不对」那一类——
    必须有断言钉住，否则下次重构很容易退回去。
    """

    def test_upstream_finish_button_is_part_of_the_upload_flow(self) -> None:
        """E-123：**不点上传面板的「完成」，文件只停在队列里。**

        实测：5 个文件都带 next-icon-success、面板也有「上传成功」，
        但图片空间 144 张卡片里一张都没有它们；点「完成」之后队列 9 → 0、
        5 张全部出现在空间里。

        ⚠️ 上一轮没发现它，是因为探测脚本用**猜的关键词**过滤按钮
        （只找了「上传/确定/确认/开始上传/上传至」）。
        """

        import inspect

        self.assertEqual(page.MEDIA_FINISH_TEXT, "完成")
        source = inspect.getsource(page._upload_staged_files_to_media)
        self.assertIn("click_media_finish(", source, "上传流程必须包含点「完成」")
        expression = page.build_click_media_finish_expression()
        self.assertIn("完成", expression)
        self.assertNotIn("{{", expression)
        self.assertNotIn("}}", expression)

    def test_select_media_image_clicks_the_label_not_the_card(self) -> None:
        """E-124：**要点卡片里的 `<label>`，不是卡片 div。**

        实测结构 `img < .PicList_pic_imgBox < label < .PicList_pic_background`；
        点外层 div 会「匹配到了、点了、什么也没发生」——连点 5 张主图位纹丝不动。
        改成点 label 之后主图位 1 → 5。
        """

        expression = page.build_select_media_image_expression("主图_01_1x1.jpg")
        self.assertIn("clickTarget", expression)
        self.assertIn("card.querySelectorAll('label')", expression)
        # 点击必须经过 clickTarget，不能直接点卡片
        self.assertNotIn(".hits[0].click()", expression)

    def test_open_popup_checks_visibility_not_existence(self) -> None:
        """弹层关闭后**节点仍留在 DOM 里**（只是隐藏）。

        用 `querySelector` 判存在会永远返回 already，弹层从没真正打开，
        后续选图全部落空。所以必须判**可见**。
        """

        expression = page.build_open_media_popup_expression()
        self.assertIn("getBoundingClientRect().height > 0", expression)

    def test_stage_only_fills_empty_slots(self) -> None:
        """已有图片无身份映射时必须保留并停止，不能按张数假定是本商品的图。"""

        import inspect

        source = inspect.getsource(stages.stage_upload_images)
        self.assertIn("before.get(", source)
        self.assertIn("无法核验它们是否对应本商品", source)
        self.assertNotIn("names[:need]", source)

    def test_page_client_has_a_health_check(self) -> None:
        """E-125：渲染进程卡死时要能**明确检测**出来。

        没有它，卡死表现为光秃秃的「等待页面响应超时」——
        看的人分不清是页面卡了还是选择器写错了。
        """

        self.assertTrue(hasattr(page.PageClient, "health_check"))
        import inspect

        source = inspect.getsource(page.PageClient.health_check)
        self.assertIn("1+1", source, "健康检查用一个不可能被缓存/优化的最小表达式")

    def test_session_connects_without_waiting_for_a_form(self) -> None:
        """连接阶段接受类目页；公共入口完成健康检查后才读取事实。"""
        import inspect

        source = inspect.getsource(stages.stage_session)
        open_at = source.index("_open_publish_page(ctx, wait_form=False)")
        facts_at = source.index("fill_snapshot_facts(")
        self.assertLess(open_at, facts_at)
        self.assertIn("RENDERER_HUNG", source)


class WriteOperationDeclarationTest(unittest.TestCase):
    """处理器自称的写操作必须与中央登记表一致——不一致就绕过了授权门。"""

    def test_every_registered_handler_declares_a_consistent_operation(self) -> None:
        for stage, spec in stages.STAGE_HANDLERS.items():
            with self.subTest(stage=stage):
                self.assertEqual(
                    spec.write_operation,
                    STAGE_WRITE_OPERATION.get(stage),
                    "阶段 {!r} 的处理器声明与 STAGE_WRITE_OPERATION 不一致".format(stage),
                )

    def test_new_fill_stages_are_registered_as_writes(self) -> None:
        for stage in ("fill_base", "fill_props", "fill_price_stock"):
            self.assertEqual(stages.STAGE_HANDLERS[stage].write_operation, "save_draft")

    def test_read_only_stages_stay_read_only(self) -> None:
        self.assertIsNone(stages.STAGE_HANDLERS["session"].write_operation)
        self.assertIsNone(stages.STAGE_HANDLERS["precheck"].write_operation)


if __name__ == "__main__":
    unittest.main()

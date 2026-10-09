# -*- coding: utf-8 -*-
"""动作守卫的两项审计：`X[0]` 的强弱守卫、以及**全部点击**的就近守卫。

## 为什么要有第二项

门 6 原先只覆盖「点集合第 0 个」（`X[0].click()`）。但点击还有别的形态：
`someEl.click()`、`root.querySelector(SEL).click()` —— 这些没守卫同样会点错。

## 判据演进过三版，每版的问题都值得记

| 版本 | 判据 | 错在哪 |
|---|---|---|
| 1 | 表达式里**任何位置**有没有守卫 | **没有判别力**——别处有个 `.length !== 1`，所有点击都算有守卫 |
| 2 | 只看最后一个 `if (` 之后 | **把真正的守卫切掉了**——实测 `set_prop_selected` 的守卫在更前面，中间夹着另一个 `if` |
| 3 | 点击前 600 字符内的**精确**守卫 | —— |

第 3 版在 **7 种情形**上自证过：合成 5 种 + 两个**实测误报**的真表达式。

⚠️ 还有一条同样重要：`if (closer) { closer.click(); }` **不该**报——
`closer` 是 `querySelector` 的**单个**元素，`if (closer)` 就是正确的守卫。
「真值守卫」只在判断**集合**时才是问题。
"""

from __future__ import annotations

import pathlib
import sys
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SUBPROJECT = REPO_ROOT / "taobao-publisher"
if str(SUBPROJECT) not in sys.path:
    sys.path.insert(0, str(SUBPROJECT))

from taobao_publish import page, selfcheck  # noqa: E402


class AllClicksAuditTest(unittest.TestCase):
    def test_current_tree_has_no_bare_clicks(self) -> None:
        total, bare = selfcheck.audit_all_clicks()
        self.assertGreater(total, 20, "应当扫到二十多处点击")
        self.assertEqual(bare, [], "这些点击没有就近守卫：\n  " + "\n  ".join(bare))

    def test_audit_detects_a_bare_click(self) -> None:
        """**先证明这个判据会失败**——否则它只是「扫不到东西所以永远通过」。"""

        from unittest import mock

        original = page.build_close_media_popup_expression
        try:
            page.build_close_media_popup_expression = lambda: (
                "(() => { document.querySelector(SEL).click(); return {ok:true}; })()")
            total, bare = selfcheck.audit_all_clicks()
        finally:
            page.build_close_media_popup_expression = original

        self.assertTrue(bare, "光秃点击必须被发现")
        self.assertTrue(any("close_media_popup" in item for item in bare))

    def test_audit_detects_a_lower_bound_guard(self) -> None:
        """`>= 1` **不是**守卫——「至少有一个」和「恰好一个」是两回事。"""

        from unittest import mock

        original = page.build_close_media_popup_expression
        try:
            page.build_close_media_popup_expression = lambda: (
                "(() => { const hits = ALL;"
                " if (hits.length >= 1) { hits[0].click(); } return {ok:true}; })()")
            _, bare = selfcheck.audit_all_clicks()
        finally:
            page.build_close_media_popup_expression = original

        self.assertTrue(bare, "下界守卫必须被算作「没有守卫」")

    def test_two_real_expressions_are_not_false_positives(self) -> None:
        """这两条是**实测误报过**的——判据第二版把它们判错了。

        * `set_prop_selected`：守卫在 `hits.length !== 1`，中间夹着另一个 `if`；
        * `close_media_popup`：`closer` 是 `querySelector` 的**单个**元素。
        """

        for name, expression in (
            ("set_prop_selected",
             page.build_set_prop_selected_expression("材质成分", "棉100%")),
            ("close_media_popup", page.build_close_media_popup_expression()),
        ):
            with self.subTest(expression=name):
                window_has_exact = any(
                    __import__("re").search(pattern, expression)
                    for pattern in (
                        r"\.length\s*(===|!==|==|!=)\s*1",
                        r"getBoundingClientRect\(\)\.height\s*>\s*0",
                        r"if\s*\(\s*!\s*\w+",
                    ))
                self.assertTrue(window_has_exact,
                                "{} 有精确守卫，不该被判成光秃点击".format(name))

    def test_gate_failure_message_points_at_the_expression(self) -> None:
        from unittest import mock

        original = page.build_close_media_popup_expression
        try:
            page.build_close_media_popup_expression = lambda: (
                "(() => { document.querySelector(SEL).click(); return {ok:true}; })()")
            result = selfcheck.check_action_guards()
        finally:
            page.build_close_media_popup_expression = original

        self.assertFalse(result.ok)
        self.assertTrue(any("close_media_popup" in item for item in result.failures),
                        "失败信息要指出是哪个构造器：{}".format(result.failures))


class StrictnessGuardTest(unittest.TestCase):
    def test_exact_guard_list_excludes_lower_bounds(self) -> None:
        """**这一条防的是判据再次变宽。**

        `>= 1` 一旦被算作守卫，这道门就退回第 1 版——没有判别力。
        """

        import inspect

        source = inspect.getsource(selfcheck.audit_all_clicks)
        marker = source.index("exact = (")
        block = source[marker:source.index(")", source.index("reason:", marker))]
        self.assertNotIn(">=", block, "精确守卫里不能有下界判断")
        self.assertNotIn("length\\s*[<>]", block)
        self.assertIn("===|!==|==|!=", block)

    def test_gate_reports_click_count(self) -> None:
        result = selfcheck.check_action_guards()
        self.assertIn("处点击", result.detail)
        self.assertIn("0 处无就近守卫", result.detail)


if __name__ == "__main__":
    unittest.main()

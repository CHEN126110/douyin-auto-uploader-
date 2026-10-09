# -*- coding: utf-8 -*-
"""自检的六道门：**既要全过，也要证明每道门真的会失败**。

⚠️ 只断言「全过」是不够的——上一轮刚踩过：
一条因为**扫不到东西**所以永远通过的元测试，比没有测试更危险。
所以这里每道门都要**造一个反例**证明它能失败。

同时也钉住「门自己抛错也算失败」：静默跳过会让「没检查」看起来像「没问题」。
"""

from __future__ import annotations

import pathlib
import sys
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SUBPROJECT = REPO_ROOT / "taobao-publisher"
if str(SUBPROJECT) not in sys.path:
    sys.path.insert(0, str(SUBPROJECT))

from taobao_publish import selfcheck  # noqa: E402


class SelfCheckPassesTest(unittest.TestCase):
    def test_all_gates_pass(self) -> None:
        results = selfcheck.run_all()
        failed = [r for r in results if not r.ok]
        self.assertEqual(
            [r.name for r in failed], [],
            "自检未通过：\n" + "\n".join(
                "{}: {}".format(r.name, "；".join(r.failures[:5])) for r in failed),
        )

    def test_all_gates_are_registered(self) -> None:
        """**门的清单要与 ALL_CHECKS 一致**，而不是写死个数。

        写死个数的话，加一道门就得记得改这里，忘了就红——
        而真正该问的是「跑的是不是登记过的那几道」。
        """

        names = [r.name for r in selfcheck.run_all()]
        self.assertEqual(len(names), len(selfcheck.ALL_CHECKS),
                         "跑出来的门数与登记的不一致")
        for expected in ("契约自检", "构造器冒烟", "错误目录完备性",
                         "hard 规则覆盖", "陈旧说法"):
            self.assertIn(expected, names)


class GatesCanActuallyFailTest(unittest.TestCase):
    """每道门都要有一个**反例**。"""

    def test_builder_gate_catches_a_brace_bug(self) -> None:
        """塞一个花括号写错的构造器进去，冒烟必须抓到。"""

        from taobao_publish import page

        def build_故意写错() -> str:
            # 单花括号 + **真的调用 .format()** —— 就是当初炸掉 upload_images 的写法。
            # ⚠️ 第一版写的是一句**不含 .format() 调用**的字符串，
            # 字符串里只有花括号是不会报错的——于是门没失败、用例先失败。
            return "(() => { const a = 1; })()".format()

        page.build_故意写错 = build_故意写错
        try:
            result = selfcheck.check_builders()
        finally:
            del page.build_故意写错

        self.assertFalse(result.ok, "花括号错误必须被抓到")
        self.assertTrue(any("故意写错" in f for f in result.failures))

    def test_error_catalog_gate_catches_a_missing_code(self) -> None:
        """目录里没有的码，必须被扫出来。"""

        from taobao_publish import errors

        original = dict(errors.ERROR_CATALOG)
        # 造一个「代码里声明了但目录里没有」的码：
        # 从目录里摘掉一个**已被声明**的码即可。
        declared = selfcheck.declared_error_codes()
        victim = next(code for code in declared if code in errors.ERROR_CATALOG)
        errors.ERROR_CATALOG.pop(victim)
        try:
            result = selfcheck.check_error_catalog()
        finally:
            errors.ERROR_CATALOG.clear()
            errors.ERROR_CATALOG.update(original)

        self.assertFalse(result.ok, "摘掉目录里的码之后必须失败")
        self.assertTrue(any(victim in f for f in result.failures))

    def test_hard_rule_gate_catches_an_unread_rule(self) -> None:
        """契约里加了 hard 规则、代码里没有，必须被发现。

        ⚠️ 这条用的是**临时改契约文件再复原**——所以复原要写在 finally 里，
        失败时也不能把工作区留在坏状态。
        """

        import json

        rules_path = SUBPROJECT / "contracts" / "rules.json"
        original = rules_path.read_text(encoding="utf-8")
        try:
            data = json.loads(original)
            rules = data.get("rules") or data
            rules["zz_injected_hard_rule"] = {
                "value": 1, "unit": "个", "hard": True,
                "evidence": {"level": "candidate", "source": "测试注入"},
            }
            rules_path.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                                  encoding="utf-8")
            result = selfcheck.check_hard_rules()
        finally:
            rules_path.write_text(original, encoding="utf-8")

        self.assertFalse(result.ok, "代码里没出现过的 hard 规则必须被发现")
        self.assertTrue(any("zz_injected_hard_rule" in f for f in result.failures))

    def test_hard_rule_names_enumerates_from_json_not_dir(self) -> None:
        """枚举方式必须真的扫得到东西。

        ``dir(rules)`` 会扫出 **0 条**（规则是 ``.get(name)`` 访问的），
        于是覆盖检查永远通过——上一轮就是这么错的。
        """

        names = selfcheck.hard_rule_names()
        self.assertGreaterEqual(len(names), 10, "hard 规则不可能只有这么点")
        self.assertIn("title_max_chars", names)
        self.assertIn("main_image_max_bytes", names)

    def test_a_gate_that_raises_counts_as_failure(self) -> None:
        """门自己抛错也算失败——不能静默跳过。

        「没检查」看起来像「没问题」是最危险的一种。
        """

        def broken_gate():
            raise RuntimeError("模拟门自身坏掉")

        original = selfcheck.ALL_CHECKS
        selfcheck.ALL_CHECKS = (broken_gate,)
        try:
            results = selfcheck.run_all()
        finally:
            selfcheck.ALL_CHECKS = original

        self.assertEqual(len(results), 1)
        self.assertFalse(results[0].ok)
        self.assertIn("自检自身抛错", results[0].detail)


if __name__ == "__main__":
    unittest.main()

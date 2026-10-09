# -*- coding: utf-8 -*-
"""**五道门，每一道都要能证明它会失败。**

这是从第 44 轮学到的：那一轮新做的第五道门，**第一次验证就发现它自己是坏的**
——允许清单宽到豁免整个文件，塞一句假说法进去照样 `ok=True`。

一道「因为扫不到东西所以永远通过」的门，比没有门更危险：**它给出已覆盖的假象。**
所以这里用一张**表**把「每道门的反例」集中起来，一次跑完：

| 门 | 反例 |
|---|---|
| 契约自检 | 把一条规则的证据等级改成非法值 |
| 构造器冒烟 | 塞一个 `.format()` 会抛错的构造器 |
| 错误目录完备性 | 从目录里摘掉一个已被声明的码 |
| hard 规则覆盖 | 往契约里加一条代码里没有的 hard 规则 |
| 陈旧说法 | 塞一句不在允许清单里的「尚未实现」 |

**每一条反例都必须在 `finally` 里复原**——用例失败时也不能把工作区留在坏状态。
"""

from __future__ import annotations

import contextlib
import json
import pathlib
import re
import sys
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SUBPROJECT = REPO_ROOT / "taobao-publisher"
if str(SUBPROJECT) not in sys.path:
    sys.path.insert(0, str(SUBPROJECT))

from taobao_publish import selfcheck  # noqa: E402

PACKAGE = SUBPROJECT / "taobao_publish"
RULES = SUBPROJECT / "contracts" / "rules.json"


# ---------------------------------------------------------------------------
# 注入器：每个都是一对「改坏 / 复原」
# ---------------------------------------------------------------------------
@contextlib.contextmanager
def break_contract_evidence():
    """把一条规则的证据等级改成非法值。"""

    original = RULES.read_text(encoding="utf-8")
    try:
        data = json.loads(original)
        rules = data.get("rules") or data
        rules["title_max_chars"]["evidence"]["level"] = "乱写的等级"
        RULES.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        yield
    finally:
        RULES.write_text(original, encoding="utf-8")


@contextlib.contextmanager
def break_a_builder():
    """塞一个 `.format()` 会抛 `KeyError` 的构造器。

    ⚠️ 反例本身要先自证有效：第一版写的是**不含 `.format()` 调用**的字符串，
    字符串里只有花括号是不会报错的（第 40 轮踩过）。
    """

    from taobao_publish import page

    def build_反例() -> str:
        return "(() => { const a = 1; })()".format()

    page.build_反例 = build_反例
    try:
        yield
    finally:
        del page.build_反例


@contextlib.contextmanager
def break_error_catalog():
    """从目录里摘掉一个**已被声明**的码。"""

    from taobao_publish import errors

    declared = selfcheck.declared_error_codes()
    victim = next(code for code in declared if code in errors.ERROR_CATALOG)
    original = dict(errors.ERROR_CATALOG)
    try:
        errors.ERROR_CATALOG.pop(victim)
        yield victim
    finally:
        errors.ERROR_CATALOG.clear()
        errors.ERROR_CATALOG.update(original)


@contextlib.contextmanager
def break_hard_rule_coverage():
    """往契约里加一条**代码里没有**的 hard 规则。"""

    original = RULES.read_text(encoding="utf-8")
    try:
        data = json.loads(original)
        rules = data.get("rules") or data
        rules["zz_injected_hard_rule"] = {
            "value": 1, "unit": "个", "hard": True,
            "evidence": {"level": "candidate", "source": "测试注入"},
        }
        RULES.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        yield
    finally:
        RULES.write_text(original, encoding="utf-8")


@contextlib.contextmanager
def break_stale_claims():
    """塞一句**不在允许清单里**的陈旧说法。"""

    target = PACKAGE / "stages.py"
    original = target.read_text(encoding="utf-8")
    try:
        target.write_text(
            original.replace(
                "def stage_submit(ctx: PipelineContext) -> StageOutcome:",
                'def stage_submit(ctx: PipelineContext) -> StageOutcome:\n'
                '    _probe = "自动发布尚未实现"  # noqa: F841',
                1),
            encoding="utf-8",
        )
        yield
    finally:
        target.write_text(original, encoding="utf-8")



@contextlib.contextmanager
def break_action_guard():
    """把一个表达式换成**下界守卫**的写法——多命中时会静默挑第一个。

    这正是第 49 轮实机抓到的那个 bug 的形态。
    """

    from taobao_publish import page

    original = page.build_select_media_image_expression

    def buggy(name_hint: str) -> str:
        # 刻意用 `>= 1` 而不是 `=== 1`
        return ("(() => { const hits = [1, 2, 3];"
                " if (hits.length >= 1) { hits[0].click(); return {ok:true}; }"
                " return {ok:false}; })()")

    page.build_select_media_image_expression = buggy
    try:
        yield
    finally:
        page.build_select_media_image_expression = original


#: 门名 → (注入器, 期望在 failures 里看到的关键词)
INJECTIONS = {
    "契约自检": (break_contract_evidence, "title_max_chars"),
    "构造器冒烟": (break_a_builder, "反例"),
    "错误目录完备性": (break_error_catalog, None),   # 关键词由注入器给出
    "hard 规则覆盖": (break_hard_rule_coverage, "zz_injected_hard_rule"),
    "陈旧说法": (break_stale_claims, "尚未实现"),
    # 关键词取失败信息里**实际出现的**片段——第一版写「下界守卫」，
    # 而消息里是 hits.length >= 1。
    "动作守卫": (break_action_guard, ">= 1"),
}

CHECKS = {
    "契约自检": selfcheck.check_contracts,
    "构造器冒烟": selfcheck.check_builders,
    "错误目录完备性": selfcheck.check_error_catalog,
    "hard 规则覆盖": selfcheck.check_hard_rules,
    "陈旧说法": selfcheck.check_stale_claims,
    "动作守卫": selfcheck.check_action_guards,
}


class EveryGateCanFailTest(unittest.TestCase):
    def test_the_table_covers_every_registered_gate(self) -> None:
        """**加了一道门却没加反例，这条会失败。**

        门数不写死，按 `ALL_CHECKS` 实际登记的对。
        """

        registered = {check.__name__ for check in selfcheck.ALL_CHECKS}
        covered = set(CHECKS)
        # 名字映射：check_contracts -> 契约自检 ... 用 run_all 的结果核对
        actual = {result.name for result in selfcheck.run_all()}
        self.assertEqual(actual, covered,
                         "登记的门与有反例的门对不上：登记 {}，有反例 {}".format(
                             sorted(actual), sorted(covered)))
        self.assertEqual(len(registered), len(covered))

    def test_each_gate_is_healthy_before_injection(self) -> None:
        """先确认「没注入时是通过的」——否则后面的失败证明不了什么。"""

        for name, check in CHECKS.items():
            with self.subTest(gate=name):
                self.assertTrue(check().ok, "{} 在未注入时就没通过".format(name))

    def test_each_gate_fails_under_its_injection(self) -> None:
        for name, (inject, keyword) in INJECTIONS.items():
            with self.subTest(gate=name):
                with inject() as payload:
                    result = CHECKS[name]()
                self.assertFalse(result.ok, "{} 在注入反例后仍然通过".format(name))
                self.assertTrue(result.failures, "{} 报了失败却没给 failures".format(name))
                expected = keyword if keyword is not None else payload
                self.assertTrue(
                    any(expected in failure for failure in result.failures),
                    "{} 的失败信息里没提到 {!r}：{}".format(name, expected, result.failures),
                )

    def test_workspace_is_clean_after_the_injections(self) -> None:
        """注入器必须复原干净——用例失败时也不能把工作区留在坏状态。

        这条跟在上面那条后面跑，但**不依赖执行顺序**：它自己再注入一次并复原，
        然后核对文件内容。
        """

        before = {path.name: path.read_text(encoding="utf-8")
                  for path in (RULES, PACKAGE / "stages.py")}
        for inject, _ in INJECTIONS.values():
            with inject():
                pass
        after = {path.name: path.read_text(encoding="utf-8")
                 for path in (RULES, PACKAGE / "stages.py")}
        self.assertEqual(before, after, "注入器没有把文件复原")

    def test_run_all_still_passes_after_the_injections(self) -> None:
        for result in selfcheck.run_all():
            self.assertTrue(result.ok, "{} 没通过：{}".format(result.name, result.failures))


if __name__ == "__main__":
    unittest.main()

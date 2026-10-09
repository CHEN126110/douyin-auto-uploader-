# -*- coding: utf-8 -*-
"""第五道门：**陈旧说法**。

上一轮写的 `scripts/scan-stale-claims.py` 不在 `check` 里——那就又是一个
「要记得单独跑」的脚本。收进门之后，两件事必须钉住：

1. **门真的会失败**（不能又是一条永远通过的）；
2. **允许清单不许宽到豁免整个文件**。

第 2 条不是假想：第一版的 `("stages.py", "尚未实现")` 会豁免 `stages.py` 里
**任何**含「尚未实现」的行。我塞一句假的 `"自动发布尚未实现"` 进去，
这道门照样 `ok=True`——**清单宽到豁免整个文件，就等于没有这道门。**
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

PACKAGE = SUBPROJECT / "taobao_publish"


class StaleClaimGateTest(unittest.TestCase):
    def test_gate_passes_in_the_current_tree(self) -> None:
        result = selfcheck.check_stale_claims()
        self.assertTrue(result.ok, "当前树里有未豁免的陈旧说法：{}".format(result.failures))

    def test_gate_fails_on_a_new_stale_claim(self) -> None:
        """塞一句不在清单里的陈旧说法，门必须报出来。"""

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
            result = selfcheck.check_stale_claims()
        finally:
            target.write_text(original, encoding="utf-8")

        self.assertFalse(result.ok, "新加的陈年说法必须被发现")
        self.assertTrue(any("stages.py" in f for f in result.failures))

    def test_allowlist_has_no_rotten_entries(self) -> None:
        """清单里匹配不到东西的条目该删——留着会悄悄豁免将来的同类问题。"""

        rotten = selfcheck.stale_allowlist_rot()
        self.assertEqual(rotten, [], "这些清单条目已经失效，请删除：{}".format(rotten))

    def test_every_allowlist_entry_would_not_swallow_a_new_claim(self) -> None:
        """**每条清单项都不该吞掉一条「新的」陈旧说法。**

        这是防「清单再次变宽」的核心用例。

        ⚠️ 第一版写的是「片段在文件里只应匹配 1 行」——那个判定有两个毛病：
        片段出现在定义处与调用处是正常的（`stage_not_implemented(` 就有 2 处），
        于是它**报假阳性**；而真正要防的宽泛问题它**抓不到**——
        宽泛条目在正常树里同样只匹配 1 行。

        改成直接验证语义：拿每个片段去匹配一条**合成的**新陈旧行，它不该匹配上。
        第一版的 `("stages.py", "尚未实现")` 就是被这条抓住的——
        它能匹配 `_probe = "自动发布尚未实现"`，等于豁免了整个文件。
        """

        too_broad = []
        for name, fragment in selfcheck.STALE_ALLOWLIST:
            if not (PACKAGE / name).is_file():
                too_broad.append("{} 不存在".format(name))
                continue
            for phrase in selfcheck.STALE_PHRASES:
                synthetic = '_probe = "自动发布{}"'.format(phrase)
                if fragment in synthetic:
                    too_broad.append(
                        "{} :: {!r} 会吞掉一条新的陈旧说法（{!r}）".format(
                            name, fragment, synthetic))
            for token in selfcheck.STALE_TOKENS:
                synthetic = '_probe = "{}"'.format(token)
                if fragment in synthetic:
                    too_broad.append(
                        "{} :: {!r} 会吞掉新的旧模式名（{!r}）".format(
                            name, fragment, synthetic))

        self.assertEqual(
            too_broad, [],
            "这些清单条目太宽，会豁免掉将来的同类问题：\n  " + "\n  ".join(too_broad))

    def test_scanner_does_not_scan_itself(self) -> None:
        """`selfcheck.py` 里写着这些词作为搜索项——扫它会把自己全报出来。"""

        self.assertIn("selfcheck.py", selfcheck.SCAN_EXCLUDED_FILES)
        names = {item[0] for item in selfcheck._scan_stale_claims()}
        self.assertNotIn("selfcheck.py", names)

    def test_scanner_keeps_line_numbers_aligned(self) -> None:
        """注释替换成空行而不是删掉——否则报出去的行号是错的。

        **报告里给错行号比不给更糟**：看的人会去错的地方找。
        """

        sample = "\n".join([
            "# 注释一",
            "code_a = 1",
            "/* 块注释",
            "   还在块里 */",
            "code_b = 2",
        ])
        blanked = selfcheck.blank_comments(sample)
        self.assertEqual(len(blanked.splitlines()), len(sample.splitlines()),
                         "行数必须一一对应")
        self.assertIn("code_b", blanked.splitlines()[4])

    def test_gate_is_registered(self) -> None:
        # **不写死门数**——加一道门就得记得改这里，忘了就红，
        # 而真正该问的是「这道门在不在登记的清单里」。
        names = [result.name for result in selfcheck.run_all()]
        self.assertIn("陈旧说法", names)
        self.assertEqual(len(names), len(selfcheck.ALL_CHECKS))


if __name__ == "__main__":
    unittest.main()

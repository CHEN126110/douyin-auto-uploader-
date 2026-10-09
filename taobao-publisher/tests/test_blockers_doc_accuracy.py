# -*- coding: utf-8 -*-
"""`docs/06-阻塞项.md` **不许再说已经解决的事是阻塞**。

## 为什么

2026-10-03 实测：这份文档最后修改于 **11:28**，而它写着：

| 项 | 它说 | 实际 |
|---|---|---|
| B-01 | 选择器零取证 | **30/30 verified** |
| B-03 | 图片空间链路未知 | **上传已跑通** |
| B-11 | **9 个阶段未实现** | **全部实现** |
| B-12 | **未接入 Sidecar / 前端** | **已接入并实机验证** |
| B-13 | 导购标题未进入模型 | **已接入** |

**这是告诉用户「什么被卡住」的文档**——它过期比代码过期更误导：
用户会照着一份早已失效的清单去安排工作。

## 判据

* 每个 `## B-` 标题**必须带状态标记**（`（已解除）` / `（部分解除）` / `（仍存在）`）；
* **阶段全实现时**，不许有未标记的节在说「N 个阶段未实现」；
* **DOM 路线可用时**，不许有未标记的节在说「选择器零取证」；
* 新加的阻塞项要真的列在「当前阻塞」表里。

⚠️ **只针对标题与状态行判定**，正文里的历史叙述一律保留
（项目红线：不删历史记录）。
"""

from __future__ import annotations

import pathlib
import re
import sys
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SUBPROJECT = REPO_ROOT / "taobao-publisher"
if str(SUBPROJECT) not in sys.path:
    sys.path.insert(0, str(SUBPROJECT))

from taobao_publish.pipeline import describe_readiness  # noqa: E402

DOC = SUBPROJECT / "docs" / "06-阻塞项.md"

#: 标题末尾必须有的状态标记之一。
STATUS_MARKS = ("（已解除）", "（部分解除）", "（仍存在）")


class BlockersDocShapeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.text = DOC.read_text(encoding="utf-8")
        self.headings = [line for line in self.text.splitlines()
                         if line.startswith("## B-")]

    def test_doc_exists_and_has_sections(self) -> None:
        self.assertTrue(DOC.is_file())
        self.assertGreaterEqual(len(self.headings), 10, "B-xx 节太少了")

    def test_every_heading_carries_a_status_mark(self) -> None:
        """⚠️ **扫标题的人只能看到标题**——状态行在下面，标题是第一眼。"""

        missing = [h for h in self.headings
                   if not any(h.rstrip().endswith(mark) for mark in STATUS_MARKS)]
        self.assertEqual(missing, [],
                         "这些标题没有状态标记（读者会以为它们仍是阻塞）：\n  "
                         + "\n  ".join(missing))

    def test_has_a_current_blockers_section(self) -> None:
        self.assertIn("## 当前阻塞", self.text)

    def test_status_marks_are_not_nested_bold(self) -> None:
        """`> **状态：**已解除****` 渲染不对。"""

        self.assertNotIn("**** ——", self.text)
        self.assertNotIn("> **状态：**", self.text)


class BlockersDocMatchesRealityTest(unittest.TestCase):
    """**文档要与实际就绪度对得上。**"""

    def setUp(self) -> None:
        self.text = DOC.read_text(encoding="utf-8")
        self.readiness = describe_readiness()

    def _unmarked_headings_containing(self, needle: str):
        found = []
        for heading in self.text.splitlines():
            if not heading.startswith("## B-"):
                continue
            if needle in heading and not any(heading.rstrip().endswith(m)
                                             for m in STATUS_MARKS):
                found.append(heading)
        return found

    def test_no_unmarked_section_claims_stages_are_unimplemented(self) -> None:
        """阶段全实现时，标题里不许再说「未实现」而不带标记。"""

        if self.readiness.unimplemented_stages:
            self.skipTest("仍有未实现阶段，文档那样写是对的")
        offenders = self._unmarked_headings_containing("未实现")
        self.assertEqual(offenders, [],
                         "阶段已全部实现，这些标题却在说「未实现」且没标状态：\n  "
                         + "\n  ".join(offenders))

    def test_no_unmarked_section_claims_selectors_are_unverified(self) -> None:
        if not self.readiness.dom_write_ready:
            self.skipTest("DOM 路线还不可用，文档那样写是对的")
        offenders = self._unmarked_headings_containing("零取证")
        self.assertEqual(offenders, [],
                         "DOM 路线已可用，这些标题却在说「零取证」且没标状态：\n  "
                         + "\n  ".join(offenders))

    def test_submit_is_listed_as_the_live_unverified_stage(self) -> None:
        """`submit` 没跑过是**当前**的真实阻塞，文档要写着。"""

        if "submit" not in self.readiness.live_unverified_stages:
            self.skipTest("submit 已经跑过了")
        self.assertIn("submit", self.text)
        self.assertIn("B-17", self.text)

    def test_current_blockers_section_is_short(self) -> None:
        """「当前阻塞」不该又变回一张长清单——长清单说明它在累积而不是在收敛。"""

        marker = "## 当前阻塞"
        start = self.text.index(marker)
        end = self.text.index("## 概览", start)
        rows = [line for line in self.text[start:end].splitlines()
                if line.startswith("| **B-")]
        self.assertLessEqual(len(rows), 5,
                             "当前阻塞列了 {} 项，是不是有已解除的没移走？".format(len(rows)))


if __name__ == "__main__":
    unittest.main()

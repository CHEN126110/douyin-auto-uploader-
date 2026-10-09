# -*- coding: utf-8 -*-
"""B-18：`发货时间` 被判成 `text` —— **一个陷阱，和一个看不见的风险**。

## 陷阱：radio 组被判成文本框

```
发货时间     kind=text        controls=6
控件： <input> role= value='on'   ← 6 个，全是 radio
行文本：发货时间* 按商品统一设置 按规格单独设置
        今日发提升转化 24小时内发货提升转化 48小时内发货 大于48小时发货
```

根因：`locate_row_expression` 的控件画像里**没有 `type`**——
`tag`/`role`/`placeholder`/`disabled`/`readOnly` 都有，唯独缺它，
**于是 radio 与文本框长得一模一样**。

**任何人若对 `发货时间` 调 `fill_text_field`，会去写一个 `value='on'` 的 radio**——
写进去毫无意义，而回读可能"看起来设上了"。

**修后实测：**

```
发货时间     kind=choice       controls=6      ← 之前是 text
宝贝标题     kind=text         controls=1      ← 未受影响
品牌         kind=combobox     controls=1
一口价       kind=text         controls=1
```

## 风险：它的状态没人知道

这三行由**店铺默认值**决定，平台不要求填（第 77 轮：无阻塞错误、按钮可用）。
**流水线不该去设它们**——那会越过「不猜字段」的红线。

**但「不设」不等于「不用告诉操作人」**：商品按什么物流条款上架，
发布之后没有任何地方会说。

## 修的过程中量对了两次

1. 我先**猜**选中的是「24小时内发货」（按第 2 个 radio 推的），
   **实测是「48小时内发货」**——猜错了，量对了；
2. `closest('label')` 停在 `label.next-radio-wrapper`（空文本）上，
   于是读出 `[]`——**而 `[]` 会被当成「没选中任何项」，「读不到」与「没有」是两回事**。
   改成**逐级往上取第一个非空文字**。
"""
from __future__ import annotations

import inspect
import pathlib
import re
import sys
import unittest
from unittest import mock

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SUBPROJECT = REPO_ROOT / "taobao-publisher"
if str(SUBPROJECT) not in sys.path:
    sys.path.insert(0, str(SUBPROJECT))

from taobao_publish import locating, page, stages  # noqa: E402


class ControlProfileCarriesTypeTest(unittest.TestCase):
    def test_the_expression_reports_type(self) -> None:
        """⚠️ **没有 `type`，radio 与文本框长得一模一样。**"""

        source = inspect.getsource(locating.locate_row_expression)
        self.assertIn("type: el.getAttribute('type')", source)


class ClassifyRowChoiceTest(unittest.TestCase):
    """`choice` 与 `text` 必须分开。"""

    def _classify(self, controls):
        client = mock.MagicMock()
        client.evaluate.return_value = {
            "label": "发货时间", "hitCount": 1, "controlCount": len(controls),
            "controls": controls,
        }
        return page.classify_row(client, "发货时间")

    def test_a_radio_group_is_choice(self) -> None:
        controls = [{"tag": "input", "type": "radio", "role": "", "value": "on"}
                    for _ in range(6)]
        self.assertEqual(self._classify(controls)["kind"], "choice")

    def test_a_checkbox_group_is_choice(self) -> None:
        controls = [{"tag": "input", "type": "checkbox", "role": ""}]
        self.assertEqual(self._classify(controls)["kind"], "choice")

    def test_a_text_input_is_still_text(self) -> None:
        controls = [{"tag": "input", "type": "text", "role": ""}]
        self.assertEqual(self._classify(controls)["kind"], "text")

    def test_an_input_without_type_is_text(self) -> None:
        """老表达式（没有 `type` 字段）要按原样退化，不能误判成 choice。"""

        controls = [{"tag": "input", "role": ""}]
        self.assertEqual(self._classify(controls)["kind"], "text")

    def test_a_combobox_still_wins(self) -> None:
        controls = [{"tag": "input", "type": "text", "role": "combobox"}]
        self.assertEqual(self._classify(controls)["kind"], "combobox")

    def test_a_mixed_row_is_text(self) -> None:
        """radio + 真文本框混在一行 → 不是纯选项组。"""

        controls = [{"tag": "input", "type": "radio"}, {"tag": "input", "type": "text"}]
        self.assertEqual(self._classify(controls)["kind"], "text")


class ReadSelectedOptionsTest(unittest.TestCase):
    def test_the_text_walk_does_not_stop_at_the_first_label(self) -> None:
        """⚠️ **实测结构里 `closest('label')` 停在空 wrapper 上。**

        ```
        depth 0 input.next-radio-input            ""
        depth 1 span.next-radio.checked           ""
        depth 2 label.next-radio-wrapper.checked  ""        ← 停在这会读出空串
        depth 3 label                             "按商品统一设置"
        ```
        """

        # ⚠️ **判构造器的「输出」，不判它的源码。**
        #
        # 源码里有 Python 文档字符串，而文档里就写着 `closest('label')`
        # ——用来解释「**不**停在它上面」。判源码会被自己的文档骗到，
        # 本会话为此栽过很多次（`input.value` 在 docstring 里、
        # `/api/upload/*` 被当成注释开头…）。
        #
        # **构造器的返回值是纯 JS**，天然不含文档——判它就没有这个问题。
        expression = page.build_read_selected_options_expression("发货时间")
        self.assertNotIn("closest('label')", expression,
                         "不能停在 closest('label')——它可能是空 wrapper")
        self.assertIn("parentElement", expression, "要逐级往上走")

    def test_it_returns_empty_on_an_unreadable_row(self) -> None:
        client = mock.MagicMock()
        client.evaluate.return_value = {"ok": False, "reason": "row_not_found"}
        self.assertEqual(page.read_selected_options(client, "发货时间"), [])

    def test_it_returns_the_picked_texts(self) -> None:
        client = mock.MagicMock()
        client.evaluate.return_value = {"ok": True,
                                        "picked": ["按商品统一设置", "48小时内发货"]}
        self.assertEqual(page.read_selected_options(client, "发货时间"),
                         ["按商品统一设置", "48小时内发货"])


class ReadbackReportsWithoutCountingTest(unittest.TestCase):
    """⚠️ **报告，但不虚增计数。**"""

    def setUp(self) -> None:
        self.source = inspect.getsource(stages.stage_readback)

    def test_it_reads_the_logistics_rows(self) -> None:
        self.assertIn("default_notice", self.source)
        self.assertIn('("上架时间", "发货时间", "提取方式")', self.source)
        self.assertIn("read_selected_options", self.source)

    def test_it_is_in_data(self) -> None:
        self.assertIn('"default_notice": default_notice', self.source)

    def test_it_is_mentioned_in_the_summary(self) -> None:
        """`data` 是给程序看的，**操作人看的是 summary**。"""

        self.assertIn("顺带读到的**平台默认值**", self.source)

    def test_it_does_not_change_the_matched_count(self) -> None:
        """**第 70 轮的教训**：虚增计数会让人误判。

        物流设置要**另起一句**，不能混进「N 项一致」。
        """

        # 计数那句只喂 `len(matched)`——**不喂物流设置**。
        index = self.source.index("项全部一致")
        # 从计数句往前找到 `.format(`，看它后面紧跟着什么
        head = self.source[:index]
        call = head.rindex("\n        summary=")
        segment = self.source[call:index + 120]
        self.assertIn("format(", segment)
        self.assertIn("len(matched)", segment,
                      "「N 项一致」的数量只能来自 matched")
        self.assertNotIn("default_notice", segment,
                         "物流设置不能进计数那个 format")

        # 物流设置是**另起一句**接上去的
        self.assertIn("+ notice_text", self.source)

    def test_it_says_the_pipeline_does_not_set_them(self) -> None:
        """要说清**为什么**不设——否则读者以为是漏了。"""

        self.assertIn("本流水线不设", self.source)

    def test_an_unreadable_row_is_reported_as_such(self) -> None:
        """读不到就说「未读到」，**不能显示成空**（那会被当成「没有」）。"""

        self.assertIn('"未读到"', self.source)


class DocsMentionItTest(unittest.TestCase):
    def test_blockers_doc_records_the_new_state(self) -> None:
        doc = (SUBPROJECT / "docs" / "06-阻塞项.md").read_text(encoding="utf-8")
        self.assertIn("B-18", doc, "这项要在阻塞项文档里有位置")


if __name__ == "__main__":
    unittest.main()

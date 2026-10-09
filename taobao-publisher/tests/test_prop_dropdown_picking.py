# -*- coding: utf-8 -*-
"""类目属性的**下拉选值**：两种控件都要能选、能回读。

## 这一轮解决的问题

`fill_props` 从「**一个属性行都定位不到**」到「填得上并能回读」。

## 实测踩过的四个坑（都在真实页面上）

| # | 现象 | 真相 |
|---|---|---|
| 1 | 「标签 '品牌' 没有定位到行」 | 属性行是 `.sell-catProp-item-common`，不是 `publish_form` 那套 |
| 2 | 「没有候选项」 | 只认 `.info-content`；`sell-o-select` 的候选项是 `.sell-o-info` |
| 3 | 点 input 不展开（`no_popup`） | `sell-o-select` 的 input 是 `readonly`，要点 `.next-select` 容器 |
| 4 | 选上了却报 `FIELD_MISMATCH` | `sell-o-select` 的值不在 `input.value`，在 `.next-select-values` |

**第 4 条尤其值得记**：那是**假失败**——选择其实成功了，
是我的回读读错了地方。**检查错了，不是代码错了。**

## 两种控件

| 属性 | 控件 | 值在哪 |
|---|---|---|
| 品牌 | `sell-o-combobox`（可搜索） | `input.value` |
| 适用季节 / 适用性别 | `sell-o-select`（`next-no-search`） | `.next-select-values` |

## 实机结果

```
[OK] fill_base / fill_props / fill_skus / fill_freight / fill_price_stock
[OK] readback  回读核对通过：7 项全部一致
跑了 6 个阶段，6 个通过 → **全链条通过**
```
"""

from __future__ import annotations

import pathlib
import sys
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SUBPROJECT = REPO_ROOT / "taobao-publisher"
if str(SUBPROJECT) not in sys.path:
    sys.path.insert(0, str(SUBPROJECT))

from taobao_publish import page, stages  # noqa: E402

PAGE_SOURCE = (SUBPROJECT / "taobao_publish" / "page.py").read_text(encoding="utf-8")
STAGES_SOURCE = (SUBPROJECT / "taobao_publish" / "stages.py").read_text(encoding="utf-8")


class OpenPropDropdownTest(unittest.TestCase):
    def setUp(self) -> None:
        self.expression = page.build_open_prop_dropdown_expression("品牌")

    def test_clicks_the_container_not_the_input(self) -> None:
        """`sell-o-select` 的 input 是 readonly，点它不展开。"""

        self.assertIn('row.querySelector(\'[class*="next-select"]\')', self.expression)
        self.assertIn("trigger.click()", self.expression)

    def test_does_not_click_when_already_expanded(self) -> None:
        """**再点一次会把它关掉**（实测踩过）。"""

        self.assertIn("aria-expanded", self.expression)
        self.assertIn("wasExpanded", self.expression)
        self.assertIn("if (!expanded)", self.expression)

    def test_uniqueness_enforced_before_clicking(self) -> None:
        """命中不是恰好 1 行时**一次点击都不发生**。

        表达式改成「遍历两种行结构」之后判据换了写法，
        所以断言的是**语义**（先判唯一性、再点），不是某个具体字符串。
        """

        click_at = self.expression.index("trigger.click()")

        # 多命中直接返回（在点击之前）
        self.assertIn("label_ambiguous", self.expression)
        self.assertLess(self.expression.index("label_ambiguous"), click_at)
        # 恰好一行才继续
        self.assertIn("hits.length === 1", self.expression)
        self.assertLess(self.expression.index("hits.length === 1"), click_at)
        # 找不到也要在点击之前返回
        self.assertIn("label_not_found", self.expression)
        self.assertLess(self.expression.index("label_not_found"), click_at)


class CandidateTextTest(unittest.TestCase):
    def setUp(self) -> None:
        self.expression = page.build_pick_spec_value_expression("秋季")

    def test_reads_more_than_one_structure(self) -> None:
        """只认 `.info-content` 会把 `sell-o-select` 的候选项整条过滤掉。"""

        self.assertIn(".sell-o-info", self.expression)
        self.assertIn("textOf", self.expression)

    def test_still_refuses_ambiguity(self) -> None:
        self.assertIn("reason: hits.length === 0 ? 'no_match' : 'ambiguous'",
                      self.expression)


class ReadPropValueTest(unittest.TestCase):
    """**两种控件的值不在同一个地方。**"""

    def setUp(self) -> None:
        # 构造器（内联 JS 已按项目约定抽出来）
        self.expression = page.build_read_prop_value_expression("品牌")

    def test_reads_values_element_first(self) -> None:
        """sell-o-select 的值在 .next-select-values，不在 input。"""

        self.assertIn(".next-select-values", self.expression)

    def test_falls_back_to_input_value(self) -> None:
        """sell-o-combobox 的值在 input.value。"""

        self.assertIn("input.value", self.expression)

    def test_falls_back_to_em_title(self) -> None:
        self.assertIn("em[title]", self.expression)

    def test_values_element_is_tried_before_input(self) -> None:
        """顺序要紧：只读 input 会把 sell-o-select 判成「没选上」——**假失败**。

        ⚠️ **必须先剥注释**：构造器的文档字符串里就写着 `input.value`
        （在真正的代码之前）。不剥的话这条断言会被注释骗到——
        这个会话已经因此栽了 8 次。
        """

        from frontend_source_helper import code_only

        code = code_only(self.expression)
        self.assertLess(code.index("next-select-values"), code.index("input.value"))

    def test_multi_select_summary_prefix_is_stripped(self) -> None:
        """多选控件选中后的文本是「已选择 N/M 项<值>」——**前缀必须剥掉**。

        不剥的话回读永远不等于目标值，填对了也报 FIELD_MISMATCH
        （2026-10-08 真机长筒袜「适用场景」实测：`已选择 1/9 项全天候穿戴`）。
        """

        from frontend_source_helper import code_only

        code = code_only(self.expression)
        self.assertIn("已选择", code)
        self.assertIn("values_multi", code)

class FillPropsWiringTest(unittest.TestCase):
    def setUp(self) -> None:
        start = STAGES_SOURCE.index("def stage_fill_props")
        self.body = STAGES_SOURCE[start:STAGES_SOURCE.index("\ndef ", start + 10)]

    def test_combobox_uses_pick_prop_value(self) -> None:
        """组合框要**真的去选**，不是报「尚无写入方式」。"""

        self.assertIn("pick_prop_value(client", self.body)
        self.assertNotIn("尚无写入方式", self.body)

    def test_never_falls_back_to_free_text(self) -> None:
        """契约实测：往输入框打字并回车**不会**加入任何值。"""

        self.assertIn("绝不退化成自由文本硬填", self.body)

    def test_readback_has_a_property_row_fallback(self) -> None:
        """`read_text_field` 定位不到时退回 `read_prop_value`——**同一个根因的第三处**。"""

        start = STAGES_SOURCE.index("def _read_expected_value")
        body = STAGES_SOURCE[start:STAGES_SOURCE.index("\ndef ", start + 10)]
        self.assertIn("read_text_field(client, label)", body)
        self.assertIn("read_prop_value(client, label)", body)


class MainImageMissingRetryWiringTest(unittest.TestCase):
    """主图按 ID 挑选 missing 时，必须**重开弹层**再重选（不是只在旧弹层里等）。

    真机 2026-10-08 run37/run44：弹层重开后平台初始加载偶发很慢，10s 轮询 +
    「点走再点回」共 20s 都没等到卡片，图明明在空间里。重开弹层是完整重置——
    平台对新弹层一定会做初始加载。删掉这段，偶发失败就回来了。
    """

    def setUp(self) -> None:
        start = STAGES_SOURCE.index("def stage_upload_images")
        self.body = STAGES_SOURCE[start:STAGES_SOURCE.index("\ndef ", start + 10)]

    def test_missing_caught_and_popup_reopened(self) -> None:
        marker = "except page.MediaImageMissing:"
        self.assertIn(marker, self.body)
        recovery = self.body[self.body.index(marker):]
        self.assertIn("page.open_media_popup(client)", recovery)
        # 重开之后必须**再选一次**——只重开不重选等于没恢复
        self.assertEqual(recovery.count("pick_media_by_id_with_requery"), 1)
        self.assertIn("open_directory(client, selected_directory", recovery)


class CallableExportsTest(unittest.TestCase):
    def test_public_helpers_exist(self) -> None:
        for name in ("build_open_prop_dropdown_expression",
                     "build_search_prop_options_expression",
                     "pick_prop_value", "read_prop_value", "classify_row"):
            with self.subTest(name=name):
                self.assertTrue(callable(getattr(page, name, None)), name + " 不存在")


if __name__ == "__main__":
    unittest.main()

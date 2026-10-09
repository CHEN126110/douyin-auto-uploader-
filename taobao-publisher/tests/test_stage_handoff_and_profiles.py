# -*- coding: utf-8 -*-
"""**只在连着跑时才暴露**的三个缺陷。

单阶段冒烟永远发现不了这些——页面早就加载好了、属性行早就在那儿了。
只有从类目页一路跑下来才露出来。

## 缺陷一：阶段交接时表单还没渲染

```
[OK]   select_category  20688ms  类目已选中并进入填写页
[FAIL] fill_base           14ms  标签 '宝贝标题' 没有定位到行
```

`page.wait_for_publish_form` **早就写好了**，文档字符串描述的正是这个场景，
但**只有 `open_media_popup` 调用它**，`fill_*` 一个都没调。

→ 修在公共入口 `_open_publish_page`（`select_category` 传 `wait_form=False`，
它从类目页开始）。

## 缺陷二：类目属性块渲染得更晚

修完缺陷一之后：

```
[OK]   fill_base    已填并回读校验：宝贝标题、导购标题      ← 交接修好了
[FAIL] fill_props   打开属性 '品牌' 的下拉失败：label_not_found
```

`wait_for_publish_form` 等的是**表单行**，而「类目属性」块是更晚渲染的另一块。
**同一个交接问题，深了一层。**

→ `page.wait_for_prop_row`：等**自己要的那一行**。

## 缺陷三：属性行会落在**不同结构**里

```
classify_row(品牌)  -> located=true, profile=**publish_form**
property_row 组合的行数: **0**
publish_form 组合的行数: 51
```

同一个类目、同一个 URL 形态，**属性行落在不同结构里**，取决于页面是怎么到这一步的。

`classify_row` 两种都试所以找得到；而
`build_open_prop_dropdown_expression` / `build_read_prop_value_expression`
**写死了 `locating.PROPERTY_ROW`**。

→ 两个构造器都改成**按顺序试两种结构**。

## 结果

```
跑了 7 个阶段，7 个通过 → **全链条通过**
readback 回读核对通过：7 项全部一致
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

STAGES_SOURCE = (SUBPROJECT / "taobao_publish" / "stages.py").read_text(encoding="utf-8")
PAGE_SOURCE = (SUBPROJECT / "taobao_publish" / "page.py").read_text(encoding="utf-8")


class StageHandoffTest(unittest.TestCase):
    """缺陷一：`_open_publish_page` 要等填写页。"""

    def test_open_publish_page_waits_for_the_form_by_default(self) -> None:
        source = STAGES_SOURCE[STAGES_SOURCE.index("def _open_publish_page"):
                                STAGES_SOURCE.index("\ndef ", STAGES_SOURCE.index("def _open_publish_page") + 10)]
        self.assertIn("wait_form: bool = True", source)
        self.assertIn("wait_for_publish_form", source)

    def test_raises_when_the_form_never_renders(self) -> None:
        """一直等不到就**明确报错**，不把症状留给下游阶段。"""

        source = STAGES_SOURCE[STAGES_SOURCE.index("def _open_publish_page"):
                                STAGES_SOURCE.index("\ndef ", STAGES_SOURCE.index("def _open_publish_page") + 10)]
        self.assertIn("仍然没有渲染出任何一行", source)

    def test_select_category_does_not_wait_for_the_form(self) -> None:
        """它从**类目页**开始，那里没有填写页。"""

        start = STAGES_SOURCE.index("def stage_select_category")
        body = STAGES_SOURCE[start:STAGES_SOURCE.index("\ndef ", start + 10)]
        self.assertIn("wait_form=False", body)

    def test_every_stage_goes_through_the_shared_entry(self) -> None:
        """所有阶段都走 `_open_publish_page`，所以修一处就够。"""

        import ast

        tree = ast.parse(STAGES_SOURCE)
        users = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name.startswith("stage_"):
                segment = ast.get_source_segment(STAGES_SOURCE, node) or ""
                if "_open_publish_page" in segment:
                    users.add(node.name)
        self.assertGreaterEqual(len(users), 8, "使用共享入口的阶段应有多个")


class PropRowWaitTest(unittest.TestCase):
    """缺陷二：要等**自己要的那一行**。"""

    def test_helper_exists(self) -> None:
        self.assertTrue(callable(getattr(page, "wait_for_prop_row", None)))

    def test_fill_props_waits_before_classifying(self) -> None:
        start = STAGES_SOURCE.index("def stage_fill_props")
        body = STAGES_SOURCE[start:STAGES_SOURCE.index("\ndef ", start + 10)]
        self.assertIn("wait_for_prop_row(client", body)
        # 等待必须在分类之前，且取代了直接分类
        self.assertNotIn("shape = classify_row(client", body)

    def test_docstring_names_the_real_reason(self) -> None:
        """注释要说清「类目属性块渲染得更晚」——否则后人会把它当多余的等待删掉。"""

        import inspect

        doc = inspect.getdoc(page.wait_for_prop_row) or ""
        self.assertIn("类目属性", doc)
        self.assertIn("晚", doc)


class BothRowProfilesTest(unittest.TestCase):
    """缺陷三：属性行会落在**不同结构**里。"""

    def test_open_expression_tries_both_structures(self) -> None:
        expression = page.build_open_prop_dropdown_expression("品牌")
        self.assertIn("sell-component-info-wrapper-wrap", expression)
        self.assertIn("sell-catProp-item-common", expression)
        self.assertIn("PROFILES", expression)

    def test_read_expression_tries_both_structures(self) -> None:
        expression = page.build_read_prop_value_expression("品牌")
        self.assertIn("sell-component-info-wrapper-wrap", expression)
        self.assertIn("sell-catProp-item-common", expression)

    def test_open_still_refuses_ambiguity(self) -> None:
        expression = page.build_open_prop_dropdown_expression("品牌")
        self.assertIn("label_ambiguous", expression)
        self.assertIn("label_not_found", expression)
        # 多命中在点击之前就返回
        self.assertLess(expression.index("label_ambiguous"),
                        expression.index("trigger.click()"))

    def test_open_reports_which_structures_were_tried(self) -> None:
        """失败时要说清**试过哪些结构**——否则没法判断是结构不对还是真没有。"""

        expression = page.build_open_prop_dropdown_expression("品牌")
        self.assertIn("tries", expression)
        self.assertIn("rowCount", expression)


class FullChainScriptTest(unittest.TestCase):
    def test_script_exists_and_declares_its_boundary(self) -> None:
        script = SUBPROJECT / "scripts" / "smoke-full-chain-live.py"
        self.assertTrue(script.is_file())
        source = script.read_text(encoding="utf-8")
        for phrase in ("不创建草稿", "不上传", "不提交", "--allow-write"):
            self.assertIn(phrase, source)

    def test_script_covers_the_chain_from_the_category_page(self) -> None:
        script = (SUBPROJECT / "scripts" / "smoke-full-chain-live.py").read_text(encoding="utf-8")
        for stage in ("select_category", "fill_base", "fill_props", "fill_skus",
                      "fill_freight", "fill_price_stock", "readback"):
            self.assertIn('"{}"'.format(stage), script)


if __name__ == "__main__":
    unittest.main()

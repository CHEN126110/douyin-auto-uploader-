# -*- coding: utf-8 -*-
"""`fill_props` 的属性分类：**报错要说得出真正的原因**。

## 实机实测（2026-10-03，只读）

用生产定位逻辑量 `MEASURED_ROW_LABELS` 的 46 个标签：

| 行组合 | 定位到 |
|---|---|
| `publish_form`（`.sell-component-info-wrapper-wrap`） | 21 —— **类目属性行一个都没有** |
| `property_row`（`.sell-catProp-item-common`） | **4** —— 品牌、上市年份季节、适用季节、适用性别 |

而那 4 个**全是 `input[role=combobox]`**（可搜索下拉）。
其余 42 个标签**根本不在这页**——实测地图是**跨类目的并集**。

## 改之前的表现

`fill_props` 对每个属性都调 `fill_text_field`（走 `publish_form` 组合），于是：

```
[FAIL] fill_props 填类目属性失败：标签 '品牌' 没有定位到行
```

**说的是症状，不是原因。** 真正的原因是两层：① 属性行用的是另一套 DOM 结构；
② 它的控件是可搜索下拉，**没有写入方式**。

## 改之后

`page.classify_row()` 依次尝试两套组合并判控件类型，`fill_props` 按类型分派：

| kind | 处理 |
|---|---|
| `text` | 照旧写 |
| `combobox` | blocker：「是可搜索下拉，尚无写入方式」 |
| `not_located` | blocker：「不在当前类目的表单上」（说明地图是并集） |
| `ambiguous` | blocker：「定位到多行，拒绝猜」 |
"""

from __future__ import annotations

import pathlib
import sys
import unittest
from unittest import mock

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SUBPROJECT = REPO_ROOT / "taobao-publisher"
if str(SUBPROJECT) not in sys.path:
    sys.path.insert(0, str(SUBPROJECT))

from taobao_publish import locating, page, stages  # noqa: E402
from taobao_publish.models import PropEntry, PublishItem  # noqa: E402
from taobao_publish.models import ImageSet, SkuEntry  # noqa: E402


class PropertyRowProfileTest(unittest.TestCase):
    def test_property_row_profile_is_registered(self) -> None:
        """光定义常量不够——**要进 `ROW_PROFILES`**（第一版就漏了这一步）。"""

        self.assertIn("property_row", locating.ROW_PROFILES)
        self.assertEqual(locating.PROPERTY_ROW.row_selector, ".sell-catProp-item-common")

    def test_profile_order_tries_both_structures(self) -> None:
        """顺序里必须**同时**有发布页那套与属性行那套。"""

        names = [profile.name for profile in locating.ROW_PROFILE_ORDER]
        self.assertIn("publish_form", names)
        self.assertIn("property_row", names)


class ClassifyRowTest(unittest.TestCase):
    """`classify_row` 的分类结果决定 `fill_props` 怎么写。"""

    def _client(self, hits_by_profile):
        class _Client:
            def evaluate(self, expression, context_id=None):  # noqa: ANN001
                for name, payload in hits_by_profile.items():
                    if name in expression:
                        return payload
                return {"hitCount": 0}

        return _Client()

    def test_text_input(self) -> None:
        client = self._client({"publish_form": {
            "hitCount": 1, "controlCount": 1,
            "controls": [{"tag": "input", "role": ""}]}})
        with mock.patch.object(locating, "locate_row_expression",
                               lambda label, profile: profile.name):
            got = page.classify_row(client, "宝贝标题")
        self.assertEqual(got["kind"], "text")
        self.assertEqual(got["profile"], "publish_form")

    def test_combobox_is_not_text(self) -> None:
        """**可搜索下拉不能当文本写。**"""

        client = self._client({"property_row": {
            "hitCount": 1, "controlCount": 1,
            "controls": [{"tag": "input", "role": "combobox"}]}})
        with mock.patch.object(locating, "locate_row_expression",
                               lambda label, profile: profile.name):
            got = page.classify_row(client, "品牌")
        self.assertEqual(got["kind"], "combobox")
        self.assertEqual(got["profile"], "property_row")

    def test_not_located(self) -> None:
        client = self._client({})
        with mock.patch.object(locating, "locate_row_expression",
                               lambda label, profile: profile.name):
            got = page.classify_row(client, "面料")
        self.assertFalse(got["located"])
        self.assertEqual(got["kind"], "not_located")

    def test_ambiguous_is_refused(self) -> None:
        """命中多行**不许挑一行写**。"""

        client = self._client({"publish_form": {"hitCount": 3, "controls": []}})
        with mock.patch.object(locating, "locate_row_expression",
                               lambda label, profile: profile.name):
            got = page.classify_row(client, "一号价")
        self.assertEqual(got["kind"], "ambiguous")

    def test_no_control(self) -> None:
        client = self._client({"publish_form": {"hitCount": 1, "controls": []}})
        with mock.patch.object(locating, "locate_row_expression",
                               lambda label, profile: profile.name):
            got = page.classify_row(client, "白底图")
        self.assertEqual(got["kind"], "no_control")


class FillPropsBlockerMessageTest(unittest.TestCase):
    """`fill_props` 的 blocker 文案要说得出原因。"""

    def setUp(self) -> None:
        source = (SUBPROJECT / "taobao_publish" / "stages.py").read_text(encoding="utf-8")
        start = source.index("def stage_fill_props")
        self.body = source[start:source.index("\ndef ", start + 10)]

    def test_imports_and_calls_the_classifiers(self) -> None:
        """⚠️ 钉住一次**真实的手误**：第一个补丁把导入加到了 `fill_base` 上
        （字符串替换命中的是**第一处** `from .page import ...`）。

        断言**语义**而不是文本形状：导入行可能跨行、可能加新名字，
        写死一整行会让无关改动也把它弄红。
        """

        self.assertIn("from .page import (", self.body)
        for name in ("classify_row", "wait_for_prop_row"):
            with self.subTest(name=name):
                self.assertIn(name, self.body, "fill_props 没导入 " + name)
        # 用到了（不是只导入）
        self.assertIn("wait_for_prop_row(client", self.body)

    def test_combobox_now_goes_through_pick_prop_value(self) -> None:
        """**行为升级了**：组合框从「报尚无写入方式」改为「真的去选」。

        实机验证过两种控件都能走通（品牌 / 适用季节 / 适用性别），
        所以这条断言跟着改——**改的是测试，不是行为**。
        具体选值逻辑由 `tests/test_prop_dropdown_picking.py` 覆盖。
        """

        self.assertIn("pick_prop_value(client", self.body)
        self.assertNotIn("尚无写入方式", self.body)

    def test_not_located_message_explains_the_union(self) -> None:
        """要说清**地图是跨类目的并集**——否则看的人会以为标签写错了。"""

        self.assertIn("跨类目的并集", self.body)
        self.assertIn("不在当前类目的表单上", self.body)

    def test_ambiguous_message_refuses_to_guess(self) -> None:
        self.assertIn("拒绝猜", self.body)

    def test_failure_distinguishes_partial_success(self) -> None:
        """「一条都没写成」与「写了几条、剩下写不了」要分开说。"""

        self.assertIn("写不进去（成功", self.body)


class NoSilentTextFallbackTest(unittest.TestCase):
    """**不许**对非 text 的分类回退到 `fill_text_field`。"""

    def test_only_text_kind_uses_fill_text_field(self) -> None:
        source = (SUBPROJECT / "taobao_publish" / "stages.py").read_text(encoding="utf-8")
        start = source.index("def stage_fill_props")
        body = source[start:source.index("\ndef ", start + 10)]

        # `fill_text_field` 只应在 `kind == "text"` 那条分支里出现
        index = body.index("fill_text_field(")
        preceding = body[max(0, index - 120):index]
        self.assertIn('kind == "text"', preceding,
                      "fill_text_field 必须在 text 分支里调用")


if __name__ == "__main__":
    unittest.main()

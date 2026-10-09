# -*- coding: utf-8 -*-
"""跨边界核对：**界面发的字段** vs **Sidecar 接受的字段**。

## 为什么需要

第 66 轮的教训：「两处算同一件事、算法不一致」——
`desktop` 排除 `_1x1` 而 `local_source` 偏好 `_1x1`，**768 条测试全绿，缺陷照样活着**。

同一把尺子用到**界面 ↔ Sidecar** 这条边界上：
`TaobaoPublishPanel.vue` 造出 `product`，`app.py` 把它翻译成流水线的 `request`。
**两边字段集对不上**的后果是**静默的**：界面填了半天、Sidecar 看不懂就丢掉，
而流水线在**预检**才报「缺这个字段」——用户看不出丢在哪一环。

## 实测发现

`outer_id`（商家编码）**声明了、Sidecar 也接受，而界面从没写过**。
后果：`fill_base` 每次都报「跳过：商家编码（未提供）」——
**不是用户没填，是根本没地方填。** 已补上输入框。

`category_id` 是**有依据的例外**（流水线回读权威 catId），见核对脚本里的说明。
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SUBPROJECT = REPO_ROOT / "taobao-publisher"
if str(SUBPROJECT) not in sys.path:
    sys.path.insert(0, str(SUBPROJECT))

CHECK = SUBPROJECT / "scripts" / "check-ui-sidecar-fields.py"
spec = importlib.util.spec_from_file_location("ui_sidecar_fields", CHECK)
fields = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fields)

PANEL = REPO_ROOT / "tauri-app" / "src" / "components" / "TaobaoPublishPanel.vue"


class ExtractorTest(unittest.TestCase):
    """提取器必须**只取顶层键**——否则它会误报，而误报的检查器会被忽略。"""

    def test_declared_has_no_nested_sku_fields(self) -> None:
        """`spec_values` / `price` / `stock` 是 `skus[]` 里的**嵌套**字段。"""

        declared = fields.interface_type_fields()
        for nested in ("spec_values", "price", "stock"):
            with self.subTest(field=nested):
                self.assertNotIn(nested, declared,
                                 "嵌套字段被当成了顶层——提取器有假阳性")

    def test_declared_has_the_top_level_fields(self) -> None:
        declared = fields.interface_type_fields()
        for name in ("title", "category_path", "props", "skus", "outer_id"):
            with self.subTest(field=name):
                self.assertIn(name, declared)

    def test_sidecar_accepted_is_not_empty(self) -> None:
        self.assertIn("title", fields.sidecar_accepted_fields())
        self.assertIn("outer_id", fields.sidecar_accepted_fields())


class CrossBoundaryTest(unittest.TestCase):
    """**三边必须一致**（例外要有依据）。"""

    def test_no_field_the_ui_writes_is_dropped_by_the_sidecar(self) -> None:
        """⚠️ 界面会写、Sidecar 不读 → **静默丢弃**。"""

        built = fields.ui_built_fields()
        accepted = fields.sidecar_accepted_fields()
        dropped = sorted(built - accepted)
        self.assertEqual(dropped, [],
                         "这些键界面会写但 Sidecar 不读，会被静默丢掉：{}".format(dropped))

    def test_no_dead_fields_in_the_type(self) -> None:
        """types 声明了、界面从不写、也没有例外依据 → 死字段。"""

        declared = fields.interface_type_fields()
        built = fields.ui_built_fields()
        dead = sorted(declared - built - set(fields.INTENTIONALLY_UNSET))
        self.assertEqual(dead, [],
                         "这些字段声明了却没人能填（缺输入框），或该写进例外清单：{}".format(dead))

    def test_no_field_the_sidecar_reads_is_unreachable(self) -> None:
        accepted = fields.sidecar_accepted_fields()
        declared = fields.interface_type_fields()
        unreachable = sorted(accepted - declared)
        self.assertEqual(unreachable, [],
                         "Sidecar 会读这些键，但界面造不出来：{}".format(unreachable))


class IntentionalExceptionTest(unittest.TestCase):
    """例外清单**本身也要被看守**——它会过期。"""

    def test_exception_entries_carry_a_reason(self) -> None:
        for name, reason in fields.INTENTIONALLY_UNSET.items():
            with self.subTest(field=name):
                self.assertGreater(len(reason.strip()), 20,
                                   "例外必须写明依据，不能只写个名字")

    def test_exception_entries_are_not_actually_written_by_the_ui(self) -> None:
        """例外一旦开始被写，就该把它从清单里删掉。"""

        built = fields.ui_built_fields()
        stale = sorted(set(fields.INTENTIONALLY_UNSET) & built)
        self.assertEqual(stale, [],
                         "例外清单过期：界面已经开始写这些字段了：{}".format(stale))

    def test_exception_entries_are_declared_in_the_type(self) -> None:
        """例外只能是「声明了但不写」的；没声明的例外是无意义的。"""

        declared = fields.interface_type_fields()
        bogus = sorted(set(fields.INTENTIONALLY_UNSET) - declared)
        self.assertEqual(bogus, [],
                         "例外清单里有 types 根本没声明的字段：{}".format(bogus))


class OuterIdWiringTest(unittest.TestCase):
    """`outer_id` 从界面到 Sidecar **四处都要通**。"""

    def test_panel_declares_and_initialises_it(self) -> None:
        source = PANEL.read_text(encoding="utf-8")
        self.assertIn("outer_id: string;", source)
        self.assertIn('outer_id: ""', source)

    def test_panel_has_an_input_for_it(self) -> None:
        source = PANEL.read_text(encoding="utf-8")
        template = source[source.index("<template>"):]
        self.assertIn('v-model="draft.outer_id"', template,
                      "没有输入框，用户就没地方填")

    def test_panel_sends_it_only_when_non_empty(self) -> None:
        """选填字段**留空就不发**，让流水线如实报「跳过」。"""

        source = PANEL.read_text(encoding="utf-8")
        self.assertIn("if (outerId) product.outer_id = outerId;", source)

    def test_default_is_empty_not_a_guess(self) -> None:
        """⚠️ **不许猜一个默认商家编码**——空着就是空着。"""

        source = PANEL.read_text(encoding="utf-8")
        self.assertNotIn('outer_id: "ID-', source)


if __name__ == "__main__":
    unittest.main()

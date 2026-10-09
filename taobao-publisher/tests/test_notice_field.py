# -*- coding: utf-8 -*-
"""「购买须知」这条通路**已整条删除**——本文件留作"它为什么不再有效"的记录。

## 它曾经是什么（E-304 接入 / E-306 接进界面 / E-318 撤回界面）

一条完整的字段通路，五处齐备：

1. `models.PublishItem.notice`；
2. `mapping.build_publish_item` **只从请求里取**它（刻意不从本地的「备注」猜——
   内部说明（供应商/成本）被当买家须知发出去，比"没填"糟得多）；
3. `stages.stage_fill_price_stock` 非空才写「购买须知」行，空着记进 `skipped`；
4. `stages.expected_field_values` 非空才在回读里期待它（写进去的就要核对）；
5. `contracts/field_mapping.json` 的 `item.notice` 条目——证据级别如实写的是
   **`candidate`**：真机只确认过"行存在 + 标签已实测 + 控件数 1"，**真实写入从未实测**。

配套还有侧车两处：`/load_detail` 的回传、`_validated_product_edits` 的保存白名单
（以及 `_product_edit_revision` 的"资料指纹"）。

## 为什么这些断言现在无效（2026-10-07）

用户要求撤回界面改动（E-318），侧车的淘宝请求白名单也去掉了 `notice`。于是
**没有任何调用方能产生非空的 notice**：界面不收集、不发；侧车不转发；用户按主界面
按钮走的那条路（`ctx.prepared_media is not None` 的"素材已备好→绑定"分支）也不构造它。
死值 → 死字段 → 死行：留着只会让人以为它还能用。

所以按"删段不删文件"处理：把这条链连同它的断言一起删掉，**文件保留**，把"为什么"写在这里。

## 保留的东西（别顺手删掉）

* `src/orm.py` 的 `notice` 列与 `_ensure_record_columns` 迁移：真实库已经有这一列，
  **删列是破坏性操作**；只是代码不再使用它，它也不再参与"资料指纹"；
* `locating.VERIFIED_LABELS['fill_price_stock']` 里的「购买须知」：那是**真机实测的行标签**
  （证据），不是这段死码的一部分；
* 平台表单上那一行本身（`MEASURED_ROW_LABELS['购买须知']`，控件数 1）——哪天要重新接上，
  它是入口，不是障碍。

## 本文件现在锁什么

只锁一条：**这条链确实删干净了，没有被顺手接回来**。重新接上就得同时补齐
模型字段 / 映射 / 写入 / 回读期望 / 契约条目五处——只补一处是半截通路，这里会先报出来。
"""

from __future__ import annotations

import ast
import dataclasses
import json
import unittest
from pathlib import Path
from unittest import mock

from taobao_publish import mapping, models, stages

SUBPROJECT_ROOT = Path(__file__).resolve().parents[1]
SIDECAR_APP = SUBPROJECT_ROOT.parent / "tauri-app" / "python-sidecar" / "app.py"


class _Ctx:
    """`stage_fill_price_stock` / `expected_field_values` 需要的最小上下文。"""

    def __init__(self, item, contracts):
        self.item = item
        self._contracts = contracts
        self.scratch = {}

    def resolved_contracts(self):
        return self._contracts


def _item():
    return models.PublishItem(
        record_id=7, record_name="ID-测试",
        skus=[models.SkuEntry(spec_values={"颜色分类": "黑"}, price=19.9, stock=10)])


def _fill_price_stock():
    """跑一次真实的 `stage_fill_price_stock`，只把平台边界换成替身（不碰浏览器）。"""

    from taobao_publish import page
    from taobao_publish.contracts import load_contracts
    ctx = _Ctx(_item(), load_contracts())
    written = []

    def fake_fill(client, label, value, **kwargs):
        written.append((label, value))
        return {"label": label, "written": value, "read_back": value}

    # ⚠️ `stage_fill_price_stock` 是**在函数内** `from .page import ...` 的，
    # 所以必须 patch `page` 模块上的名字，patch `stages.fill_text_field` 会报
    # "module has no attribute"。
    with mock.patch.object(stages, "_open_publish_page", return_value=mock.Mock()), \
            mock.patch.object(page, "read_text_field", return_value="1"), \
            mock.patch.object(page, "fill_text_field", side_effect=fake_fill):
        outcome = stages.stage_fill_price_stock(ctx)
    return outcome, written


def _entries_with_intent(node, intent):
    """递归找 `"intent": <intent>` 的条目（契约结构变了也不会静默漏检）。"""

    found = []
    if isinstance(node, dict):
        if node.get("intent") == intent:
            found.append(node)
        for value in node.values():
            found.extend(_entries_with_intent(value, intent))
    elif isinstance(node, list):
        for value in node:
            found.extend(_entries_with_intent(value, intent))
    return found


class NoticeChainRemovedTest(unittest.TestCase):
    """最简回归：这条死链不得复活（复活一处就是半截通路）。"""

    def test_the_chain_is_gone_from_every_layer(self) -> None:
        with self.subTest(layer="模型：PublishItem 不再有 notice 字段"):
            self.assertNotIn("notice", {f.name for f in dataclasses.fields(models.PublishItem)})

        with self.subTest(layer="映射：请求里给了 notice 也不会进 PublishItem"):
            outcome = mapping.build_publish_item(
                models.LocalProduct(record_id=7, record_name="ID-测试"),
                {"record_id": 7, "record_name": "ID-测试",
                 "skus": [{"spec_values": {"颜色分类": "黑"}, "price": 19.9, "stock": 10}],
                 "notice": "接回来的话这里会变"})
            self.assertIsNotNone(outcome.item)
            self.assertFalse(hasattr(outcome.item, "notice"))

        with self.subTest(layer="写入：不再写「购买须知」，也不再报「未填」"):
            outcome, written = _fill_price_stock()
            self.assertTrue(outcome.ok, outcome.summary)
            self.assertEqual(["一口价", "总库存"], [label for label, _ in written])
            self.assertNotIn("购买须知", outcome.summary)
            self.assertEqual({"fields", "stock_before", "price", "stock"}, set(outcome.data))

        with self.subTest(layer="回读：期望清单里没有「购买须知」"):
            from taobao_publish.contracts import load_contracts
            labels = [entry["label"] for entry in
                      stages.expected_field_values(_Ctx(_item(), load_contracts()))]
            self.assertNotIn("购买须知", labels)

        with self.subTest(layer="契约：没有 item.notice 条目"):
            payload = json.loads(
                (SUBPROJECT_ROOT / "contracts" / "field_mapping.json").read_text(encoding="utf-8"))
            self.assertEqual([], _entries_with_intent(payload, "item.notice"))


class SidecarNoLongerCarriesTheFieldTest(unittest.TestCase):
    """侧车四处（`/load_detail` 回传、指纹 fields、保存白名单、新建插入）都不该再有它。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = SIDECAR_APP.read_text(encoding="utf-8")

    def test_no_notice_string_literal_is_left_in_the_sidecar(self) -> None:
        """只看**字符串字面量**，所以解释"为什么删"的注释不会把这条用例考红。"""

        literals = sorted({
            node.value for node in ast.walk(ast.parse(self.source))
            if isinstance(node, ast.Constant) and node.value == "notice"})
        self.assertEqual([], literals, (
            "app.py 里又出现了 'notice' 字符串字面量。回传、指纹、保存白名单、新建插入"
            "四处都已删除；要重新接上这条链，请同时补齐模型/映射/写入/回读期望/契约五处，"
            "只加一个键是半截通路。"))

    def test_the_desktop_request_translation_still_does_not_forward_it(self) -> None:
        """桌面请求白名单里**不该**有它：界面造不出这个键，转了就是静默丢弃。"""

        marker = "for key in (\"title\", \"guide_title\", \"freight_template_name\", \"outer_id\""
        start = self.source.index(marker)
        line = self.source[start:self.source.index("\n", start)]
        self.assertNotIn("notice", line,
                         "界面不提供该字段；侧车再转它就成了「界面造不出来的键」")


if __name__ == "__main__":
    unittest.main()

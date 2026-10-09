# -*- coding: utf-8 -*-
"""`readback` 必须覆盖**流水线写过的每一样东西**。

审查发现：流水线写了 8 样，而 `readback` 只核对 4 项——**主图、SKU 行数、运费模板
都不在范围内**。而 `submit` 现在要求 readback 必须通过，于是
「主图位空着、SKU 表空着」的运行**能通过核对继续走到提交**。

这正是 E-126 的同一类缺陷：**写入时验证过，被后续重渲染抹掉，最终检查看不见**。
"""

from __future__ import annotations

import pathlib
import sys
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SUBPROJECT = REPO_ROOT / "taobao-publisher"
if str(SUBPROJECT) not in sys.path:
    sys.path.insert(0, str(SUBPROJECT))

from taobao_publish import stages  # noqa: E402
from taobao_publish.models import ImageSet, PropEntry, PublishItem, SkuEntry  # noqa: E402


def make_item(**overrides):
    base = dict(
        record_id=1,
        record_name="ID-1",
        title="标题",
        images=ImageSet(main=["a.jpg", "b.jpg", "c.jpg", "d.jpg", "e.jpg"], detail=[]),
        props=[PropEntry(prop_name="品牌", value_name="无品牌/无注册商标")],
        skus=[
            SkuEntry(spec_values={"尺码": "M(37-41)"}, price=16.8, stock=100),
            SkuEntry(spec_values={"尺码": "L（45-47）"}, price=16.8, stock=100),
        ],
        freight_template_name="极兔快递",
    )
    base.update(overrides)
    return PublishItem(**base)


def expected_for(item):
    ctx = stages.PipelineContext(item=item, dry_run=False)
    return {entry["label"]: entry for entry in stages.expected_field_values(ctx)}


class ReadbackCoverageTest(unittest.TestCase):
    def test_covers_main_image_count(self) -> None:
        entry = expected_for(make_item())["主图张数"]
        self.assertEqual(entry["value"], "5")
        self.assertEqual(entry["kind"], "main_image_count")

    def test_covers_sku_specs(self) -> None:
        entry = expected_for(make_item())["SKU 规格值"]
        # ⚠️ 值里**同时含行数与规格值**——旧版只比行数，规格值填错也能过。
        self.assertEqual(entry["value"], "2 行：L（45-47）｜M(37-41)")
        self.assertEqual(entry["kind"], "sku_specs")

    def test_covers_freight_template(self) -> None:
        entry = expected_for(make_item())["运费模板"]
        self.assertEqual(entry["value"], "极兔快递")
        self.assertEqual(entry["kind"], "freight_template")

    def test_every_entry_declares_a_kind(self) -> None:
        """没有 ``kind`` 的条目会走缺省 ``text``——那对新加的三项是错的读法，
        所以要求**每一项都显式声明**，避免有人加条目时忘了。"""

        entries = stages.expected_field_values(
            stages.PipelineContext(item=make_item(), dry_run=False))
        for entry in entries:
            self.assertIn("kind", entry, "条目 {!r} 没有声明 kind".format(entry.get("label")))
            self.assertIn(entry["kind"],
                          {"text", "main_image_count", "sku_specs", "sku_row_prices", "sku_row_values", "freight_template", "submit_ready"})

    def test_structural_entries_are_omitted_when_not_applicable(self) -> None:
        """没有主图 / 没有 SKU / 没指定运费模板时**不产生**对应的核对项——
        否则会拿一个空期望值去核对，产生假失败。"""

        labels = expected_for(make_item(images=ImageSet(main=[], detail=[]),
                                        skus=[],
                                        freight_template_name=""))
        self.assertNotIn("主图张数", labels)
        self.assertNotIn("SKU 规格值", labels)
        self.assertNotIn("运费模板", labels)

    def test_dispatch_helper_handles_all_kinds(self) -> None:
        """分派函数必须认识全部 kind；未知 kind 要**抛错**而不是静默按文本读。"""

        import inspect

        source = inspect.getsource(stages._read_expected_value)
        for kind in ("main_image_count", "sku_specs", "freight_template"):
            self.assertIn(kind, source)
        self.assertIn("raise ValueError", source, "未知 kind 必须显式报错")

    def test_readback_uses_the_dispatch_helper(self) -> None:
        import inspect

        source = inspect.getsource(stages.stage_readback)
        self.assertIn("_read_expected_value(", source)
        self.assertNotIn("page.read_text_field(client, label)", source,
                         "不能再一律用文本读取器——主图张数/SKU 行数不是文本字段")


if __name__ == "__main__":
    unittest.main()

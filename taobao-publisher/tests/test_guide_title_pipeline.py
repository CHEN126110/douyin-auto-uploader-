# -*- coding: utf-8 -*-
"""**导购标题必须真的进流水线**——以前填了被静默丢弃。

表单上有「导购标题」这一行（实测 43 行里的第 5 行，
`MEASURED_ROW_LABELS["导购标题"]["controls"] == 1`），界面上也有输入框，
但：

* `PublishItem` **没有** `guide_title` 字段；
* `buildProductRequest` 不发它；
* Sidecar 的翻译不认它；
* 流水线从不填它。

于是**操作人填了导购标题，以为会发布，实际被静默丢弃**——
与之前修过的「界面收集的资料从没到达流水线」（E-127）同一类。

这些是**静态 + 离线**检查，不连浏览器。
"""

from __future__ import annotations

import dataclasses
import inspect
import pathlib
import sys
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SUBPROJECT = REPO_ROOT / "taobao-publisher"
if str(SUBPROJECT) not in sys.path:
    sys.path.insert(0, str(SUBPROJECT))

from taobao_publish import mapping, models, stages  # noqa: E402

PANEL = REPO_ROOT / "tauri-app" / "src" / "components" / "TaobaoPublishPanel.vue"
TYPES = REPO_ROOT / "tauri-app" / "src" / "types" / "index.ts"
SIDECAR = REPO_ROOT / "tauri-app" / "python-sidecar" / "app.py"


class GuideTitlePipelineTest(unittest.TestCase):
    def test_publish_item_carries_guide_title(self) -> None:
        names = [f.name for f in dataclasses.fields(models.PublishItem)]
        self.assertIn("guide_title", names)

    def test_guide_title_is_not_on_sku_entry(self) -> None:
        """它属于商品级字段，不该落到 SKU 上——实测踩过这个（加错了类）。"""

        names = [f.name for f in dataclasses.fields(models.SkuEntry)]
        self.assertNotIn("guide_title", names)

    def test_build_publish_item_reads_it_from_the_request(self) -> None:
        local = models.LocalProduct(record_id=1, record_name="ID-1", title="本地标题",
                                    main_images=["a.jpg"], detail_images=[])
        item = mapping.build_publish_item(local, {"title": "标题",
                                                  "guide_title": "夏季薄款袜子"}).item
        self.assertEqual(item.guide_title, "夏季薄款袜子")

    def test_missing_guide_title_is_empty_not_guessed(self) -> None:
        """没给就是空——**不编造**。"""

        local = models.LocalProduct(record_id=1, record_name="ID-1", title="本地标题",
                                    main_images=["a.jpg"], detail_images=[])
        item = mapping.build_publish_item(local, {"title": "标题"}).item
        self.assertEqual(item.guide_title, "")

    def test_too_long_guide_title_is_a_blocker(self) -> None:
        """`guide_title_max_chars` 在契约里是 hard: true——发布路径也要查。"""

        from taobao_publish.contracts import load_contracts

        limit = load_contracts().rules.integer("guide_title_max_chars")
        local = models.LocalProduct(record_id=1, record_name="ID-1", title="本地标题",
                                    main_images=["a.jpg"], detail_images=[])
        item = mapping.build_publish_item(
            local, {"title": "标题", "guide_title": "字" * (limit + 1)}).item
        blockers = mapping.validate_title(item, load_contracts())
        self.assertTrue(any(b.field == "guide_title" for b in blockers),
                        "导购标题超长必须报阻塞")

    def test_empty_guide_title_is_not_validated(self) -> None:
        """选填——空着不该报。"""

        from taobao_publish.contracts import load_contracts

        local = models.LocalProduct(record_id=1, record_name="ID-1", title="本地标题",
                                    main_images=["a.jpg"], detail_images=[])
        item = mapping.build_publish_item(local, {"title": "标题"}).item
        blockers = mapping.validate_title(item, load_contracts())
        self.assertFalse([b for b in blockers if b.field == "guide_title"])

    def test_fill_base_fills_it_and_skips_when_empty(self) -> None:
        source = inspect.getsource(stages.stage_fill_base)
        self.assertIn('fill_text_field(client, "导购标题"', source)
        self.assertIn("if guide_title:", source, "选填：没给就不填")

    def test_readback_covers_it(self) -> None:
        source = inspect.getsource(stages.expected_field_values)
        self.assertIn("导购标题", source, "回读核对要覆盖它")

    def test_sidecar_translation_passes_it(self) -> None:
        source = SIDECAR.read_text(encoding="utf-8")
        block = source.split("def _taobao_product_request_payload(", 1)[1].split(
            "def _run_taobao_publish_task(", 1)[0]
        self.assertIn("guide_title", block)

    def test_frontend_sends_it(self) -> None:
        types_src = TYPES.read_text(encoding="utf-8")
        self.assertIn("guide_title", types_src)

        panel = PANEL.read_text(encoding="utf-8")
        builder = panel.split("function buildProductRequest(", 1)[1].split(
            "async function checkPreparation", 1)[0]
        self.assertIn("guide_title", builder, "面板必须把它发出去")


if __name__ == "__main__":
    unittest.main()

# -*- coding: utf-8 -*-
"""主图那一项：**能比对内容时就不只比张数**。

## 缺口（第 71 轮发现，这轮修）

`readback` 的两项是「只数数量」的，其中一项是主图：

| 项 | 页面**读回了** | 核对**用了** |
|---|---|---|
| 主图张数 | `filled: 5` + **`images: [5 个 URL]`** | 只用 `filled` |

**于是图片被挤掉、被替换、顺序变了，都照样报「全部一致」。**

## 这一轮能证明什么、不能证明什么

**能**：`upload_images` 选图入位后把平台上的 URL 记进 scratch，
`readback` 再读一次比对——证明**现在挂着的就是刚选进去的那几张**
（数量、内容、顺序）。

**不能**：平台把图重新托管成 `img.alicdn.com/...`，而图片空间只给文件名，
**没有名字→URL 的映射**——所以证明不了「选进去的确实是本地那几个文件」。

**能证明什么就说什么，不夸大。**

## 实测判别力（页面上 5 张）

```
有选入记录（一致）        → 通过
记录少一张（模拟被挤掉）   → 失败（正确）
记录顺序不同             → 失败（正确）   ← 第 1 张是搜索主图，顺序有意义
没有记录（退回比张数）     → 通过（如实退回）
```
"""

from __future__ import annotations

import inspect
import pathlib
import sys
import unittest
from unittest import mock

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SUBPROJECT = REPO_ROOT / "taobao-publisher"
if str(SUBPROJECT) not in sys.path:
    sys.path.insert(0, str(SUBPROJECT))

from taobao_publish import page, stages  # noqa: E402
from taobao_publish.models import ImageSet, PublishItem, SkuEntry  # noqa: E402

SAMPLE_URLS = ["https://img.alicdn.com/a.webp", "https://img.alicdn.com/b.webp"]


def make_item(count: int = 2) -> PublishItem:
    return PublishItem(
        record_id=1, record_name="X", title="标题",
        images=ImageSet(main=["m{}.jpg".format(i) for i in range(count)], detail=[]),
        skus=[SkuEntry(spec_values={"尺码": "M"}, price=1.0, stock=1)],
    )


def expected(ctx):
    return stages.expected_field_values(ctx)


class MainImagesPrefersContentTest(unittest.TestCase):
    def test_falls_back_to_count_without_a_selection_record(self) -> None:
        """没有选入记录时（例如单独跑 readback）如实退回比张数。"""

        ctx = stages.PipelineContext(item=make_item(), dry_run=False)
        entry = next(e for e in expected(ctx) if e["kind"].startswith("main_image"))
        self.assertEqual(entry["kind"], "main_image_count")
        self.assertEqual(entry["value"], "2")

    def test_compares_content_when_the_record_exists(self) -> None:
        ctx = stages.PipelineContext(item=make_item(), dry_run=False)
        ctx.scratch["upload_images"] = {"selected_urls": SAMPLE_URLS}
        entry = next(e for e in expected(ctx) if e["kind"].startswith("main_image"))
        self.assertEqual(entry["kind"], "main_images")
        self.assertIn("a.webp", entry["value"])
        self.assertIn("｜", entry["value"], "多张要用分隔符连起来，避免拼串歧义")

    def test_source_says_what_it_proves_and_what_it_does_not(self) -> None:
        """⚠️ `source` 要写清「证明未被替换」，**不能**写成「证明是本地那几个文件」。"""

        ctx = stages.PipelineContext(item=make_item(), dry_run=False)
        ctx.scratch["upload_images"] = {"selected_urls": SAMPLE_URLS}
        entry = next(e for e in expected(ctx) if e["kind"] == "main_images")
        self.assertIn("未被替换", entry["source"])

    def test_an_empty_record_still_falls_back(self) -> None:
        """`selected_urls: []` 等于「没记到」，要退回比张数而不是报「0 张一致」。"""

        ctx = stages.PipelineContext(item=make_item(), dry_run=False)
        ctx.scratch["upload_images"] = {"selected_urls": []}
        entry = next(e for e in expected(ctx) if e["kind"].startswith("main_image"))
        self.assertEqual(entry["kind"], "main_image_count")


class MainImagesDispatchTest(unittest.TestCase):
    def _read(self, urls):
        with mock.patch.object(page, "read_main_image_slots",
                               return_value={"found": True, "images": urls}):
            return stages._read_expected_value(
                None, page, {"label": "主图内容", "kind": "main_images"})

    def test_it_returns_the_urls_in_order(self) -> None:
        self.assertEqual(self._read(SAMPLE_URLS), "｜".join(SAMPLE_URLS))

    def test_order_matters(self) -> None:
        """第 1 张是搜索主图，**顺序不同就是不同**。"""

        self.assertNotEqual(self._read(SAMPLE_URLS), self._read(list(reversed(SAMPLE_URLS))))

    def test_a_dropped_image_is_visible(self) -> None:
        self.assertNotEqual(self._read(SAMPLE_URLS), self._read(SAMPLE_URLS[:1]))

    def test_missing_slots_is_empty_not_a_crash(self) -> None:
        with mock.patch.object(page, "read_main_image_slots",
                               return_value={"found": False}):
            got = stages._read_expected_value(
                None, page, {"label": "主图内容", "kind": "main_images"})
        self.assertEqual(got, "")


class FormatUrlsTest(unittest.TestCase):
    def test_it_does_not_truncate(self) -> None:
        """⚠️ 截断会让「前 N 位相同、后面不同」的两次比对误判为相等。"""

        source = inspect.getsource(stages._format_urls)
        self.assertNotIn("[:", source, "不许截断")
        long_url = "https://img.alicdn.com/" + "x" * 300 + ".webp"
        self.assertIn("x" * 300, stages._format_urls([long_url]))

    def test_it_skips_blanks(self) -> None:
        self.assertEqual(stages._format_urls(["a", "", "  ", "b"]), "a｜b")


class UploadRecordsSelectedUrlsTest(unittest.TestCase):
    def test_upload_stage_records_the_urls(self) -> None:
        """`upload_images` 必须把选入后读到的 URL 记进 scratch，否则这项退化了。"""

        source = inspect.getsource(stages.stage_upload_images)
        self.assertIn("selected_urls", source)
        self.assertIn("after.get(\"images\")", source)


if __name__ == "__main__":
    unittest.main()

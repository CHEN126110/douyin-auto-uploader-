# -*- coding: utf-8 -*-
"""上传队列的**假失败**：陈旧项不该算在本次头上。

第 46 轮实机复核第 34 轮的修复（「平台拒绝要如实报」）时，发现了它的**镜像问题**：

```
队列明细：
   主图_01_1x1.jpg            state=error    ← 上一次尝试留下的陈旧项
   ID-探针_185322_1x1.jpg     state=success  ← 本次传的，其实成功了

ok = False   rejectedByPlatform = True   confirmed = []
```

**本次成功却报拒绝。** 后果不只是误报——**那个陈旧项会让之后每一次上传都失败**，
而重新开始并没有清理队列的路径。

而且修完之后又发现第二个毛病：`staleQueueErrors` 的计算写在
`if rejected: return` **之后**，于是「平台拒绝」这条路径上它永远是空的。

这些用例用**假客户端**离线跑，不碰平台。
"""

from __future__ import annotations

import pathlib
import sys
import tempfile
import unittest
from unittest import mock

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SUBPROJECT = REPO_ROOT / "taobao-publisher"
if str(SUBPROJECT) not in sys.path:
    sys.path.insert(0, str(SUBPROJECT))

from taobao_publish import page  # noqa: E402


class FakeMediaClient:
    """按表达式内容分派响应的假客户端。**只覆盖 upload_files_to_media 用到的那几处。**"""

    def __init__(self, queue_items):
        self.queue_items = queue_items
        self.calls = []

    def evaluate(self, expression, context_id=None):
        self.calls.append(expression[:60])
        if "UploadPanel_uploadDir" in expression:
            return {"ok": True, "kind": "combobox", "value": "全部图片"}
        if "UploadPanel_fileItem" in expression:
            return {"count": len(self.queue_items), "items": self.queue_items}
        if "input[type=" in expression and "count" in expression:
            return {"count": 1, "inputs": [{"multiple": True}]}
        if "media-popup" in expression or "mediaPopup" in expression:
            return {"open": True}
        if "next-overlay" in expression or "PicList" in expression:
            return {"names": []}
        if "next-btn" in expression or "完成" in expression:
            return {"ok": True}
        # 默认当成「查得到」——让 arrived 为真
        return {"ok": True, "inHtml": True, "count": 1, "visible": 1, "names": []}

    def set_file_input_files(self, files, selector, *, context_id=None, timeout=15.0):
        return {"ok": True, "via": "objectId", "fileCount": len(files)}


def run_upload(queue_items, names):
    """跑一次上传，返回结果。

    ⚠️ **必须打桩 `time.sleep`**：`upload_files_to_media` 内部有固定的等待
    （等入口、等「完成」各一次），真睡的话这组用例要跑 **32 秒**。
    单元测试不该真等。
    """

    client = FakeMediaClient(queue_items)
    with tempfile.TemporaryDirectory(prefix="tb-queue-") as directory:
        paths = []
        for name in names:
            path = pathlib.Path(directory) / name
            path.write_bytes(b"x")
            paths.append(str(path))
        with mock.patch.object(page.time, "sleep", lambda *_: None):
            return page.upload_files_to_media(client, paths, context_id=1,
                                              rename_to=list(names),
                                              per_file_timeout=0.1)


STALE_ERROR = {
    "index": 0, "name": "主图_01_1x1.jpg", "state": "error",
    "desc": "操作过于频繁，请滑动验证码之后，重新上传。",
}


def ok_item(name):
    return {"index": 1, "name": name, "state": "success", "desc": "251.18K"}


def error_item(name):
    return {"index": 2, "name": name, "state": "error", "desc": "操作过于频繁"}


class StaleQueueItemTest(unittest.TestCase):
    def test_stale_error_does_not_make_this_attempt_fail(self) -> None:
        """**陈旧失败项不该把本次判成失败。**"""

        result = run_upload([STALE_ERROR, ok_item("新图.jpg")], ["新图.jpg"])
        self.assertFalse(result.get("rejectedByPlatform"),
                         "本次没有失败项，不该报平台拒绝")
        self.assertEqual(result.get("failed"), [])
        self.assertTrue(result.get("ok"), "本次应当成功")

    def test_this_attempts_own_error_still_reports(self) -> None:
        """但**本次自己的**失败项必须如实报。"""

        result = run_upload([STALE_ERROR, error_item("新图.jpg")], ["新图.jpg"])
        self.assertTrue(result.get("rejectedByPlatform"))
        self.assertEqual(result.get("failed"), ["新图.jpg"])
        self.assertIn("新图.jpg", result.get("reason") or "")

    def test_stale_items_are_reported_separately(self) -> None:
        """陈旧项不影响结论，但要让调用方看见——它们会一直堆着。"""

        result = run_upload([STALE_ERROR, ok_item("新图.jpg")], ["新图.jpg"])
        stale = result.get("staleQueueErrors") or []
        self.assertEqual([item["name"] for item in stale], ["主图_01_1x1.jpg"])

    def test_stale_report_present_on_the_rejected_path_too(self) -> None:
        """⚠️ **这条是修完第一个毛病后暴露的第二个。**

        `staleQueueErrors` 原先算在 `if rejected: return` **之后**，
        于是「平台拒绝」这条路径上它永远是空的——实机验证时发现的。
        """

        result = run_upload([STALE_ERROR, error_item("新图.jpg")], ["新图.jpg"])
        self.assertTrue(result.get("rejectedByPlatform"))
        stale = result.get("staleQueueErrors") or []
        self.assertEqual([item["name"] for item in stale], ["主图_01_1x1.jpg"],
                         "平台拒绝这条路径上也必须报出陈旧项")

    def test_successful_queue_item_is_not_reported_as_stale(self) -> None:
        """`success` 的项不算陈旧问题。"""

        result = run_upload([ok_item("早先成功的.jpg"), ok_item("新图.jpg")], ["新图.jpg"])
        self.assertEqual(result.get("staleQueueErrors"), [])


class SourceOrderTest(unittest.TestCase):
    def test_stale_computation_precedes_the_early_return(self) -> None:
        """顺序钉住：计算必须在提前 return 之前。"""

        import inspect

        source = inspect.getsource(page._upload_staged_files_to_media)
        self.assertLess(
            source.index("stale_rejected = ["),
            source.index('"rejectedByPlatform": True'),
            "stale_rejected 必须在提前 return 之前算好",
        )

    def test_rejection_filter_uses_this_attempts_names(self) -> None:
        """筛选必须按**本次的文件名**，不是整个队列。"""

        import inspect

        source = inspect.getsource(page._upload_staged_files_to_media)
        self.assertIn("wanted_names", source)
        self.assertIn('in wanted_names', source)


if __name__ == "__main__":
    unittest.main()

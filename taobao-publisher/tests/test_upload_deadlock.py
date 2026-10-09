# -*- coding: utf-8 -*-
"""上传的**死锁**：平台接受了，函数却报失败。

## 实机（2026-10-03 20:01，限流解除后第一次尝试）

```
ok                  = False
confirmed           = []
failed              = ['ID-探针_200110_1x1.jpg']
队列明细：
   ID-探针_200110_1x1.jpg             state=success  desc=251.18K
```

**平台明确回了 `state=success`，函数却报失败。**

## 原因：一个环

```python
arrived = wait_for_media_images(...)      # 找的是**图片空间**里的图
if arrived.ok: confirmed.append(name)
...
if confirmed: click_media_finish(...)     # 只有 confirmed 才点「完成」
ok = not failed and finish.ok
```

而 E-123 实测：

> **点「完成」让上传落库**：不点它，文件只停在上传面板里，
> 图片空间里什么都看不到，而面板上全是成功图标。

于是 `confirmed` 要求图**进空间** → 进空间要求点**「完成」** →
点「完成」要求 `confirmed`。**环。**

而 `media_image_exists` 还会剥掉 UploadPanel 子树（第 34 轮改的），
所以它**必然**看不到那个还没「完成」的文件。

**后果**：`upload_images` **每次**都报 `IMAGE_UPLOAD_FAILED`——
即使平台已经接受。这条从第 34 轮之后一直成立。

## 修法：把两件事分开

| 问题 | 判据 |
|---|---|
| 平台接不接受 | **队列状态**（平台自己的话，`state == 'success'`） |
| 落没落库 | 点「完成」**之后**再看图片空间 |

⚠️ **不降低标准**：队列里是 `error` 的仍然如实拒绝（第 34 轮那条路径不动）。

## 实机复验

```
ok = True   confirmed = ['ID-探针_200345_1x1.jpg']   failed = []
→ 上传成功并落库
```

随后完整链条 8/8 通过（含 `upload_images`）。
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


class UploadDeadlockTest(unittest.TestCase):
    def _upload(self, *, reject=False, finish_ok=True, gallery_visible=True):
        from test_stale_queue_rejection import FakeMediaClient, ok_item, error_item
        client = FakeMediaClient([(error_item if reject else ok_item)('one.jpg')])
        events = []
        evaluate = client.evaluate
        def record(expression, **kwargs):
            if 'UploadPanel_fileItem' in expression:
                events.append('queue')
            return evaluate(expression, **kwargs)
        client.evaluate = record
        def finish(*args, **kwargs):
            self.assertIn('queue', events)
            events.append('finish')
            return {'ok': finish_ok}
        def landed(*args, **kwargs):
            self.assertIn('finish', events, '图片空间只能在点完成后查询')
            events.append('landed')
            return gallery_visible
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(page, 'click_media_finish', finish), \
                mock.patch.object(page, 'media_image_exists', landed):
            path = pathlib.Path(directory) / 'one.jpg'
            path.write_bytes(b'isolated queue fixture')
            result = page.upload_files_to_media(client, [str(path)], context_id=1,
                                                wait=0, per_file_timeout=0)
        return result, events

    def test_queue_success_moves_into_confirmed(self) -> None:
        """**队列说成功的必须进 `confirmed`**——否则「完成」永远不会被点。"""

        result, _ = self._upload()
        self.assertEqual(result['confirmed'], ['one.jpg'])

    def test_accepted_removed_from_failed(self) -> None:
        """上传成功但当时还没落库的，**不能留在 `failed` 里**。"""

        result, _ = self._upload()
        self.assertEqual(result['failed'], [])
        self.assertTrue(result['ok'])

    def test_finish_is_clicked_after_acceptance(self) -> None:
        """顺序要紧：先认「平台接受」，**再**点「完成」。"""

        _, events = self._upload()
        self.assertLess(events.index('queue'), events.index('finish'))
        self.assertEqual(events.count('finish'), 1)

    def test_landed_is_checked_after_finish(self) -> None:
        """`landed` 是**点完之后**才算的——那才是落库确认。"""

        result, events = self._upload()
        self.assertEqual(result['landed'], ['one.jpg'])
        self.assertLess(events.index('finish'), events.index('landed'))

    def test_success_requires_acceptance_and_finish(self) -> None:
        """成功 = **平台接受** 且 **点了完成**，两者都要。"""

        result, events = self._upload(finish_ok=False)
        self.assertFalse(result['ok'])
        self.assertEqual(result['confirmed'], ['one.jpg'])
        self.assertNotIn('landed', events)

    def test_rejection_path_is_unchanged(self) -> None:
        """⚠️ **不降低标准**：队列里 `error` 的仍然如实拒绝。"""

        result, events = self._upload(reject=True)
        self.assertTrue(result['rejectedByPlatform'])
        self.assertFalse(result['ok'])
        self.assertNotIn('finish', events)

    def test_missing_gallery_does_not_prevent_finishing_a_successful_queue(self) -> None:
        """队列接收与严格图库回执分开，避免完成前等待图库的循环依赖。"""
        result, events = self._upload(gallery_visible=False)
        self.assertTrue(result['ok'])
        self.assertEqual(events.count('finish'), 1)
        self.assertEqual(result['landed'], [])


class ChainCoversUploadTest(unittest.TestCase):
    def test_full_chain_script_includes_upload_images(self) -> None:
        script = (SUBPROJECT / "scripts" / "smoke-full-chain-live.py").read_text(encoding="utf-8")
        self.assertIn('"upload_images"', script)

    def test_script_selects_the_compliant_images(self) -> None:
        """必须显式筛 `_1x1` 那套：另一套 1440x1920 比例 0.75，不合契约。"""

        script = (SUBPROJECT / "scripts" / "smoke-full-chain-live.py").read_text(encoding="utf-8")
        self.assertIn('MAIN_IMAGE_SUFFIX = "_1x1.jpg"', script)
        self.assertIn("MAIN_IMAGE_LIMIT = 5", script)
        self.assertIn("不合契约", script)


if __name__ == "__main__":
    unittest.main()

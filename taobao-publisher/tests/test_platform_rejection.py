# -*- coding: utf-8 -*-
"""**平台拒绝了上传，不许报成功。**

实测（2026-10-03）：

```
UploadPanel_fileDesc:
  '操作过于频繁，请滑动验证码之后，重新上传。'
UploadPanel_fileState > button > i.next-icon-error
```

平台在限流、要求过验证码——而当时 `upload_files_to_media` 报的是
``arrived: true`` / ``confirmed``。**平台拒绝了却报成功**，
于是错误以别处的 ``no_match`` 冒出来，离真正的原因很远。

这与前几轮修的那几个属于同一类：**失败被静默成了成功**。

**红线**：不绕过验证码。这一层只负责**如实报告并停下来**，人工处理之后重跑。
"""

from __future__ import annotations

import inspect
import pathlib
import sys
import unittest
import tempfile
from contextlib import ExitStack
from unittest import mock

from PIL import Image

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SUBPROJECT = REPO_ROOT / "taobao-publisher"
if str(SUBPROJECT) not in sys.path:
    sys.path.insert(0, str(SUBPROJECT))

from taobao_publish import page, stages  # noqa: E402
from taobao_publish.errors import ERROR_CATALOG  # noqa: E402
from taobao_publish.models import PublishItem, ImageSet


class PlatformRejectionTest(unittest.TestCase):
    def _rejected_stage(self, reason):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            path = pathlib.Path(directory) / 'main.jpg'
            Image.new('RGB', (800, 800), 'white').save(path)
            ctx = stages.PipelineContext(item=PublishItem(record_id=1, record_name='ID-1',
                title='仅本地测试', images=ImageSet(main=[str(path)])), dry_run=False)
            client = mock.Mock()
            client.evaluate.return_value = {'ok': True, 'supported': False, 'path': []}
            stack.enter_context(mock.patch.object(stages, '_open_publish_page', return_value=client))
            stack.enter_context(mock.patch.object(page, 'read_main_image_slots', return_value={'found': True, 'filled': 0}))
            stack.enter_context(mock.patch.object(page, 'open_media_popup'))
            stack.enter_context(mock.patch.object(page, 'read_media_popup', return_value={'open': True}))
            stack.enter_context(mock.patch.object(page, 'media_iframe_context', return_value=1))
            stack.enter_context(mock.patch.object(page, 'find_media_images', side_effect=lambda c, names, **k:
                {'receipts': {}, 'missing': list(names)}))
            upload = stack.enter_context(mock.patch.object(page, 'upload_files_to_media',
                return_value={'ok': False, 'rejectedByPlatform': True, 'reason': reason}))
            select = stack.enter_context(mock.patch.object(page, 'select_media_image'))
            result = stages.stage_upload_images(ctx)
            upload.assert_called_once()
            select.assert_not_called()
            return result

    def test_queue_reader_reports_per_item_state(self) -> None:
        expression = page.build_read_media_queue_expression()
        for marker in ("next-icon-success", "next-icon-error", "next-icon-loading"):
            self.assertIn(marker, expression, "要能区分成功 / 失败 / 上传中")
        self.assertIn("UploadPanel_fileDesc", expression, "要读平台给的说明文案")

    def test_queue_reader_never_invents_a_reason(self) -> None:
        """平台没给原因时**不许编一个**——如实留空。"""

        source = inspect.getsource(page.read_media_queue_state)
        self.assertNotIn("默认", source)
        expression = page.build_read_media_queue_expression()
        # desc 直接取自 DOM，没有回落文案
        self.assertIn("descEl ? (descEl.textContent || '').trim()", expression)

    def test_upload_checks_the_queue_before_finishing(self) -> None:
        """检查必须在点「完成」**之前**——完成后队列就清空了，读不到原因。"""

        source = inspect.getsource(page._upload_staged_files_to_media)
        self.assertLess(
            source.index("read_media_queue_state("),
            source.index("click_media_finish("),
            "要先读队列状态，再点完成",
        )

    def test_upload_reports_platform_rejection(self) -> None:
        source = inspect.getsource(page._upload_staged_files_to_media)
        self.assertIn("rejectedByPlatform", source)
        self.assertIn('"reason"', source)
        # 被平台拒绝时不能报 ok
        self.assertIn('"ok": False', source)

    def test_error_catalog_explains_not_to_bypass(self) -> None:
        """错误目录里必须写明「不要尝试绕过」。"""

        spec = ERROR_CATALOG.get("VERIFICATION_REQUIRED")
        self.assertIsNotNone(spec, "必须有 VERIFICATION_REQUIRED 这个码")
        text = repr(spec)
        self.assertIn("绕过", text, "要明确写出不要绕过")

    def test_stage_maps_rejection_to_verification_required(self) -> None:
        result = self._rejected_stage('操作过于频繁，请滑动验证码之后，重新上传。')
        self.assertFalse(result.ok)
        self.assertEqual(result.error_code, 'VERIFICATION_REQUIRED')
        self.assertIn('平台拒绝了上传', result.summary)

    def test_stage_does_not_attempt_to_solve_the_captcha(self) -> None:
        """**红线**：不许有任何「自动过验证码」的代码。

        ⚠️ **检查的是标识符名，不是源码原文。**

        第一版直接搜文本，被**文档字符串里引用的平台原话**命中了
        （``操作过于频繁，请滑动验证码之后，重新上传。``）。这是同一个教训的
        第四次：检查要作用在**结构**上，而不是原文上——**名字不可能是文档字符串**。
        """

        import ast as _ast

        forbidden_words = ("captcha", "geetest", "slider", "slide_to", "drag",
                           "bypass", "verification_code")
        for module in (page, stages):
            tree = _ast.parse(pathlib.Path(module.__file__).read_text(encoding="utf-8"))
            names = []
            for node in _ast.walk(tree):
                if isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef, _ast.ClassDef)):
                    names.append(node.name)
                elif isinstance(node, _ast.Name):
                    names.append(node.id)
                elif isinstance(node, _ast.Attribute):
                    names.append(node.attr)
                elif isinstance(node, _ast.arg):
                    names.append(node.arg)
            for name in names:
                lowered = name.lower()
                for word in forbidden_words:
                    self.assertNotIn(
                        word, lowered,
                        "{} 里出现了疑似绕过验证码的标识符：{}".format(module.__name__, name),
                    )

    def test_rejection_reason_is_quoted_verbatim_not_paraphrased(self) -> None:
        """平台给的原因要**原样**带出来，不要改写成一个笼统的说法。

        改写会丢信息：``操作过于频繁，请滑动验证码之后，重新上传。``
        直接告诉人该做什么；改成「上传失败」就什么也没说。
        """

        reason = '测试图.jpg：操作过于频繁，请滑动验证码之后，重新上传。'
        self.assertIn(reason, self._rejected_stage(reason).summary)


if __name__ == "__main__":
    unittest.main()

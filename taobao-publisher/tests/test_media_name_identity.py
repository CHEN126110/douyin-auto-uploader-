# -*- coding: utf-8 -*-
"""图片空间「按名字」这件事必须可靠——否则会**静默用错图**。

踩出来的两个缺陷（2026-10-03）：

1. **采集目录里的主图名不含商品标识**（``主图_01_1x1.jpg``），而图片空间是
   **店铺级**的。于是两个商品的主图同名，「按名字判断图已在空间里 → 跳过上传」
   会把**上一个商品的图**当成这个商品的图选进去。
2. **选图在命中多张时静默挑了第一张**：实测同一个名字能命中 3 张，
   而当时只判 ``ok``，不判 ``matched``。

两处都是「悄悄产出错误发布结果」，正是项目红线禁止的那一类。
"""

from __future__ import annotations

import inspect
import pathlib
import sys
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SUBPROJECT = REPO_ROOT / "taobao-publisher"
if str(SUBPROJECT) not in sys.path:
    sys.path.insert(0, str(SUBPROJECT))

from taobao_publish import page, stages, form_adapters  # noqa: E402


class MediaNameIdentityTest(unittest.TestCase):
    def test_select_refuses_when_more_than_one_card_matches(self) -> None:
        """命中不是恰好 1 张就拒绝——**不能挑第一张**。"""

        source = inspect.getsource(page._media_image_result)
        self.assertIn("matched != 1", source)
        self.assertIn("拒绝猜", source)

    def test_unidentified_product_cannot_create_a_media_identity(self) -> None:
        """没有有效商品ID不能用通用前缀上传，防止不同商品共享素材身份。"""
        for record_id in (0, -1, True, 7.0, None):
            with self.subTest(record_id=record_id):
                with self.assertRaises(page.PageError):
                    form_adapters.media_file_identity('never-opened.jpg', record_id, 'main', slot=1)

    def test_stage_uses_scoped_names_for_upload_and_selection(self) -> None:
        """上传名与选图名必须是**同一个带前缀的名字**。

        只有一处改名的话，上传出去叫新名字、选图却按老名字找——直接找不到。
        """

        source = inspect.getsource(stages.stage_upload_images)
        self.assertIn("media_file_identity(path, ctx.item.record_id, 'main', slot=index + 1)", source)
        self.assertIn("main_identities=identities", source)
        preparation = inspect.getsource(form_adapters.prepare_media)
        self.assertIn("expected_sha256=", preparation)
        self.assertIn("rename_to=list(pending)", preparation)
        # 选图用的是 names，也就是带前缀的那一份
        self.assertIn("page.select_media_image(client, name,", source)


class UploadRenameTest(unittest.TestCase):
    def test_upload_supports_rename_to(self) -> None:
        signature = inspect.signature(page.upload_files_to_media)
        self.assertIn("rename_to", signature.parameters)

    def test_rename_copies_to_a_temp_file_and_cleans_up(self) -> None:
        """改名不能动原文件——采集目录是只读资产。"""

        source = inspect.getsource(page.upload_files_to_media)
        self.assertIn("tempfile.mkdtemp", source)
        self.assertIn("shutil.copy2", source)
        self.assertIn("shutil.rmtree", source)
        self.assertIn("ignore_errors=True", source, "清理失败不该盖过主流程的结果")

    def test_rename_length_mismatch_is_rejected(self) -> None:
        source = inspect.getsource(page.upload_files_to_media)
        self.assertIn("rename_to 的长度必须与 files 一致", source)

    def test_upload_uses_the_renamed_path_when_setting_files(self) -> None:
        import tempfile
        from unittest.mock import patch
        from test_stale_queue_rejection import FakeMediaClient, ok_item
        client = FakeMediaClient([ok_item('renamed.jpg')])
        received = []
        def receive(files, selector, **kwargs):
            received.extend((pathlib.Path(p).name, pathlib.Path(p).read_bytes()) for p in files)
            return {'ok': True}
        client.set_file_input_files = receive
        with tempfile.TemporaryDirectory() as directory, patch.object(page.time, 'sleep', lambda *_: None):
            source = pathlib.Path(directory) / 'original.jpg'
            source.write_bytes(b'exact source image')
            result = page.upload_files_to_media(client, [str(source)], context_id=1,
                                               rename_to=['renamed.jpg'])
        self.assertTrue(result['ok'])
        self.assertEqual(received, [('renamed.jpg', b'exact source image')])


if __name__ == "__main__":
    unittest.main()

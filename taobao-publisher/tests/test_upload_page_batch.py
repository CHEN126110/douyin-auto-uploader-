# -*- coding: utf-8 -*-
"""`upload_page.PictureSpacePageUploader` 的整批语义（**此前没有任何测试**）。

## 为什么补这个文件

协议上传这条路上，真正"发请求"的是 `upload_page`（页面内 XHR）。
它此前**零测试覆盖**：`test_upload_api.py` 覆盖的是纯计算层（URL/multipart/分类），
`test_upload_client.py` 那侧覆盖的是 Python 传输层，都不碰这个类。

而它承载着三件**一旦错了就会伤到用户**的事：

1. **写授权门**：没授权时一个请求都不该发；
2. **风控即停**：命中风控立刻停手、**不重试**，并把人工验证入口交出来；
3. **已成功的回执必须留住**：风控打断后，前面成功的图靠这些回执+账本跳过，
   不必整批重来（`on_receipt` 每张成功立刻回调就是为这个）。

用替身把平台边界换掉（不发任何真实请求、不碰浏览器、不读本地文件）。
"""

from __future__ import annotations

import json
import unittest
from unittest import mock

from taobao_publish.authorization import WriteAuthorization
from taobao_publish.errors import WriteNotAuthorizedError
from taobao_publish.upload_api import UploadCandidate
from taobao_publish.upload_page import PictureSpacePageUploader

CDN = "https://img.alicdn.com/imgextra/i4/2214966481149"


def ok_payload(index: int) -> str:
    return json.dumps({
        "success": True,
        "object": {"url": "%s/O1CN01probe%s_!!2214966481149.jpg" % (CDN, index),
                   "fileId": "pic-%s" % index,
                   "size": 12345},
    }, ensure_ascii=False)


#: 风控的真实形态：**既没有 `success` 也没有 `errorCode`**，只有 `ret` 与 data.url。
RISK_PAYLOAD = json.dumps({
    "ret": ["FAIL_SYS_USER_VALIDATE", "RGV587_ERROR::SM::哎哟喂,被挤爆啦,请稍后重试"],
    "data": {"url": "https://h5api.m.taobao.com/_____tmd_____/punish?x5secdata=abc&action=captcha"},
}, ensure_ascii=False)

#: 平台业务拒绝（例如传了 1x1 图）。
REJECT_PAYLOAD = json.dumps({
    "success": False, "errorCode": "NOT_ALLOW_UPLOAD_1x1_IMAGE", "errorMsg": "不允许上传 1x1 图片",
}, ensure_ascii=False)

#: 声称成功但没有图片地址——**不能拿它去选图**。
NO_URL_PAYLOAD = json.dumps({"success": True, "object": {}}, ensure_ascii=False)


class FakeSession:
    """只实现 `upload_batch` 用到的两个方法；每次调用弹一条预置响应。"""

    def __init__(self, responses, token="tb-token-1"):
        self._responses = list(responses)
        self._token = token
        self.sent = []
        self.token_reads = 0

    def read_tb_token(self):
        self.token_reads += 1
        return self._token

    def send_form_data(self, url, *, file_path, filename, fields, content_type):
        self.sent.append({"url": url, "filename": filename,
                          "fields": list(fields), "content_type": content_type})
        return self._responses.pop(0)


def candidates(count):
    return [UploadCandidate(path="C:/none/%d.jpg" % i, name="tb_probe_%d.jpg" % i, size=1000 + i)
            for i in range(count)]


AUTH = WriteAuthorization.for_form_filling()


class AuthorizationGateTest(unittest.TestCase):
    def test_no_upload_authorization_means_no_request_at_all(self) -> None:
        session = FakeSession([(200, ok_payload(1))])
        uploader = PictureSpacePageUploader(session)
        with self.assertRaises(WriteNotAuthorizedError):
            uploader.upload_batch(candidates(1), folder_id="222",
                                  authorization=WriteAuthorization.none())
        self.assertEqual([], session.sent, "未授权时一个请求都不该发")


class BatchSemanticsTest(unittest.TestCase):
    def test_batch_sends_in_order_and_collects_receipts(self) -> None:
        session = FakeSession([(200, ok_payload(1)), (200, ok_payload(2)), (200, ok_payload(3))])
        seen, progress = [], []
        report = PictureSpacePageUploader(session).upload_batch(
            candidates(3), folder_id="222", authorization=AUTH,
            progress=progress.append, on_receipt=seen.append)

        self.assertTrue(report.ok, report.to_dict())
        self.assertEqual(3, len(report.receipts))
        self.assertEqual(["tb_probe_0.jpg", "tb_probe_1.jpg", "tb_probe_2.jpg"],
                         [r.name for r in report.receipts])
        self.assertEqual([r.name for r in report.receipts], [r.name for r in seen],
                         "on_receipt 必须逐张、按顺序回调（断点续传靠它）")
        self.assertEqual(3, len(progress))
        self.assertEqual(1, session.token_reads, "整批只读一次 token")
        # URL 契约：目录由 folderId 决定（query 里必须带上目标目录）。
        self.assertIn("folderId=222", session.sent[0]["url"])

    def test_rate_limit_stops_the_batch_but_keeps_earlier_receipts(self) -> None:
        """**这条最重要**：风控即停、不重试，且已成功的回执一张都不能丢。"""

        session = FakeSession([(200, ok_payload(1)), (200, RISK_PAYLOAD), (200, ok_payload(3))])
        report = PictureSpacePageUploader(session).upload_batch(
            candidates(3), folder_id="222", authorization=AUTH)

        self.assertFalse(report.ok)
        self.assertTrue(report.stopped_reason, "风控必须给出停手原因")
        self.assertIn("人工", report.stopped_reason)
        self.assertEqual(1, len(report.receipts), "第一张的回执必须留住，否则下次要整批重来")
        self.assertEqual("tb_probe_0.jpg", report.receipts[0].name)
        self.assertEqual(2, report.attempted)
        self.assertEqual(2, len(session.sent), "命中风控后**不许**再发第三张")
        self.assertIn("punish", report.challenge_url, "人工验证入口要交出来（给人用，程序不碰）")

    def test_business_rejection_does_not_stop_the_batch(self) -> None:
        """平台业务拒绝（如 1x1 图）只算这一张失败，不该拖累整批。"""

        session = FakeSession([(200, ok_payload(1)), (200, REJECT_PAYLOAD), (200, ok_payload(3))])
        report = PictureSpacePageUploader(session).upload_batch(
            candidates(3), folder_id="222", authorization=AUTH)

        self.assertFalse(report.ok)
        self.assertFalse(report.stopped_reason, "业务失败不是风控，不该停手")
        self.assertEqual(3, report.attempted)
        self.assertEqual(2, len(report.receipts))
        self.assertEqual(1, len(report.failed))
        self.assertIn("1x1", json.dumps(report.failed, ensure_ascii=False))

    def test_success_without_url_is_a_failure_not_a_receipt(self) -> None:
        session = FakeSession([(200, NO_URL_PAYLOAD)])
        report = PictureSpacePageUploader(session).upload_batch(
            candidates(1), folder_id="222", authorization=AUTH)

        self.assertEqual(0, len(report.receipts))
        self.assertIn("没有图片地址", json.dumps(report.failed, ensure_ascii=False))

    def test_pace_waits_between_images_but_not_after_the_last(self) -> None:
        session = FakeSession([(200, ok_payload(1)), (200, ok_payload(2)), (200, ok_payload(3))])
        with mock.patch("taobao_publish.upload_page.time.sleep") as sleep:
            PictureSpacePageUploader(session).upload_batch(
                candidates(3), folder_id="222", authorization=AUTH, pace_seconds=1.2)
        self.assertEqual(2, sleep.call_count, "3 张之间只该有 2 次间隔")
        sleep.assert_called_with(1.2)


class LocalGuardTest(unittest.TestCase):
    def test_oversize_image_is_rejected_before_any_request(self) -> None:
        oversize = UploadCandidate(path="C:/none/big.jpg", name="big.jpg", size=4 * 1024 * 1024)
        session = FakeSession([(200, ok_payload(1))])
        with self.assertRaises(ValueError):
            PictureSpacePageUploader(session).upload_batch(
                [oversize], folder_id="222", authorization=AUTH)
        self.assertEqual([], session.sent, "本地护栏要在发出请求之前拦住")

    def test_disallowed_suffix_is_rejected_before_any_request(self) -> None:
        bad = UploadCandidate(path="C:/none/x.pdf", name="x.pdf", size=1000)
        session = FakeSession([(200, ok_payload(1))])
        with self.assertRaises(ValueError):
            PictureSpacePageUploader(session).upload_batch(
                [bad], folder_id="222", authorization=AUTH)
        self.assertEqual([], session.sent)

    def test_local_suffix_whitelist_is_pinned(self) -> None:
        """把本地格式白名单**钉住**——它比平台页面自述的还窄。

        平台上传面板的原文（E-224 真机读到的文案）写着支持
        `JPG/BMP/GIF/HEIC/PNG/JPEG/WEBP`，而本仓库的本地护栏只允许
        `jpg/jpeg/gif/png/bmp` —— 即 **WEBP / HEIC 会在本地被拒**。
        这是"宁可早拒"的取舍，但**不是**可以悄悄改的东西：
        要放宽就得先有"平台确实收 WEBP/HEIC"的实测证据，所以这里显式钉住现值。
        """

        from taobao_publish.upload_api import ALLOWED_SUFFIXES

        self.assertEqual((".jpg", ".jpeg", ".gif", ".png", ".bmp"), ALLOWED_SUFFIXES)


if __name__ == "__main__":
    unittest.main()

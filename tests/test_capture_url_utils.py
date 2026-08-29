# -*- coding: utf-8 -*-

from __future__ import annotations

import sys
import unittest
from pathlib import Path

SIDECAR_DIR = Path(__file__).resolve().parents[1] / "tauri-app" / "python-sidecar"
sys.path.insert(0, str(SIDECAR_DIR))

from capture_url_utils import (  # noqa: E402
    capture_url_host,
    extract_first_capture_url,
    is_supported_capture_host,
    is_taobao_short_link,
    normalize_capture_url,
)


class CaptureUrlUtilsTest(unittest.TestCase):
    def test_extracts_url_from_taobao_share_text(self) -> None:
        raw = "复制打开淘宝： https://m.tb.cn/h.abc123?tk=AbCd 。"
        self.assertEqual(
            extract_first_capture_url(raw),
            "https://m.tb.cn/h.abc123?tk=AbCd",
        )

    def test_normalizes_domain_without_scheme(self) -> None:
        self.assertEqual(
            normalize_capture_url("item.taobao.com/item.htm?id=123"),
            "https://item.taobao.com/item.htm?id=123",
        )

    def test_accepts_taobao_short_link_hosts(self) -> None:
        self.assertTrue(is_taobao_short_link("https://m.tb.cn/h.abc123"))
        self.assertTrue(is_supported_capture_host("https://tb.cn/h.abc123"))

    def test_keeps_supported_standard_hosts(self) -> None:
        self.assertEqual(
            capture_url_host("https://detail.1688.com/offer/123.html"),
            "detail.1688.com",
        )
        self.assertTrue(is_supported_capture_host("https://detail.tmall.com/item.htm?id=123"))

    def test_rejects_unrelated_host(self) -> None:
        self.assertFalse(is_supported_capture_host("https://example.com/item"))


if __name__ == "__main__":
    unittest.main()

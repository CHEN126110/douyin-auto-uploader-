# -*- coding: utf-8 -*-

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sidecar_function_source import upload_text  # noqa: E402


class SidecarUploadSafetyTest(unittest.TestCase):
    def test_upload_start_routes_use_final_publish_confirmation_gate(self) -> None:
        # 判定在 UploadService.resolve_stop_before_submit，接口在 upload_routes.py：读 app.py + upload_*.py 的全文
        source = upload_text()
        self.assertIn("def resolve_stop_before_submit", source)

        upload_start_body = source.split("def upload_start():", 1)[1].split(
            "def upload_status", 1
        )[0]
        upload_all_body = source.split("def upload_start_all():", 1)[1].split(
            "def upload_batch", 1
        )[0]

        self.assertIn("service.resolve_stop_before_submit", upload_start_body)
        self.assertIn("service.resolve_stop_before_submit", upload_all_body)
        self.assertIn("confirm_final_publish", source)


if __name__ == "__main__":
    unittest.main()

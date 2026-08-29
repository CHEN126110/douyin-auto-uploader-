# -*- coding: utf-8 -*-

from __future__ import annotations

import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_PATH = PROJECT_ROOT / "tauri-app" / "python-sidecar" / "app.py"


class SidecarUploadSafetyTest(unittest.TestCase):
    def test_upload_start_routes_use_final_publish_confirmation_gate(self) -> None:
        source = APP_PATH.read_text(encoding="utf-8")
        self.assertIn("def _resolve_upload_stop_before_submit", source)

        upload_start_body = source.split("def upload_start():", 1)[1].split(
            "def upload_status", 1
        )[0]
        upload_all_body = source.split("def upload_start_all():", 1)[1].split(
            "def upload_batch", 1
        )[0]

        self.assertIn("_resolve_upload_stop_before_submit", upload_start_body)
        self.assertIn("_resolve_upload_stop_before_submit", upload_all_body)
        self.assertIn("confirm_final_publish", source)


if __name__ == "__main__":
    unittest.main()

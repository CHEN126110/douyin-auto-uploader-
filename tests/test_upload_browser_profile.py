# -*- coding: utf-8 -*-

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.utils import _get_persistent_browser_user_data_path


class UploadBrowserProfileTest(unittest.TestCase):
    def test_upload_browser_profile_uses_stable_data_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            old_value = os.environ.get("DOUYIN_DATA_DIR")
            os.environ["DOUYIN_DATA_DIR"] = tmp_dir
            try:
                profile_path = Path(_get_persistent_browser_user_data_path())
            finally:
                if old_value is None:
                    os.environ.pop("DOUYIN_DATA_DIR", None)
                else:
                    os.environ["DOUYIN_DATA_DIR"] = old_value

        self.assertEqual(profile_path, Path(tmp_dir) / "upload-browser-profile")
        self.assertNotIn("DrissionPage", str(profile_path))


if __name__ == "__main__":
    unittest.main()

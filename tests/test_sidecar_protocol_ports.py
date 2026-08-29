# -*- coding: utf-8 -*-

from __future__ import annotations

import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_PATH = PROJECT_ROOT / "tauri-app" / "python-sidecar" / "app.py"


class SidecarProtocolPortsTest(unittest.TestCase):
    def test_protocol_jinritemai_cdp_scan_includes_debug_browser_ports(self) -> None:
        source = APP_PATH.read_text(encoding="utf-8")
        helper_body = source.split("def _protocol_cdp_port_candidates():", 1)[1].split(
            "def _find_cdp_port_with_jinritemai", 1
        )[0]
        finder_body = source.split("def _find_cdp_port_with_jinritemai():", 1)[1].split(
            "def _ensure_protocol_browser", 1
        )[0]

        self.assertIn("_DEBUG_BROWSER_PORT_START", helper_body)
        self.assertIn("_DEBUG_BROWSER_PORT_END", helper_body)
        self.assertIn("_protocol_cdp_port_candidates()", finder_body)


if __name__ == "__main__":
    unittest.main()

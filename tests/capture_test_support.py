# -*- coding: utf-8 -*-
"""链接采集模块（src/sidecar/capture_*.py）的测试夹具。

2026-10-20 采集从 ``app.py`` 拆成 ``capture_helpers``（无状态函数）、``capture_service``（``CaptureService``）、
``capture_routes``（五个接口）。旧测试靠按名字从 ``app.py`` 源码里抽函数再 ``exec``；现在直接构造真实的服务对象，
所有外部依赖（浏览器、端口探测、协议引擎、路径规则）都用假件注入，不导入 ``app.py``、不碰真实数据库。
"""
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.sidecar import capture_helpers, capture_routes, capture_service  # noqa: E402,F401
from src.sidecar.capture_routes import create_capture_blueprint  # noqa: E402
from src.sidecar.capture_service import CaptureService  # noqa: E402


def make_service(**overrides):
    """所有依赖都是无害的假件；用例按需覆盖其中几个。"""
    deps = dict(
        record_model=None,
        logger=logging.getLogger('capture-test'),
        protocol_capture_engine=None,
        find_cdp_port=lambda: None,
        load_capture_attributes=lambda: None,
        normalize_save_path=lambda path: path,
        is_local_port_available=lambda host, port: True,
        normalize_debug_address=lambda address: address,
        verify_debug_browser=lambda address, timeout=None: {'ok': True},
        discover_browsers=lambda verify=False: [],
        debug_host='127.0.0.1',
        capture_port_start=9400,
        capture_port_end=9402,
    )
    deps.update(overrides)
    return CaptureService(**deps)


def make_blueprint(service, **overrides):
    deps = dict(service=service, normalize_save_path=lambda path: path, get_app_root=lambda: '.', settings_manager=None)
    deps.update(overrides)
    return create_capture_blueprint(**deps)

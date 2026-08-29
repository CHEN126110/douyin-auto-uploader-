# -*- coding: utf-8 -*-
"""business_api 核心层：驱动、上下文、统一响应与错误码。"""
from .context import BrowserContext, CaptchaGuard, HumanPacer
from .driver import BrowserDriver, DrissionDriver, connect_chromium
from .errors import BusinessApiError, ErrorCode
from .launcher import (
    debug_endpoint_alive,
    ensure_browser,
    find_chrome,
    launch_debug_chrome,
)
from .responses import (
    envelope_from_error,
    err_envelope,
    http_status_for,
    ok_envelope,
)

__all__ = [
    "ErrorCode",
    "BusinessApiError",
    "ok_envelope",
    "err_envelope",
    "envelope_from_error",
    "http_status_for",
    "BrowserDriver",
    "DrissionDriver",
    "connect_chromium",
    "find_chrome",
    "debug_endpoint_alive",
    "launch_debug_chrome",
    "ensure_browser",
    "HumanPacer",
    "CaptchaGuard",
    "BrowserContext",
]

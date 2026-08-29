# -*- coding: utf-8 -*-
"""统一响应封装。

返回结构（envelope）：
    {
        "ok": bool,
        "code": str,         # ErrorCode
        "message": str,
        "hint": str | None,  # 修复建议（错误时常见）
        "data": Any,
    }
"""
from __future__ import annotations

from typing import Any, Optional

from .errors import BusinessApiError, ErrorCode


def ok_envelope(message: str = "OK", data: Any = None) -> dict:
    return {
        "ok": True,
        "code": ErrorCode.OK,
        "message": message,
        "hint": None,
        "data": data,
    }


def err_envelope(
    message: str,
    code: str = ErrorCode.UNKNOWN,
    hint: Optional[str] = None,
    data: Any = None,
) -> dict:
    return {
        "ok": False,
        "code": code,
        "message": message,
        "hint": hint,
        "data": data,
    }


def envelope_from_error(exc: BusinessApiError, data: Any = None) -> dict:
    """从 BusinessApiError 构造错误响应。data 为空时回落到异常的 context。"""
    return {
        "ok": False,
        "code": exc.code,
        "message": exc.message,
        "hint": exc.hint,
        "data": data if data is not None else (exc.context or None),
    }


# 业务错误码 → HTTP 状态码。便于调用方用状态码快速判断大类。
HTTP_STATUS_BY_CODE = {
    ErrorCode.OK: 200,
    ErrorCode.INVALID_PARAM: 400,
    ErrorCode.LOGIN_REQUIRED: 401,
    ErrorCode.CAPTCHA_REQUIRED: 423,   # Locked：需人工解锁
    ErrorCode.RATE_LIMITED: 429,
    ErrorCode.NOT_IMPLEMENTED: 501,
    ErrorCode.BROWSER_NOT_READY: 503,
    ErrorCode.ELEMENT_NOT_FOUND: 502,
    ErrorCode.WAIT_TIMEOUT: 504,
    ErrorCode.PAGE_STRUCTURE_CHANGED: 502,
    ErrorCode.ACTION_FAILED: 500,
    ErrorCode.UPSTREAM_ERROR: 502,
    ErrorCode.UNKNOWN: 500,
}


def http_status_for(code: str) -> int:
    return HTTP_STATUS_BY_CODE.get(code, 500)

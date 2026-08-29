# -*- coding: utf-8 -*-
"""业务域路由基础设施：上下文工厂、统一异常处理、参数校验、骨架路由注册。"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import wraps
from typing import Any, Callable, List, Optional

from flask import jsonify, request

from ..core import (
    BrowserContext,
    BusinessApiError,
    ErrorCode,
    connect_chromium,
    envelope_from_error,
    err_envelope,
    http_status_for,
    ok_envelope,
)

# --- 上下文工厂（可注入，便于测试 / 集成复用 app.py 会话） ---
_context_factory: Optional[Callable[[], BrowserContext]] = None


def set_context_factory(factory: Optional[Callable[[], BrowserContext]]) -> None:
    """注入自定义的 BrowserContext 工厂。测试或与 app.py 会话集成时使用。"""
    global _context_factory
    _context_factory = factory


def get_context() -> BrowserContext:
    if _context_factory is not None:
        return _context_factory()
    address = os.environ.get("DOUYIN_CHROME_ADDRESS", "127.0.0.1:9222")
    driver = connect_chromium(address)
    return BrowserContext(driver)


# --- 统一响应 / 异常处理 ---
def json_ok(message: str = "OK", data: Any = None, status: int = 200):
    return jsonify(ok_envelope(message, data)), status


def json_err(message: str, code: str = ErrorCode.UNKNOWN, hint=None, data=None):
    return jsonify(err_envelope(message, code, hint, data)), http_status_for(code)


def handle_errors(fn: Callable) -> Callable:
    """路由装饰器：把异常统一转成结构化错误响应，保证不返回裸 500 HTML。"""

    @wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except BusinessApiError as exc:
            return jsonify(envelope_from_error(exc)), http_status_for(exc.code)
        except Exception as exc:  # 兜底：保证返回结构化错误
            return (
                jsonify(
                    err_envelope(
                        f"接口内部错误：{exc}",
                        ErrorCode.UNKNOWN,
                        hint="这是未预期的异常，请反馈该错误信息以便排查。",
                    )
                ),
                500,
            )

    return wrapper


# --- 参数校验（轻量，不引入额外依赖） ---
def get_json() -> dict:
    return request.get_json(silent=True) or {}


def require_params(data: dict, required: List[str]) -> None:
    missing = [k for k in required if data.get(k) in (None, "")]
    if missing:
        raise BusinessApiError(
            ErrorCode.INVALID_PARAM,
            f"缺少必填参数：{', '.join(missing)}",
            hint="请在请求体中补全这些字段后重试。",
            context={"missing": missing},
        )


def as_int(data: dict, key: str, default: int) -> int:
    try:
        return int(data.get(key, default))
    except (TypeError, ValueError):
        return default


# --- 骨架端点（未联调真实页面的接口契约占位） ---
@dataclass
class SkeletonEndpoint:
    method: str
    path: str
    name: str
    summary: str
    params: List[dict] = field(default_factory=list)


def register_skeleton(bp, endpoints: List[SkeletonEndpoint], domain: str) -> None:
    """把契约占位接口注册到 blueprint。

    这些接口可被调用并返回完整契约说明，但真实 DOM 编排待联调，统一返回 NOT_IMPLEMENTED。
    这样 API 面是完整的、可被前端 / 调用方对接，后续逐个填充真实实现即可。
    """
    for ep in endpoints:

        def make_view(ep: SkeletonEndpoint = ep):
            def view(**kwargs):
                return (
                    jsonify(
                        err_envelope(
                            f"接口 [{domain}] {ep.name} 尚未联调真实页面。",
                            ErrorCode.NOT_IMPLEMENTED,
                            hint="该接口契约已定义，需在真实登录环境抓取页面选择器后实现。",
                            data={
                                "domain": domain,
                                "name": ep.name,
                                "method": ep.method,
                                "path": ep.path,
                                "summary": ep.summary,
                                "params": ep.params,
                                "path_args": kwargs,
                            },
                        )
                    ),
                    http_status_for(ErrorCode.NOT_IMPLEMENTED),
                )

            return view

        bp.add_url_rule(
            ep.path,
            endpoint=f"{domain}_{ep.name}",
            view_func=make_view(),
            methods=[ep.method],
        )

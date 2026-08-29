# -*- coding: utf-8 -*-
"""业务 API 统一错误码与异常定义。

错误信息要求可诊断：每个异常都应说明【哪一步失败、失败原因、关联元素、能否自行修复、建议动作】，
避免出现"失败 / 未知错误 / 请重试"这类无信息量的报错。
"""
from __future__ import annotations

from typing import Any, Optional


class ErrorCode:
    """字符串错误码常量。调用方可据此做分支处理，不依赖中文文案。"""

    OK = "OK"
    INVALID_PARAM = "INVALID_PARAM"                    # 入参缺失或非法
    NOT_IMPLEMENTED = "NOT_IMPLEMENTED"                # 接口为骨架，尚未联调真实页面
    BROWSER_NOT_READY = "BROWSER_NOT_READY"            # 浏览器未连接 / 会话不可用
    LOGIN_REQUIRED = "LOGIN_REQUIRED"                  # 未登录或登录态失效
    ELEMENT_NOT_FOUND = "ELEMENT_NOT_FOUND"            # 页面元素未找到（选择器失效或页面未加载）
    WAIT_TIMEOUT = "WAIT_TIMEOUT"                      # 等待条件超时
    ACTION_FAILED = "ACTION_FAILED"                    # DOM 动作执行失败
    PAGE_STRUCTURE_CHANGED = "PAGE_STRUCTURE_CHANGED"  # 页面结构与预期不符（疑似改版）
    CAPTCHA_REQUIRED = "CAPTCHA_REQUIRED"              # 命中验证码 / 风控，需要人工处理
    RATE_LIMITED = "RATE_LIMITED"                      # 触发本地真人节奏控频
    UPSTREAM_ERROR = "UPSTREAM_ERROR"                  # 平台页面返回业务错误
    UNKNOWN = "UNKNOWN"                                # 兜底未知错误


class BusinessApiError(Exception):
    """业务 API 统一异常。

    Attributes:
        code: ErrorCode 之一，供程序分支判断。
        message: 面向人的清晰描述（哪一步 + 原因）。
        hint: 可选，给调用者 / 用户的修复建议。
        context: 可选，关联上下文（如 locator、url、stage），便于排障。
    """

    def __init__(
        self,
        code: str,
        message: str,
        hint: Optional[str] = None,
        context: Optional[dict] = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = hint
        self.context: dict = context or {}

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "message": self.message,
            "hint": self.hint,
            "context": self.context,
        }

    def __repr__(self) -> str:  # pragma: no cover - 仅用于调试输出
        return f"BusinessApiError(code={self.code!r}, message={self.message!r})"

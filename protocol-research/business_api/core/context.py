# -*- coding: utf-8 -*-
"""浏览器执行上下文：真人节奏控频、验证码人工接管、登录态检查。

合规要点：
- HumanPacer 强制操作间隔与频率上限，避免高频自动化对抗平台限流。
- CaptchaGuard 命中验证码 / 风控时一律抛 CAPTCHA_REQUIRED 交人工处理，绝不自动破解。
- BrowserContext 是业务域编排统一入口：每个写动作前先控频 + 验证码检测。
"""
from __future__ import annotations

import random
import time
from typing import List, Optional, Sequence

from .driver import BrowserDriver
from .errors import BusinessApiError, ErrorCode

# 登录页 URL 特征：导航后命中其一即视为未登录 / 登录态失效。
# 用 URL 重定向判断比猜测页面元素 class 稳健得多。
DEFAULT_LOGIN_URL_MARKERS = (
    "/login",
    "/passport",
    "/sso",
    "sso.",
    "login.jinritemai",
    "/account/login",
)


class HumanPacer:
    """真人节奏控频：最小间隔 + 随机抖动 + 每分钟次数上限。"""

    def __init__(
        self,
        min_interval: float = 0.8,
        jitter: float = 0.6,
        max_actions_per_min: int = 40,
    ) -> None:
        self.min_interval = max(0.0, min_interval)
        self.jitter = max(0.0, jitter)
        self.max_actions_per_min = max(1, max_actions_per_min)
        self._last_ts = 0.0
        self._window_start = time.time()
        self._count_in_window = 0

    def wait_turn(self) -> None:
        now = time.time()
        if now - self._window_start >= 60:
            self._window_start = now
            self._count_in_window = 0
        if self._count_in_window >= self.max_actions_per_min:
            raise BusinessApiError(
                ErrorCode.RATE_LIMITED,
                f"已达到本地控频上限（{self.max_actions_per_min} 次/分钟）。",
                hint="这是为保护账号安全的主动限流，请降低调用频率或稍后再试。",
            )
        gap = now - self._last_ts
        need = self.min_interval + random.uniform(0, self.jitter)
        if 0 < gap < need:
            time.sleep(need - gap)
        self._last_ts = time.time()
        self._count_in_window += 1


class CaptchaGuard:
    """验证码 / 风控守卫：命中即暂停并交人工，绝不自动破解。

    DEFAULT_SIGNALS 为常见特征 locator，需在真实页面联调时按平台补全 / 校准。
    """

    DEFAULT_SIGNALS: Sequence[str] = (
        "text:拖动滑块",
        "text:点击完成验证",
        "text:请完成安全验证",
        "css:.captcha",
        "css:.vc-container",
        "css:.secsdk-captcha-drag-icon",
    )

    def __init__(self, signals: Optional[Sequence[str]] = None) -> None:
        self.signals: Sequence[str] = tuple(signals) if signals else self.DEFAULT_SIGNALS

    def check(self, driver: BrowserDriver) -> None:
        for sig in self.signals:
            hit = False
            try:
                hit = driver.exists(sig, timeout=0.3)
            except BusinessApiError:
                raise
            except Exception:
                hit = False
            if hit:
                artifacts: dict = {}
                try:
                    artifacts = driver.capture(label="captcha_detected")
                except Exception:
                    artifacts = {}
                raise BusinessApiError(
                    ErrorCode.CAPTCHA_REQUIRED,
                    "检测到验证码 / 风控验证页面，已暂停自动化。",
                    hint="请在浏览器中手动完成验证后，重新发起本次请求；本工具不会自动破解验证码。",
                    context={"signal": sig, "artifacts": artifacts},
                )


class BrowserContext:
    """业务域编排统一入口：封装控频、验证码检测、登录态检查后的安全操作。"""

    def __init__(
        self,
        driver: BrowserDriver,
        pacer: Optional[HumanPacer] = None,
        captcha: Optional[CaptchaGuard] = None,
        login_check_locator: Optional[str] = None,
        login_url_markers: Optional[Sequence[str]] = None,
    ) -> None:
        self.driver = driver
        self.pacer = pacer or HumanPacer()
        self.captcha = captcha or CaptchaGuard()
        self.login_check_locator = login_check_locator
        self.login_url_markers = (
            tuple(login_url_markers) if login_url_markers else DEFAULT_LOGIN_URL_MARKERS
        )

    # --- 导航 / 读取（读操作也控频，但更轻量） ---
    def goto(self, url: str) -> None:
        self.pacer.wait_turn()
        self.driver.navigate(url)
        self.captcha.check(self.driver)

    def read_text(self, locator: str, timeout: float = 2.0) -> str:
        return self.driver.read_text(locator, timeout=timeout)

    def read_texts(self, locator: str, timeout: float = 2.0) -> List[str]:
        return self.driver.read_texts(locator, timeout=timeout)

    def read_rows(self, row_locator: str, cell_locator: str = "tag:td", limit: int = 100) -> List[list]:
        return self.driver.read_rows(row_locator, cell_locator, limit)

    def exists(self, locator: str, timeout: float = 1.0) -> bool:
        return self.driver.exists(locator, timeout=timeout)

    def count(self, locator: str, timeout: float = 1.0) -> int:
        return self.driver.count(locator, timeout=timeout)

    def wait_visible(self, locator: str, timeout: float = 10.0) -> bool:
        return self.driver.wait_visible(locator, timeout=timeout)

    def wait_gone(self, locator: str, timeout: float = 10.0) -> bool:
        return self.driver.wait_gone(locator, timeout=timeout)

    def wait_count_stable(
        self, locator: str, min_count: int = 1, rounds: int = 8, interval: float = 0.3
    ) -> int:
        """等待匹配元素数量稳定后返回其数量（应对 SPA 渐进渲染导致的"读到半截页面"）。

        连续两次读到相同且 >= min_count 的数量即视为稳定；最多轮询 rounds 次。
        若始终为 0，则返回 0，由调用方据此报 ELEMENT_NOT_FOUND。
        """
        prev = -1
        n = 0
        for _ in range(max(1, rounds)):
            n = self.count(locator)
            if n >= min_count and n == prev:
                return n
            prev = n
            time.sleep(max(0.0, interval))
        return n

    # --- 写动作（先控频 + 验证码检测） ---
    def click(self, locator: str, timeout: float = 3.0, index: int = 0) -> None:
        self.pacer.wait_turn()
        self.captcha.check(self.driver)
        self.driver.click(locator, timeout=timeout, index=index)

    def input(self, locator: str, value: str, clear: bool = True, timeout: float = 3.0) -> None:
        self.pacer.wait_turn()
        self.driver.input(locator, value, clear=clear, timeout=timeout)

    # --- 登录态 ---
    def require_login(self) -> None:
        url = (self.driver.current_url() or "").lower()
        if any(marker in url for marker in self.login_url_markers):
            raise BusinessApiError(
                ErrorCode.LOGIN_REQUIRED,
                "页面已跳转到登录页，未登录或登录态失效。",
                hint="请在浏览器中登录抖店 / 对应平台后再调用本接口。",
                context={"url": url},
            )

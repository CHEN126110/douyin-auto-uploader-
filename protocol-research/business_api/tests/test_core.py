# -*- coding: utf-8 -*-
import pytest

from business_api.core import (
    BusinessApiError,
    CaptchaGuard,
    DrissionDriver,
    ErrorCode,
    HumanPacer,
    err_envelope,
    ok_envelope,
)
from business_api.tests.fakes import FakeDriver


def test_ok_envelope():
    e = ok_envelope("hi", {"a": 1})
    assert e["ok"] is True
    assert e["code"] == ErrorCode.OK
    assert e["data"] == {"a": 1}


def test_err_envelope():
    e = err_envelope("bad", ErrorCode.INVALID_PARAM, hint="fix")
    assert e["ok"] is False
    assert e["code"] == ErrorCode.INVALID_PARAM
    assert e["hint"] == "fix"


def test_human_pacer_rate_limit():
    p = HumanPacer(min_interval=0, jitter=0, max_actions_per_min=2)
    p.wait_turn()
    p.wait_turn()
    with pytest.raises(BusinessApiError) as ei:
        p.wait_turn()
    assert ei.value.code == ErrorCode.RATE_LIMITED


def test_captcha_guard_hit():
    guard = CaptchaGuard()
    driver = FakeDriver(captcha=True)
    with pytest.raises(BusinessApiError) as ei:
        guard.check(driver)
    assert ei.value.code == ErrorCode.CAPTCHA_REQUIRED


def test_captcha_guard_pass():
    guard = CaptchaGuard()
    driver = FakeDriver(captcha=False)
    guard.check(driver)  # 不应抛异常


def test_driver_requires_page():
    with pytest.raises(BusinessApiError) as ei:
        DrissionDriver(None)
    assert ei.value.code == ErrorCode.BROWSER_NOT_READY

# -*- coding: utf-8 -*-
"""账户门禁（src/sidecar/shop_accounts.ShopAccountGuard）回归：假的账户注册表 + 假的「发布任务是否在跑」。

守住的是「不会把商品发到别的平台 / 别的账户」这条红线：
1. 读不出当前账户（注册表损坏、当前账户不存在、平台非法）→ 503，绝不悄悄回落到抖店；
2. 当前账户的平台对不上入口 → 409 ACCOUNT_PLATFORM_MISMATCH；
3. 前端带来的账户快照与当前账户不一致 → 409 ACCOUNT_CHANGED，快照不是非空文本 → 400；
4. 有发布任务在跑时拒绝切换账户（409）；
5. 装饰器与账户切换共用同一把可重入锁，且异常时也会释放。
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from flask import Flask

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from src import shop_session  # noqa: E402
from src.sidecar.shop_accounts import ShopAccountGuard  # noqa: E402

DEFAULT = shop_session.DEFAULT_PROFILE_NAME


class FakeRegistry:
    """只换掉「读注册表」，平台规范化 / 目录名规范化沿用真实实现。"""

    DEFAULT_PROFILE_NAME = DEFAULT
    slugify_profile_name = staticmethod(shop_session.slugify_profile_name)
    normalize_platform = staticmethod(shop_session.normalize_platform)

    def __init__(self, active=DEFAULT, profiles=None):
        self.registry = {"active_profile": active, "profiles": {} if profiles is None else profiles}
        self.error = None
        self.reads = 0

    def load_registry(self):
        self.reads += 1
        if self.error is not None:
            raise self.error
        return self.registry

    def get_active_profile(self):
        if self.error is not None:
            raise self.error
        return self.registry["active_profile"]


@pytest.fixture()
def registry():
    return FakeRegistry(
        active="taobao-aaaaaaaa",
        profiles={
            DEFAULT: {"platform": "douyin"},
            "taobao-aaaaaaaa": {"platform": "taobao", "label": "测试淘宝"},
            "xhs-bbbbbbbb": {"platform": "xiaohongshu"},
        },
    )


@pytest.fixture()
def running():
    return SimpleNamespace(value=False, calls=0)


@pytest.fixture()
def guard(registry, running):
    def has_running():
        running.calls += 1
        return running.value

    return ShopAccountGuard(shop_session=registry, has_running_publish_tasks=has_running)


@pytest.fixture()
def request_context():
    app = Flask("shop-accounts-test")
    with app.test_request_context("/"):
        yield


def unpack(result):
    """(Flask 响应, 状态码) -> (JSON, 状态码)；通过时 None。"""
    if result is None:
        return None
    response, status = result
    return response.get_json(), status


# ------------------------------------------------------------------ 当前账户

def test_active_account_reports_bound_platform_and_label(guard):
    assert guard.active_account() == {"profile_name": "taobao-aaaaaaaa", "platform": "taobao", "label": "测试淘宝"}
    assert guard.active_profile() == "taobao-aaaaaaaa"


@pytest.mark.parametrize("platform", ("douyin", "taobao", "xiaohongshu"))
def test_each_bound_platform_is_reported(registry, guard, platform):
    registry.registry["profiles"]["taobao-aaaaaaaa"]["platform"] = platform
    assert guard.active_account()["platform"] == platform


def test_legacy_entry_without_platform_is_douyin(registry, guard):
    registry.registry["active_profile"] = DEFAULT
    registry.registry["profiles"][DEFAULT] = {}
    assert guard.active_account() == {"profile_name": DEFAULT, "platform": "douyin", "label": None}


def test_truly_empty_legacy_registry_keeps_douyin_bootstrap(registry, guard):
    registry.registry["profiles"].clear()
    registry.registry["active_profile"] = DEFAULT
    assert guard.active_account()["platform"] == "douyin"


def test_missing_active_account_fails_instead_of_picking_default(registry, guard):
    registry.registry["active_profile"] = "ghost-00000000"
    with pytest.raises(ValueError, match="当前账户不存在"):
        guard.active_account()


def test_missing_default_with_other_accounts_fails_closed(registry, guard):
    registry.registry["active_profile"] = DEFAULT
    del registry.registry["profiles"][DEFAULT]
    with pytest.raises(ValueError, match="当前账户不存在"):
        guard.active_account()


@pytest.mark.parametrize("bad", (None, "other", 5, ""))
def test_explicit_invalid_platform_is_never_a_legacy_default(registry, guard, bad):
    registry.registry["profiles"]["taobao-aaaaaaaa"]["platform"] = bad
    with pytest.raises(ValueError):
        guard.active_account()


def test_registry_errors_reach_the_caller(registry, guard):
    registry.error = OSError("磁盘离线")
    with pytest.raises(OSError, match="磁盘离线"):
        guard.active_account()
    with pytest.raises(OSError, match="磁盘离线"):
        guard.active_profile()


# ------------------------------------------------------------------ 平台门禁

def test_matching_platform_passes(guard, request_context):
    assert guard.require_publish_platform("taobao") is None
    assert guard.require_publish_platform("taobao", "taobao-aaaaaaaa") is None


@pytest.mark.parametrize("expected,label", (
    ("douyin", "抖音"), ("xiaohongshu", "小红书千帆"), ("unknown-platform", "unknown-platform"),
))
def test_wrong_platform_is_a_409_naming_the_expected_platform(guard, request_context, expected, label):
    body, status = unpack(guard.require_publish_platform(expected))
    assert status == 409
    assert body["success"] is False
    assert body["code"] == "ACCOUNT_PLATFORM_MISMATCH"
    assert body["msg"] == f"当前账户不属于{label}，请先切换到{label}账户"


@pytest.mark.parametrize("snapshot", ("", "   ", 5, True, [], {}))
def test_account_snapshot_must_be_nonempty_text(guard, request_context, snapshot):
    body, status = unpack(guard.require_publish_platform("taobao", snapshot))
    assert status == 400
    assert body == {"success": False, "msg": "账户标识必须是非空文本"}


def test_stale_account_snapshot_is_rejected_as_changed(guard, request_context):
    body, status = unpack(guard.require_publish_platform("taobao", "another-00000000"))
    assert status == 409
    assert body["code"] == "ACCOUNT_CHANGED"
    assert "当前账户已改变" in body["msg"]


def test_platform_is_checked_before_the_snapshot(guard, request_context):
    # 平台不对时，不能因为快照合法就放行，也不该先报快照的错
    body, status = unpack(guard.require_publish_platform("douyin", ""))
    assert status == 409 and body["code"] == "ACCOUNT_PLATFORM_MISMATCH"


@pytest.mark.parametrize("error", (OSError("读不了"), ValueError("注册表损坏")))
def test_unreadable_registry_is_a_503_not_a_douyin_fallback(registry, guard, request_context, error):
    registry.error = error
    body, status = unpack(guard.require_publish_platform("douyin"))
    assert status == 503
    assert body["success"] is False
    assert body["msg"] == f"读取账户资料失败：{error}"


def test_missing_active_account_is_a_503(registry, guard, request_context):
    registry.registry["active_profile"] = "ghost-00000000"
    body, status = unpack(guard.require_publish_platform("douyin"))
    assert status == 503
    assert "当前账户不存在" in body["msg"]


# ------------------------------------------------------------------ 账户切换互斥

def test_account_change_is_allowed_when_no_publish_task_runs(guard, running, request_context):
    assert guard.account_change_blocked() is None
    assert running.calls == 1


def test_account_change_is_blocked_while_a_publish_task_runs(guard, running, request_context):
    running.value = True
    body, status = unpack(guard.account_change_blocked())
    assert status == 409
    assert body == {"success": False, "msg": "发布任务运行中，请完成或取消后再切换账户"}


def test_account_change_asks_every_time_instead_of_caching(guard, running, request_context):
    assert guard.account_change_blocked() is None
    running.value = True
    assert guard.account_change_blocked() is not None
    running.value = False
    assert guard.account_change_blocked() is None
    assert running.calls == 3


# ------------------------------------------------------------------ 账户锁

def test_with_lock_keeps_the_function_identity_and_result(guard):
    def handler(a, b=2):
        """文档。"""
        return a + b

    wrapped = guard.with_lock(handler)
    assert wrapped(1, b=5) == 6
    assert wrapped.__name__ == "handler" and wrapped.__doc__ == "文档。"


def test_with_lock_holds_the_shared_lock_while_the_handler_runs(guard):
    entered, release = threading.Event(), threading.Event()
    acquired_from_outside = []

    def handler():
        entered.set()
        assert release.wait(5)
        return "done"

    worker = threading.Thread(target=guard.with_lock(handler))
    worker.start()
    try:
        assert entered.wait(5)

        def try_acquire():
            got = guard.lock.acquire(blocking=False)
            acquired_from_outside.append(got)
            if got:
                guard.lock.release()

        probe = threading.Thread(target=try_acquire)
        probe.start()
        probe.join(5)
        assert acquired_from_outside == [False]      # 别的线程此时拿不到锁
    finally:
        release.set()
        worker.join(5)
    assert guard.lock.acquire(blocking=False)       # 结束后锁已释放
    guard.lock.release()


def test_with_lock_is_reentrant_and_releases_after_an_exception(guard):
    @guard.with_lock
    def inner():
        return guard.lock.acquire(blocking=False)

    @guard.with_lock
    def outer():
        got = inner()
        if got:
            guard.lock.release()
        return got

    assert outer() is True            # 同一线程重入（保存入口会在持锁时再进门禁）

    @guard.with_lock
    def boom():
        raise RuntimeError("业务异常")

    with pytest.raises(RuntimeError):
        boom()
    other = []

    def probe_acquire():
        got = guard.lock.acquire(blocking=False)
        other.append(got)
        if got:
            guard.lock.release()

    probe = threading.Thread(target=probe_acquire)
    probe.start()
    probe.join(5)
    assert other == [True]            # 异常没有把锁留在手里


def test_each_guard_owns_its_own_lock(registry):
    first = ShopAccountGuard(shop_session=registry, has_running_publish_tasks=lambda: False)
    second = ShopAccountGuard(shop_session=registry, has_running_publish_tasks=lambda: False)
    assert first.lock is not second.lock
    assert first.lock is first.lock


# ------------------------------------------------------------------ 依赖边界

def test_importing_the_guard_does_not_load_the_browser_stack(tmp_path):
    code = (
        "import sys; sys.path.insert(0, %r); import src.sidecar.shop_accounts; "
        "bad = [m for m in ('DrissionPage', 'src.utils', 'PySide6', 'app') if m in sys.modules]; "
        "print('LOADED=' + ','.join(bad))" % str(REPO)
    )
    env = dict(os.environ, DOUYIN_DATA_DIR=str(tmp_path / "data"), PYTHONUTF8="1")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         encoding="utf-8", env=env, check=True)
    assert out.stdout.strip().splitlines()[-1] == "LOADED="

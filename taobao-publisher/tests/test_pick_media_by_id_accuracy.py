# -*- coding: utf-8 -*-
"""按 ``pictureId`` 选图的**准确度**：隔离浏览器 + 合成选图器（真实 DOM）。

## 为什么必须有这个文件

协议上传之所以被选为主路线，核心理由就是**确定性选图**：回执里带着 ``pictureId``，
按 ID 命中唯一一张卡片，不比名字、不遍历、不受同名与虚拟滚动影响。

但这套逻辑以前**只在真机上被验证过**，而且它的注释与实现**不一致**：

.. code-block:: js

    // 注释说"先读 checked，只有未选中才点"
    if (input) { input.click(); }   // ← 实现却是无条件点

而勾选框是**切换**语义——已选中的再点会**取消**。真机上的后果是：
续跑、或用户自己先选过一张时，这一下把**已经选好的图悄悄取消**，
槽位留空却报"已选中"。这正是"选图准确度"最怕的错。

本文件用真实 DOM 把下面五条钉死（**不发任何平台写请求、不碰淘宝**）：

1. 按 ID 命中**唯一**那张，且**只点它**；
2. 已选中的卡片**不许再点**（不许反选）；
3. 同一 ID 命中多张 → **拒绝猜**，且**一张都不许点**；
4. 目标 ID 不在页面上 → 如实报 ``MediaImageMissing``；
5. ``select=False``（只查不点）→ **一次点击都不发生**。

关键设计：合成页把**每次点击**记进 ``window.__clicks``。只看最终 ``checked``
是抓不到第 2 条的——被反选的卡片，最终状态和"从未点过"一模一样。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path

import pytest

from taobao_publish import page
from taobao_publish.page import MediaImageMissing, PageClient

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "synthetic-picker.html"
PROFILE = Path(__file__).resolve().parents[1] / "tmp" / "synthetic-picker-profile"

TARGET = "1111111111111111111"
ALREADY = "2222222222222222222"
DISABLED = "3333333333333333333"
DUPLICATED = "4444444444444444444"
HIDDEN = "5555555555555555555"


def _headless_shell():
    root = Path(os.environ.get("LOCALAPPDATA", "")) / "ms-playwright"
    found = sorted(root.glob(
        "chromium_headless_shell-*/chrome-headless-shell-win64/chrome-headless-shell.exe"))
    return found[-1] if found else None


@pytest.fixture(scope="module")
def picker():
    """隔离浏览器里的合成选图器；产出连接参数（每个用例自开客户端）。"""

    exe = _headless_shell()
    if exe is None:
        pytest.skip("缺少本地独立 headless Chromium")
    shutil.rmtree(PROFILE, ignore_errors=True)
    PROFILE.mkdir(parents=True, exist_ok=True)
    process = subprocess.Popen(
        [str(exe), "--headless", "--remote-debugging-port=0",
         "--user-data-dir=" + str(PROFILE),
         "--disable-background-networking", "--no-proxy-server",
         "--host-resolver-rules=MAP * ~NOTFOUND",
         "--disable-component-update", "--no-first-run", FIXTURE.as_uri()],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    try:
        active = PROFILE / "DevToolsActivePort"
        deadline = time.monotonic() + 20
        while not active.is_file():
            if time.monotonic() > deadline or process.poll() is not None:
                pytest.fail("隔离测试浏览器启动失败")
            time.sleep(0.1)
        with urllib.request.urlopen("http://127.0.0.1:%s/json/list" % active.read_text(
                encoding="utf-8").splitlines()[0], timeout=5) as response:
            matches = [t for t in json.load(response) if t.get("url") == FIXTURE.as_uri()]
        assert len(matches) == 1, "只能连接此次新建浏览器中的本地合成页"
        yield {"ws_url": matches[0]["webSocketDebuggerUrl"], "url": FIXTURE.as_uri()}
    finally:
        process.terminate()


class _Picker:
    """一个用例一个客户端：既读页面状态，也**重置点击记录**。"""

    def __init__(self, fixture):
        self.client = PageClient.connect(fixture["ws_url"], target_url=fixture["url"])
        # CDP 能连上 ≠ 页面已经加载完：合成页的卡片是脚本渲染的，文档没到 complete
        # 时 DOM 里一张卡都没有，紧接着 `pick(wait=0.0)` 会报 missing——
        # 全量回归时机器被别的隔离浏览器占着，这一步就会输掉竞态（2026-10-10 实测）。
        # 与同目录 `test_synthetic_folder_creation.py` 的等待约定保持一致。
        deadline = time.monotonic() + 10
        while not self.client.evaluate("document.readyState === 'complete'", timeout=2):
            if time.monotonic() >= deadline:
                pytest.fail("合成选图器没有完成加载")
            time.sleep(0.05)
        self._reset()

    def _reset(self):
        # 每个用例从干净状态开始：清空点击记录，并把勾选恢复成页面的初始布局。
        self.client.evaluate(
            "window.__clicks = [];"
            "document.querySelectorAll('input[type=checkbox]').forEach(function (b) {"
            "  b.checked = (b.value === %s); }); true" % json.dumps(ALREADY))

    def clicks(self):
        return self.client.evaluate("window.__clicks") or []

    def checked(self):
        return self.client.evaluate(
            "Array.from(document.querySelectorAll('input[type=checkbox]'))"
            ".filter(b => b.checked).map(b => b.value)") or []

    def pick(self, ids, *, select=True, wait=0.0):
        return page.pick_media_by_id(self.client, ids, context_id=None,
                                     select=select, wait=wait)

    def close(self):
        self.client.close()


@pytest.fixture()
def p(picker):
    session = _Picker(picker)
    try:
        yield session
    finally:
        session.close()


def test_picks_exactly_the_requested_picture_id_and_nothing_else(p):
    result = p.pick([TARGET])

    assert result["ok"] is True and result["matched"] == 1
    entry = result["selected"][0]
    assert entry["pictureId"] == TARGET
    assert entry["checked"] is True, "点完必须处于选中态"
    assert "target" in entry["url"], "回执要带这张卡片的图片地址，供上层核对身份"
    assert entry["fragment"].startswith("O1CN"), "资源号要能被解析出来"
    assert p.clicks() == [TARGET], "只允许点目标那张"
    assert sorted(p.checked()) == sorted([TARGET, ALREADY]), "别的卡片不许被改动"


def test_already_checked_card_is_never_toggled_off(p):
    """**这条就是本轮修掉的 bug**：已选中的再点会取消，槽位会留空。"""

    result = p.pick([ALREADY])

    assert result["ok"] is True
    entry = result["selected"][0]
    assert entry["alreadyChecked"] is True, "要如实告诉调用方它本来就已经选中"
    assert entry["method"] == "none", "已选中的不该再点"
    assert p.clicks() == [], "一次点击都不该发生——再点一下就把这张图取消了"
    assert ALREADY in p.checked(), "已选中的必须仍然选中"


def test_ambiguous_picture_id_is_refused_without_clicking_anything(p):
    with pytest.raises(Exception) as caught:
        p.pick([DUPLICATED])

    assert "ambiguous" in str(caught.value) or "猜" in str(caught.value)
    assert p.clicks() == [], "有歧义时**一张都不许点**（点错比不点更糟）"
    assert sorted(p.checked()) == sorted([ALREADY]), "页面勾选状态不许被改动"


def test_missing_picture_id_is_reported_not_silently_skipped(p):
    with pytest.raises(MediaImageMissing) as caught:
        p.pick(["9999999999999999999"])

    assert "9999999999999999999" in str(caught.value)
    assert p.clicks() == []


def test_disabled_card_is_refused(p):
    with pytest.raises(Exception) as caught:
        p.pick([DISABLED])

    assert "selection_control_unavailable" in str(caught.value) or "unavailable" in str(caught.value)
    assert p.clicks() == []


def test_lookup_only_never_clicks(p):
    result = p.pick([TARGET], select=False)

    assert result["ok"] is True and result["matched"] == 1
    assert result["selected"][0]["method"] == "none"
    assert p.clicks() == [], "只查不点时不允许有任何点击"
    assert sorted(p.checked()) == sorted([ALREADY])

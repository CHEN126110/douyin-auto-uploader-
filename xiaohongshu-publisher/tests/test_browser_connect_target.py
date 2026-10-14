# -*- coding: utf-8 -*-
"""`connect()` 选页回归：**创建页在后台时必须去激活/新开它，绝不能改用可见的首页**。

为什么单独测它（2026-10-14 真机实测踩到 ✗）：
浏览器里同时开着 `app-item/good/create`（**hidden**，`required_count=1`、
`upload_trigger=1`）与 `app-system/home`（**visible**、`required_count=0`）。
`connect()` 返回的是**首页** ✗ —— 于是整条填表跑在首页上，上传第一步找不到入口，
界面只报「图片上传未成功」，真实原因被完全掩盖（AGENTS.md 纪律 5 记录的故障又回来了）。

根因（Phase 1 定位）：`32fff2e` 引入了"创建页标签优先"，但选择循环写成
"**第一个 `visible` 的标签就赢**" —— 创建页藏在后台时先被跳过，
紧跟其后的可见首页立刻占住 `chosen`；于是"激活创建页 / 不可见就新开前台标签"
那段兜底（前置条件 `chosen is None`）**永远不执行**。
`8e879ad` 那次验收显示通过，是因为当时创建页**恰好在前台**（环境依赖型绿灯）。

本测试用假 CDP 客户端，**不连浏览器、不做任何平台写入** ✓。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
if str(REPO / "xiaohongshu-publisher") not in sys.path:
    sys.path.insert(0, str(REPO / "xiaohongshu-publisher"))

from xiaohongshu_publish import browser as xhs_browser  # noqa: E402

CREATE_URL = "https://ark.xiaohongshu.com/app-item/good/create"
HOME_URL = "https://ark.xiaohongshu.com/app-system/home"
CREATE_ID = "ID-CREATE"
HOME_ID = "ID-HOME"
NEW_ID = "ID-NEW-CREATE"


class FakeTarget:
    def __init__(self, target_id: str, url: str) -> None:
        self.target_id = target_id
        self.url = url
        self.kind = "page"
        self.web_socket_url = "ws://127.0.0.1:9500/devtools/page/%s" % target_id


class FakeBrowser:
    """假 `CdpBrowser`：记录状态变更，并模拟浏览器侧的"最终一致"。

    - `Target.activateTarget` **只在窗口前台时有效** → 由 `activation_works` 决定；
    - `Target.createTarget` 新开的标签页**实测是 visible 的**（见 AGENTS.md 兜底说明）
      → 由 `new_tab_visible` 决定；
    - 两者都不是瞬时生效 → 被连接的代码本来就要轮询判定，这里立刻生效即可。
    """

    def __init__(self, port: int = 9500, timeout: float = 25.0) -> None:
        self.port = port
        self.timeout = timeout

    def list_targets(self):
        return list(ENV.targets)

    def call(self, method: str, params: dict, session_id=None):
        if method == "Target.activateTarget":
            target_id = params.get("targetId")
            ENV.activated.append(target_id)
            if ENV.activation_works:
                ENV.visible_ids.add(target_id)
        elif method == "Target.createTarget":
            url = params.get("url")
            ENV.created.append(url)
            ENV.targets.append(FakeTarget(NEW_ID, url))
            if ENV.new_tab_visible:
                ENV.visible_ids.add(NEW_ID)
            return {"targetId": NEW_ID}
        return {}

    def attach(self, target_id: str):
        return "session-%s" % target_id

    def close(self) -> None:
        pass


class FakePageClient:
    """只实现 `connect()` 用到的三件事：可见性、`location.href`、`close()`。

    真机上 `location.href` 可能因为**导航销毁执行上下文**而暂时读成空 ✗，
    这里如真机加载完的状态回答（URL 就是那条 target 的 URL）。
    """

    @staticmethod
    def connect(web_socket_url: str, target_url: str = ""):
        class Probe:
            def evaluate(self, script: str):
                if "visibilityState" in script:
                    return "visible" if target_id in ENV.visible_ids else "hidden"
                if "location.href" in script:
                    return target_url
                return None

            def close(self) -> None:
                pass

        target_id = web_socket_url.rsplit("/", 1)[-1]
        return Probe()


class Env:
    """一次用例的浏览器环境（谁可见、激活是否有效、新开标签是否可见）。"""

    def __init__(self, targets: list, visible_ids: set, activation_works: bool = True,
                 new_tab_visible: bool = True) -> None:
        self.targets = list(targets)
        self.visible_ids = set(visible_ids)
        self.activation_works = activation_works
        self.new_tab_visible = new_tab_visible
        self.activated: list = []
        self.created: list = []


ENV: Env = None  # type: ignore[assignment]


def _setup(targets: list, visible_ids: set, **kwargs) -> Env:
    global ENV
    ENV = Env(targets, visible_ids, **kwargs)
    return ENV


def _both_tabs() -> list:
    return [FakeTarget(CREATE_ID, CREATE_URL), FakeTarget(HOME_ID, HOME_URL)]


@pytest.fixture(autouse=True)
def _patch(monkeypatch):
    """换掉 CDP 客户端与 `time.sleep`（真机上的等待在单测里没必要）。"""
    monkeypatch.setattr(xhs_browser, "CdpBrowser", FakeBrowser)
    monkeypatch.setattr(xhs_browser, "PageClient", FakePageClient)
    monkeypatch.setattr(xhs_browser.time, "sleep", lambda _seconds: None)


def test_connect_activates_background_create_tab_not_visible_home():
    """核心回归：创建页在后台 → 激活**创建页**并用它，绝不退化成可见的首页。"""
    env = _setup(_both_tabs(), visible_ids={HOME_ID})

    _browser, page, _client, _session = xhs_browser.connect(9500)

    assert env.activated == [CREATE_ID], (
        "创建页在后台时没有去激活它（实际激活=%r）" % (env.activated,))
    assert page.target_id == CREATE_ID, "选中的不是创建页：%r" % (page.target_id,)


def test_connect_prefers_already_visible_create_tab():
    """创建页本来就可见时不该多此一举去激活（无谓的浏览器状态变更要避免）。"""
    env = _setup(_both_tabs(), visible_ids={CREATE_ID, HOME_ID})

    _browser, page, _client, _session = xhs_browser.connect(9500)

    assert page.target_id == CREATE_ID
    assert env.activated == []


def test_connect_never_returns_visible_home_when_create_tab_stays_hidden():
    """激活无效（窗口在后台）→ 新开创建页；**任何情况下都不许把首页交出去**。"""
    env = _setup(_both_tabs(), visible_ids={HOME_ID}, activation_works=False,
                 new_tab_visible=True)

    _browser, page, _client, _session = xhs_browser.connect(9500)

    assert env.created == [CREATE_URL], "没有新开创建页标签（实际=%r）" % (env.created,)
    assert page.target_id == NEW_ID, "选中的不是新开的创建页：%r" % (page.target_id,)


def test_connect_raises_when_no_visible_create_page_can_be_established():
    """创建页始终不可见且新开也拿不到 → **明确报错**，不降级、不静默。"""
    _setup(_both_tabs(), visible_ids={HOME_ID}, activation_works=False,
           new_tab_visible=False)

    with pytest.raises(RuntimeError) as error:
        xhs_browser.connect(9500)

    assert "good/create" in str(error.value) or "创建页" in str(error.value)


def test_connect_opens_create_tab_when_none_exists():
    """一个创建页标签都没有（只剩可见首页）→ 新开创建页，而不是用首页凑合。"""
    env = _setup([FakeTarget(HOME_ID, HOME_URL)], visible_ids={HOME_ID})

    _browser, page, _client, _session = xhs_browser.connect(9500)

    assert env.created == [CREATE_URL], "没有新开创建页标签（实际=%r）" % (env.created,)
    assert page.target_id == NEW_ID, "选中的不是新开的创建页：%r" % (page.target_id,)

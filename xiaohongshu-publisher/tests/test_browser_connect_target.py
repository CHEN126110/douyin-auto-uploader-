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
        elif method in ("Emulation.setFocusEmulationEnabled",
                        "Page.setWebLifecycleState",
                        "Page.bringToFront"):
            # 真机实测有效的一组聚焦手段（2026-10-14）：作用于**目标标签自己**（走 session）✓
            ENV.focus_levers.append(method)
            if ENV.focus_levers_work and session_id:
                ENV.visible_ids.add(str(session_id).replace("session-", "", 1))
        return {}

    def attach(self, target_id: str):
        return "session-%s" % target_id

    def close(self) -> None:
        pass


class FakePageClient:
    """只实现 `connect()` 用到的几件事：可见性、`location.href`、表单状态、`close()`。

    真机上 `location.href` 可能因为**导航销毁执行上下文**而暂时读成空 ✗，
    这里如真机加载完的状态回答（URL 就是那条 target 的 URL）。
    表单状态由 `ENV.form_states[target_id]` 提供（缺省＝空表单）。
    """

    @staticmethod
    def connect(web_socket_url: str, target_url: str = ""):
        target_id = web_socket_url.rsplit("/", 1)[-1]

        class Probe:
            def evaluate(self, script: str):
                # ⚠️ 顺序与**精确度**都重要：`FORM_STATE_PROBE` 里也有 `visibilityState`
                # 字样（它读图片可见性）→ 若用宽匹配会被可见性分支先命中 ✗（本轮踩过）。
                if "title_len" in script:            # FORM_STATE_PROBE 的唯一标记
                    return dict(ENV.form_states.get(target_id, {}))
                if "document.visibilityState" in script:
                    return "visible" if target_id in ENV.visible_ids else "hidden"
                if "location.href" in script:
                    return target_url
                return None

            def close(self) -> None:
                pass

        return Probe()


class Env:
    """一次用例的浏览器环境（谁可见、激活是否有效、新开标签是否可见、聚焦手段是否有效）。"""

    def __init__(self, targets: list, visible_ids: set, activation_works: bool = True,
                 new_tab_visible: bool = True, focus_levers_work: bool = True,
                 form_states: dict | None = None) -> None:
        self.targets = list(targets)
        self.visible_ids = set(visible_ids)
        self.activation_works = activation_works
        self.new_tab_visible = new_tab_visible
        self.focus_levers_work = focus_levers_work
        self.form_states = dict(form_states or {})
        self.activated: list = []
        self.created: list = []
        self.focus_levers: list = []


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
    """核心回归：创建页在后台 → 选中**创建页**并用它，绝不退化成可见的首页。

    本用例只走"激活标签"这条路（关掉聚焦手段），这样它验证的是
    `Target.activateTarget` 分支本身 ✓。
    """
    env = _setup(_both_tabs(), visible_ids={HOME_ID}, focus_levers_work=False)

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
    """**空**创建页标签救不活 → 新开一个可操作的前台标签；绝不许把首页交出去。

    空表单没有内容可丢，新开是划算的 ✓（与下一条"已有内容"的情形相对）。
    """
    env = _setup(_both_tabs(), visible_ids={HOME_ID}, activation_works=False,
                 focus_levers_work=False, new_tab_visible=True)

    _browser, page, _client, _session = xhs_browser.connect(9500)

    assert env.created == [CREATE_URL], "没有新开创建页标签（实际=%r）" % (env.created,)
    assert page.target_id == NEW_ID, "选中的不是新开的创建页：%r" % (page.target_id,)


def test_connect_refuses_to_open_a_new_tab_when_the_filled_form_cannot_be_shown():
    """**已有内容**的创建页救不活 → **拒绝新开**并明确报错（新开会丢掉已传的图与已填字段 ✗）。

    真机对照：带表单的标签（22 图 + 已推进）在后台救不活时，宁可报错让用户把窗口切到前台，
    也不能悄悄换一个空标签重来 —— 那正是"表单看起来丢了"的成因 ✗。
    """
    _setup([FakeTarget(CREATE_ID, CREATE_URL)], visible_ids=set(),
           activation_works=False, focus_levers_work=False, new_tab_visible=True,
           form_states={CREATE_ID: {"at_4groups": True, "required_marks": 13,
                                    "uploaded_imgs": 21, "title_len": 22}})

    with pytest.raises(RuntimeError) as error:
        xhs_browser.connect(9500)

    assert "拒绝新开" in str(error.value), str(error.value)


def test_connect_raises_when_no_visible_create_page_can_be_established():
    """激活、聚焦手段、新开标签**全都拿不到可见创建页** → 明确报错，不降级。"""
    _setup(_both_tabs(), visible_ids={HOME_ID}, activation_works=False,
           focus_levers_work=False, new_tab_visible=False)

    with pytest.raises(RuntimeError) as error:
        xhs_browser.connect(9500)

    assert "good/create" in str(error.value) or "创建页" in str(error.value) or "不可见" in str(error.value)


def test_connect_opens_create_tab_when_none_exists():
    """一个创建页标签都没有（只剩可见首页）→ 新开创建页，而不是用首页凑合。"""
    env = _setup([FakeTarget(HOME_ID, HOME_URL)], visible_ids={HOME_ID})

    _browser, page, _client, _session = xhs_browser.connect(9500)

    assert env.created == [CREATE_URL], "没有新开创建页标签（实际=%r）" % (env.created,)
    assert page.target_id == NEW_ID, "选中的不是新开的创建页：%r" % (page.target_id,)


def test_connect_picks_the_tab_that_holds_the_filled_form_not_a_visible_blank_one():
    """真机实测（2026-10-14 晚）：浏览器里**同时有两个创建页标签**，
    表单（22 张图 + 已推进到四组页）只在其中一个里，而**两个都是 hidden** ✗。

    旧实现只按"可见"挑 → 反复挑到空标签 → 每次都要重传图片，
    用户看到的现象像"表单自己丢了" ✗。⇒ 必须**按表单完成度**挑。
    """
    blank, filled = "ID-CREATE-BLANK", "ID-CREATE-FILLED"
    env = _setup(
        [FakeTarget(blank, CREATE_URL), FakeTarget(filled, CREATE_URL)],
        visible_ids=set(),                      # 两个都不可见（真机实测情形）
        focus_levers_work=True,
        form_states={
            blank: {"at_4groups": False, "required_marks": 1, "uploaded_imgs": 0, "title_len": 0},
            filled: {"at_4groups": True, "required_marks": 13, "uploaded_imgs": 21, "title_len": 22},
        },
    )

    _browser, page, _client, _session = xhs_browser.connect(9500)

    assert page.target_id == filled, "挑到了空标签而不是带表单的那个：%r" % (page.target_id,)
    assert env.created == [], "已有带表单的标签，却去新开了：%r" % (env.created,)


def test_connect_uses_focus_levers_when_activation_alone_fails():
    """真机实测（2026-10-14 晚）：`Target.activateTarget` 单独用**无效** ✗
    （浏览器窗口不在前台时它只切"窗口内的当前标签"，创建页一直 hidden）
    → 必须再走聚焦手段把标签救成 visible ✓，否则整条流程根本起不来。
    """
    env = _setup(_both_tabs(), visible_ids={HOME_ID},
                 activation_works=False, focus_levers_work=True)

    _browser, page, _client, _session = xhs_browser.connect(9500)

    assert env.focus_levers, "激活无效后没有尝试任何聚焦手段"
    assert "Emulation.setFocusEmulationEnabled" in env.focus_levers, (
        "没用实测有效的那一手：%r" % (env.focus_levers,))
    assert page.target_id == CREATE_ID, "救活后没有选中创建页：%r" % (page.target_id,)
    assert env.created == [], "创建页标签明明可用，却去新开了：%r" % (env.created,)

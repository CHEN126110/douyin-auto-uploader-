# -*- coding: utf-8 -*-
"""小红书千帆：受约束的页面封装（把四条实现纪律内建，调用方不需要自己记得）。

设计原则：**不安全的动作要么拒绝执行，要么返回证据让调用方判断**，绝不"悄悄试一下"。
所有点击都先做命中反查（纪律 3）；填表只用原生 setter（纪律 2）；
抽屉未关时不点页面控件（纪律 4）；不可见标签页不点击（纪律 1）。

依赖：`taobao-publisher/taobao_publish` 的 `CdpBrowser` / `PageClient`（本仓已验证的 CDP 客户端）。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

from . import page_scripts

#: 点击后等待的默认秒数（真机上 0.3 秒左右就能看到反应，取 0.4 留余量）
CLICK_SETTLE_SECONDS = 0.4


@dataclass
class Step:
    """一步操作的证据记录（写进报告用）。"""

    name: str
    ok: bool
    detail: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {"name": self.name, "ok": self.ok, **self.detail}


class DisciplineError(RuntimeError):
    """违反四条纪律时抛出——**不要**捕获后继续点，那正是历史事故的成因。"""


class XhsPage:
    """小红书千帆创建页的受约束封装。

    `client` 需要提供 `evaluate(script)` 与 `send(method, params)`
    （即 `taobao_publish.page.PageClient`）；`browser`/`target_id` 可选，
    仅用于切换标签页激活。
    """

    def __init__(self, client: Any, browser: Any = None, target_id: str = "") -> None:
        self.client = client
        self.browser = browser
        self.target_id = target_id
        self.steps: list[Step] = []

    # --- 纪律 1：可见标签页 -------------------------------------------------

    def visibility(self) -> str:
        return self.client.evaluate("document.visibilityState")

    def ensure_visible(self) -> str:
        """尽力把页面弄成可见；返回最终可见性状态。

        窗口在前台时 `Target.activateTarget` 通常够用；不够时由调用方决定
        是否新开标签页（见 AGENTS.md 纪律 1）。**本方法不抛异常**，
        因为"不可见"是环境状态而非代码错误——但 `click()` 会据此拒绝执行。
        """
        if self.browser is not None and self.target_id:
            try:
                self.browser.call("Target.activateTarget", {"targetId": self.target_id})
                time.sleep(1.0)
            except Exception:  # noqa: BLE001 - 激活失败不影响后续判断
                pass
        return self.visibility()

    # --- 纪律 4：抽屉是覆盖式的 ---------------------------------------------

    def drawer_state(self) -> dict:
        return self.client.evaluate(page_scripts.DRAWER_STATE)

    def close_drawer(self) -> bool:
        """尝试关掉素材空间抽屉；返回是否已关闭。

        只点**抽屉自己的**「取消」——点遮罩与 Esc 真机实测都关不掉。
        """
        if not self.drawer_state().get("drawers"):
            return True
        found = self.client.evaluate(page_scripts.DRAWER_CANCEL)
        if found.get("found"):
            self._dispatch_click(found["x"], found["y"])
            time.sleep(1.5)
        return not self.drawer_state().get("drawers")

    def require_drawer_closed(self) -> None:
        """抽屉没关就抛错——不要带着覆盖层去点页面控件。"""
        state = self.drawer_state()
        if state.get("drawers"):
            raise DisciplineError(
                "素材空间抽屉仍开着（drawers={}），按纪律 4 不操作页面控件".format(
                    state.get("drawers")))

    # --- 纪律 3：点击前反查命中 ---------------------------------------------

    def hit_test(self, x: int, y: int) -> dict:
        return self.client.evaluate(page_scripts.hit_test_script(x, y))

    def click(self, x: int, y: int, expect_text: str = "") -> dict:
        """真实鼠标点击，但**先反查命中**。

        `expect_text` 非空时，若该点位最上层元素的文本不含它，则拒绝点击并返回证据
        （用于区分"被遮住 / 不在视口 / 组件不响应"）。
        """
        state = self.drawer_state()
        if state.get("drawers"):
            raise DisciplineError("抽屉开着，拒绝点击页面控件（纪律 4）")
        if state.get("visibility") != "visible":
            raise DisciplineError(
                "标签页不可见（visibility={}），拒绝点击（纪律 1）".format(state.get("visibility")))
        hit = self.hit_test(x, y)
        if expect_text and expect_text not in (hit.get("text") or ""):
            return {"clicked": False, "reason": "命中元素不是目标（可能被覆盖层遮住）",
                    "hit": hit, "expected": expect_text}
        self._dispatch_click(x, y)
        return {"clicked": True, "hit": hit}

    def _dispatch_click(self, x: int, y: int) -> None:
        for kind, buttons in (("mouseMoved", 0), ("mousePressed", 1), ("mouseReleased", 0)):
            self.client.send("Input.dispatchMouseEvent",
                             {"type": kind, "x": x, "y": y, "button": "left",
                              "buttons": buttons, "clickCount": 1})
            time.sleep(CLICK_SETTLE_SECONDS / 3)

    # --- 纪律 2：表单只能用原生 setter --------------------------------------

    def set_title(self, title: str) -> dict:
        """写入商品标题（原生 setter + input/change + 主动失焦）。"""
        result = self.client.evaluate(page_scripts.set_title_script(title))
        self.steps.append(Step("set_title", bool(result.get("ok")), result))
        return result

    def find_title(self) -> dict:
        return self.client.evaluate(page_scripts.FIND_TITLE)

    def state(self) -> dict:
        return self.client.evaluate(page_scripts.READ_STATE)

    def run(self, name: str, action: Callable[[], Any]) -> Any:
        """执行一步并记录证据；抛错时记录失败但**继续向上抛**（不吞错）。"""
        try:
            result = action()
        except Exception as error:  # noqa: BLE001 - 记录后原样抛出
            self.steps.append(Step(name, False, {"error": str(error)}))
            raise
        ok = bool(result.get("ok", True)) if isinstance(result, dict) else True
        self.steps.append(Step(name, ok, result if isinstance(result, dict) else {}))
        return result

    def evidence(self) -> list:
        return [step.as_dict() for step in self.steps]

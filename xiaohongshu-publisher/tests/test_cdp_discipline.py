# -*- coding: utf-8 -*-
"""小红书千帆：`XhsPage` 的离线回归（假 client，不连浏览器）。

重点验证"纪律守卫"真的会**拒绝执行**——这些拒绝正是历史事故的防线。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "xiaohongshu-publisher"))

from xiaohongshu_publish.cdp import DisciplineError, XhsPage  # noqa: E402


class FakeClient:
    """记录调用，并按脚本内容返回预设结果。"""

    def __init__(self, *, drawers: int = 0, visibility: str = "visible",
                 hit_text: str = "目标", title_ok: bool = True) -> None:
        self.drawers = drawers
        self.visibility = visibility
        self.hit_text = hit_text
        self.title_ok = title_ok
        self.sent: list = []
        self.evaluated: list = []

    def evaluate(self, script: str):
        self.evaluated.append(script)
        if "document.visibilityState" in script and "material-space-drawer" in script:
            return {"drawers": self.drawers, "masks": self.drawers, "visibility": self.visibility}
        if script.strip() == "document.visibilityState":
            return self.visibility
        if "d-drawer-mask" in script and "material-space-drawer" in script:
            return {"drawers": self.drawers, "masks": self.drawers, "visibility": self.visibility}
        if "elementFromPoint" in script:
            return {"found": True, "tag": "span", "cls": "d-text", "text": self.hit_text,
                    "chain": ["span.d-text"], "rect": {"x": 0, "y": 0, "w": 10, "h": 10}}
        if "HTMLInputElement.prototype" in script:
            return {"ok": self.title_ok, "value": "标题", "length": 2}
        if "drawer.querySelectorAll" in script:
            return {"found": True, "x": 100, "y": 200} if self.drawers else {"found": False}
        return {}

    def send(self, method: str, params: dict):
        self.sent.append((method, params))
        return 1


def test_click_refuses_when_tab_is_hidden():
    page = XhsPage(FakeClient(visibility="hidden"))
    with pytest.raises(DisciplineError) as error:
        page.click(10, 10)
    assert "不可见" in str(error.value)


def test_click_refuses_when_drawer_is_open():
    page = XhsPage(FakeClient(drawers=1))
    with pytest.raises(DisciplineError) as error:
        page.click(10, 10)
    assert "抽屉" in str(error.value)


def test_click_refuses_when_hit_is_not_the_target():
    """命中反查发现最上层不是目标 → 不点，并返回证据（这就是"被盖住"的识别方式）。"""
    page = XhsPage(FakeClient(hit_text="d-drawer-footer 取消 确认"))
    result = page.click(626, 1246, expect_text="信息已确认，下一步")
    assert result["clicked"] is False
    assert "覆盖层" in result["reason"]
    assert page.client.sent == []


def test_click_proceeds_when_hit_matches():
    page = XhsPage(FakeClient(hit_text="信息已确认，下一步"))
    result = page.click(626, 1246, expect_text="信息已确认，下一步")
    assert result["clicked"] is True
    assert [m for m, _ in page.client.sent] == ["Input.dispatchMouseEvent"] * 3


def test_close_drawer_clicks_its_own_cancel():
    """点「取消」之后抽屉才算关：假件要模拟"点之前开着、点之后关上"。"""
    fake = FakeClient(drawers=1)
    page = XhsPage(fake)
    state = {"drawers": 1}

    def evaluate(script: str):
        if "drawer.querySelectorAll" in script:
            return {"ok": True, "x": 1125, "y": 1238}
        return {"drawers": state["drawers"], "masks": state["drawers"], "visibility": "visible"}

    def send(method: str, params: dict):
        fake.sent.append((method, params))
        state["drawers"] = 0          # 点了取消 → 抽屉关上
        return 1

    fake.evaluate = evaluate  # type: ignore[assignment]
    fake.send = send          # type: ignore[assignment]
    assert page.close_drawer() is True
    assert any(m == "Input.dispatchMouseEvent" for m, _ in fake.sent)


def test_require_drawer_closed_raises():
    page = XhsPage(FakeClient(drawers=1))
    with pytest.raises(DisciplineError):
        page.require_drawer_closed()


def test_set_title_records_step_and_uses_native_setter():
    page = XhsPage(FakeClient())
    result = page.set_title("桑蚕丝羊毛小腿袜女秋冬款日系撞色罗口美腿袜")
    assert result["ok"] is True
    assert any("HTMLInputElement.prototype" in script for script in page.client.evaluated)
    assert page.evidence()[0]["name"] == "set_title"


def test_run_records_failure_and_reraises():
    page = XhsPage(FakeClient())

    def boom():
        raise ValueError("炸了")

    with pytest.raises(ValueError):
        page.run("boom", boom)
    assert page.evidence()[0]["ok"] is False

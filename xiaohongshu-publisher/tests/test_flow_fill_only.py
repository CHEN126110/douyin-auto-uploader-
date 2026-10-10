# -*- coding: utf-8 -*-
"""小红书千帆：`fill_only` 编排的离线回归（假页面，不连浏览器）。

重点：**授权门**——没授权时一张图都不许上传，且不碰平台。
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "xiaohongshu-publisher"))

from xiaohongshu_publish.flow import FillPlan, run_fill_only  # noqa: E402

GOOD_TITLE = "桑蚕丝羊毛小腿袜女秋冬款日系撞色罗口美腿袜冬天长筒堆堆袜"


class FakePage:
    """按真实调用序列返回结果；记录所有动作以便断言"没做不该做的事"。"""

    def __init__(self, *, drawer_closable: bool = True, title_value: str | None = None,
                 category_lines: list | None = None) -> None:
        self.drawer_closable = drawer_closable
        self.title_value = GOOD_TITLE if title_value is None else title_value
        self.category_lines = category_lines if category_lines is not None else [
            "商品类目", "智能推荐", "长筒袜(未开通)", "短筒袜(未开通)"]
        self.actions: list = []

    def close_drawer(self) -> bool:
        self.actions.append("close_drawer")
        return self.drawer_closable

    def set_title(self, title: str) -> dict:
        self.actions.append("set_title")
        return {"ok": True, "value": self.title_value, "length": len(self.title_value or "")}

    def state(self) -> dict:
        self.actions.append("state")
        return {"title_counter": "56/60", "category_lines": self.category_lines, "errors": []}

    def run(self, name: str, action):
        self.actions.append("run:" + name)
        return action()

    def evidence(self) -> list:
        return [{"name": a, "ok": True} for a in self.actions]


def test_upload_is_refused_without_authorization():
    """核心安全断言：没授权 → 不上传、不碰平台，并说明原因。"""
    page = FakePage()
    report = run_fill_only(page, FillPlan(title=GOOD_TITLE, images=["a.jpg"]))
    assert report["ok"] is False
    assert any("未授权上传" in item for item in report["blocked"])
    assert "set_title" not in page.actions        # 也不该继续往下填
    assert "run:upload_images" not in page.actions


def test_bad_title_is_rejected_before_touching_the_page():
    page = FakePage()
    report = run_fill_only(page, FillPlan(title="测"))
    assert report["ok"] is False
    assert page.actions == []                     # 页面一次都没碰


def test_drawer_that_cannot_close_stops_the_flow():
    page = FakePage(drawer_closable=False)
    report = run_fill_only(page, FillPlan(title=GOOD_TITLE))
    assert report["ok"] is False
    assert any("抽屉关不掉" in item for item in report["blocked"])
    assert "set_title" not in page.actions


def test_authorized_upload_runs_then_title_is_set():
    page = FakePage()
    uploaded: list = []

    def upload(paths):
        uploaded.extend(paths)
        return {"ok": True, "uploaded": len(paths)}

    report = run_fill_only(page, FillPlan(title=GOOD_TITLE, images=["a.jpg", "b.jpg"],
                                          allow_upload=True), upload_fn=upload)
    assert uploaded == ["a.jpg", "b.jpg"]
    assert "run:upload_images" in page.actions
    assert "set_title" in page.actions
    assert report["title_counter"] == "56/60"


def test_title_readback_mismatch_stops_the_flow():
    """回读不一致（被截断/改写）必须停，而不是当作成功。"""
    page = FakePage(title_value="被平台改写过的标题")
    report = run_fill_only(page, FillPlan(title=GOOD_TITLE))
    assert report["ok"] is False
    assert any("回读不一致" in item for item in report["blocked"])


def test_unopened_category_is_reported_not_worked_around():
    """类目未开通只报告、不绕过（不选类目、不点下一步）。"""
    page = FakePage(category_lines=["商品类目", "智能推荐", "长筒袜(未开通)"])
    report = run_fill_only(page, FillPlan(title=GOOD_TITLE))
    assert report["ok"] is True                   # 填写本身成功
    assert report["category_unopened"] == ["长筒袜(未开通)"]
    assert any("需人工" in item for item in report["blocked"])
    assert "next" not in " ".join(page.actions)   # 绝不点下一步


def test_no_upload_needed_when_images_empty():
    page = FakePage()
    report = run_fill_only(page, FillPlan(title=GOOD_TITLE))
    assert report["ok"] is True
    assert "run:upload_images" not in page.actions

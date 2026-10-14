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


def test_required_gaps_reads_platform_judges():
    """"还差什么"必须读平台判据（required-icon 标记 + 三套计数），不能自己猜。"""
    from xiaohongshu_publish.flow import required_gaps

    class GapClient:
        @staticmethod
        def evaluate(script: str):
            if "required-icon" in script:
                return {"required_count": 13,
                        "unfilled": ["物流模板", "运费模板"],
                        "filled": ["商品标题", "商品主图"]}
            return {"key_attrs": ["关键属性 6/7"], "other_attrs": ["其他属性 4/8"],
                    "required": ["1 项必填"], "helper_placeholder": True}

    class GapPage:
        client = GapClient()

    gaps = required_gaps(GapPage())
    assert gaps["required_count"] == 13
    assert gaps["unfilled"] == ["物流模板", "运费模板"]
    assert gaps["filled"] == ["商品标题", "商品主图"]
    assert gaps["judges"]["key_attrs"] == ["关键属性 6/7"]
    assert gaps["judges"]["helper_placeholder"] is True


def test_fill_only_reports_gaps_even_if_they_read_empty():
    """判据读不到不应判填写失败（gaps 是附加信息）。"""
    page = FakePage()
    report = run_fill_only(page, FillPlan(title=GOOD_TITLE))
    assert report["ok"] is True
    assert "gaps" in report


# --- fill_gaps：读缺口 → 补 → 复读（三种情形） -------------------------------

class GapSequencePage:
    """按调用次序返回不同的缺口序列，用来观察 fill_gaps 的循环行为。"""

    def __init__(self, sequence: list) -> None:
        self.sequence = list(sequence)
        self.reads = 0

        outer = self

        class _Client:
            @staticmethod
            def evaluate(script: str):
                if "required-icon" in script:
                    index = min(outer.reads, len(outer.sequence) - 1)
                    outer.reads += 1
                    return {"required_count": 13, "unfilled": list(outer.sequence[index]),
                            "filled": []}
                return {"key_attrs": ["关键属性 6/7"], "required": ["1 项必填"]}

        self.client = _Client()


def test_fill_gaps_stops_immediately_when_no_gaps():
    from xiaohongshu_publish.flow import fill_gaps

    page = GapSequencePage([[]])
    called = []
    out = fill_gaps(page, lambda gaps: called.append(gaps))
    assert called == []                       # 没缺口就不该调 filler
    assert out["rounds"][0]["note"] == "无必填缺口"
    assert out["final"]["unfilled"] == []


def test_fill_gaps_fills_then_rereads_until_clear():
    from xiaohongshu_publish.flow import fill_gaps

    page = GapSequencePage([["物流模板"], ["物流模板"], []])
    out = fill_gaps(page, lambda gaps: {"filled": gaps["unfilled"]})
    assert len(out["rounds"]) == 3
    assert out["rounds"][0]["unfilled"] == ["物流模板"]
    assert out["rounds"][-1]["unfilled"] == []
    assert out["final"]["unfilled"] == []


def test_fill_gaps_records_filler_error_and_stops():
    from xiaohongshu_publish.flow import fill_gaps

    page = GapSequencePage([["运费模板"]])

    def boom(gaps):
        raise RuntimeError("模板还没建")

    out = fill_gaps(page, boom)
    assert out["rounds"][0]["error"] == "模板还没建"   # 记录而不是吞掉
    assert len(out["rounds"]) == 1                     # 出错即停


# --- 服务信息组 filler（三情形） ---------------------------------------------

class _ScriptedClient:
    """按脚本内容返回预设结果，并记录是否被求值。"""

    def __init__(self, open_result: dict, pick_result: dict) -> None:
        self.open_result = open_result
        self.pick_result = pick_result
        self.evaluated: list = []

    def evaluate(self, script: str):
        self.evaluated.append(script)
        return self.pick_result if "option_not_painted" in script else self.open_result


class _ClickPage:
    def __init__(self, open_result: dict, pick_result: dict) -> None:
        self.client = _ScriptedClient(open_result, pick_result)
        self.clicks: list = []

    def _dispatch_click(self, x: int, y: int) -> None:
        self.clicks.append((x, y))


def test_service_filler_skips_fields_without_values():
    """没给取值就明确跳过——绝不瞎选一个值凑数。"""
    from xiaohongshu_publish.flow import make_service_filler

    page = _ClickPage({"ok": True, "x": 1, "y": 2}, {"ok": True, "x": 3, "y": 4})
    filler = make_service_filler(page, values={})
    out = filler({"unfilled": ["物流模板"]})
    assert out["物流模板"] == {"skipped": "未提供取值（不猜）"}
    assert page.clicks == []                     # 一次都没点
    assert page.client.evaluated == []           # 一次都没求值


def test_service_filler_reports_open_failure_with_stage():
    """打开失败要报 stage=open + 原因（例如模板未建），而不是静默跳过。"""
    from xiaohongshu_publish.flow import make_service_filler

    page = _ClickPage({"ok": False, "reason": "template_missing"},
                      {"ok": True, "x": 3, "y": 4})
    filler = make_service_filler(page, values={"运费模板": "默认模板"})
    out = filler({"unfilled": ["运费模板"]})
    assert out["运费模板"]["ok"] is False
    assert out["运费模板"]["stage"] == "open"
    assert out["运费模板"]["reason"] == "template_missing"
    assert page.clicks == []


def test_service_filler_picks_option_and_records_evidence():
    from xiaohongshu_publish.flow import make_service_filler

    page = _ClickPage({"ok": True, "x": 1, "y": 2}, {"ok": True, "x": 3, "y": 4})
    filler = make_service_filler(page, values={"物流模板": "默认模板"})
    out = filler({"unfilled": ["物流模板", "未知字段"]})
    assert out["物流模板"] == {"ok": True, "value": "默认模板"}
    assert page.clicks == [(1, 2), (3, 4)]       # 先开字段，再点选项
    assert out["未知字段"]["skipped"].startswith("非服务信息组字段")


# --- 发布路线：类目选择 → 下一步 → 服务信息（2026-10 新增） -----------------

class RoutePage:
    """假页面：记录 select_category / advance_next 用到的点击与求值。"""

    def __init__(self, *, find_ok: bool = True, click_ok: bool = True,
                 find_text: str = "长筒袜", hit_text: str = "长筒袜",
                 category_lines: list | None = None,
                 drawer_closable: bool = True) -> None:
        self.find_ok = find_ok
        self.click_ok = click_ok
        self.find_text = find_text
        self.hit_text = hit_text
        self.category_lines = category_lines if category_lines is not None else [
            "商品类目", "已选类目", "已选类目: 女士内衣/男士内衣/家居服 > 短袜/打底袜/丝袜/美腿袜 > 长筒袜"]
        self.drawer_closable = drawer_closable
        self.actions: list = []
        self.evaluated: list = []

        outer = self

        class _Client:
            def evaluate(self, script: str):
                outer.evaluated.append(script)
                if "option_not_painted" in script or "请选择" in script:
                    return {"ok": True, "x": 10, "y": 20}
                return {"ok": outer.find_ok, "reason": "not_found" if not outer.find_ok else "",
                        "x": 5, "y": 6, "text": outer.find_text}

        self.client = _Client()

    def close_drawer(self) -> bool:
        self.actions.append("close_drawer")
        return self.drawer_closable

    def set_title(self, title: str) -> dict:
        self.actions.append("set_title")
        return {"ok": True, "value": title, "length": len(title)}

    def click(self, x: int, y: int, expect_text: str = "") -> dict:
        self.actions.append("click:{}".format(expect_text))
        if not self.click_ok:
            return {"clicked": False, "reason": "命中元素不是目标",
                    "hit": {"text": self.hit_text}}
        return {"clicked": True, "hit": {"text": self.hit_text}}

    def _dispatch_click(self, x: int, y: int) -> None:
        self.actions.append("dispatch:({},{})".format(x, y))

    def state(self) -> dict:
        self.actions.append("state")
        return {"title_counter": "56/60", "category_lines": self.category_lines,
                "errors": []}

    def run(self, name: str, action):
        self.actions.append("run:" + name)
        return action()

    def evidence(self) -> list:
        return [{"name": a, "ok": True} for a in self.actions]


def test_select_category_refuses_unopened_target():
    """目标类目带「(未开通)」时必须拒绝点选（不绕过平台资质）。"""
    from xiaohongshu_publish.flow import select_category

    page = RoutePage()
    out = select_category(page, "长筒袜(未开通)")
    assert out["ok"] is False
    assert "未开通" in out["reason"]
    assert page.actions == []                     # 一次都没碰页面


def test_select_category_closes_drawer_first_then_clicks():
    """纪律 4：先关抽屉再点类目；点完回读「已选类目」。"""
    from xiaohongshu_publish.flow import select_category

    page = RoutePage()
    out = select_category(page, "长筒袜")
    assert out["ok"] is True
    assert page.actions[0] == "close_drawer"
    assert "click:长筒袜" in page.actions
    assert any("已选类目" in line for line in out["selected_lines"])


def test_select_category_reports_when_not_found():
    from xiaohongshu_publish.flow import select_category

    page = RoutePage(find_ok=False)
    out = select_category(page, "运动袜")
    assert out["ok"] is False
    assert "未找到" in out["reason"]
    assert not any(a.startswith("click:") for a in page.actions)


def test_advance_next_refuses_without_selected_category():
    """没选类目就点下一步必须停（平台会拦：请选择商品类目）。"""
    page = FakePage(category_lines=["商品类目", "智能推荐"])
    report = run_fill_only(page, FillPlan(title=GOOD_TITLE, allow_advance=True))
    assert report["ok"] is False
    assert any("未选类目" in item for item in report["blocked"])
    assert "run:advance_next" not in page.actions


def test_advance_next_refuses_when_target_category_unopened():
    """目标类目未开通时停止，不点下一步。"""
    page = FakePage(category_lines=["商品类目", "长筒袜(未开通)"])
    report = run_fill_only(page, FillPlan(title=GOOD_TITLE, category="长筒袜",
                                          allow_advance=True))
    assert report["ok"] is False
    assert any("未开通" in item for item in report["blocked"])
    assert "run:select_category" not in page.actions
    assert "run:advance_next" not in page.actions


def test_full_route_selects_category_then_advances():
    """完整发布路线：选类目 → 下一步 → 服务信息（只填给了取值的）。"""
    page = RoutePage()
    report = run_fill_only(page, FillPlan(
        title=GOOD_TITLE, category="长筒袜", allow_advance=True,
        service_values={"物流模板": "【系统创建】物流模板默认—联系人"}))
    assert report["ok"] is True
    assert "run:select_category" in page.actions
    assert "run:advance_next" in page.actions
    names = [s["name"] for s in report["steps"]]
    assert "select_category" in names
    assert "advance_next" in names
    assert "service_fill" in report


def test_service_values_without_advance_are_ignored():
    """没推进到四组信息就不该去填服务信息（表单还没展开）。"""
    page = RoutePage()
    report = run_fill_only(page, FillPlan(
        title=GOOD_TITLE, category="长筒袜", allow_advance=False,
        service_values={"物流模板": "x"}))
    assert "service_fill" not in report
    assert "run:advance_next" not in page.actions


# --- 类目自动选中是**异步**的：守卫必须轮询，不能读一次就拒绝 -------------------

class AutoselectPage:
    """前 N 次 `state()` 还没有「已选类目」，之后才有 —— 模拟平台的异步自动选中。"""

    def __init__(self, appear_after: int) -> None:
        self.calls = 0
        self.appear_after = appear_after

    def state(self):
        self.calls += 1
        if self.calls > self.appear_after:
            return {"category_lines": ["商品类目",
                                       "已选类目：女士内衣/男士内衣/家居服 > 短袜/打底袜/丝袜/美腿袜 > 中筒袜"]}
        return {"category_lines": ["商品类目", "上传图片并完成标题后为您智能识别类目"]}


def test_wait_for_selected_category_polls_until_it_appears():
    """真机实测（2026-10-14）：写完标题后类目是**异步**自动选中的 ✗

    读一次就判"未选类目"会让整条链卡在第一步（本轮出现两次）→ 必须轮询 ✓。
    """
    from xiaohongshu_publish.flow import wait_for_selected_category

    page = AutoselectPage(appear_after=2)
    selected = wait_for_selected_category(page, timeout=3.0, interval=0.01)

    assert selected.endswith("中筒袜"), "没等到平台自动选中的类目：%r" % (selected,)
    assert page.calls >= 3, "没有轮询（只读了 %d 次）" % (page.calls,)


def test_wait_for_selected_category_returns_empty_when_never_selected():
    """一直没选中就如实返回空串（**不编造类目** ✗），由调用方决定怎么报错。"""
    from xiaohongshu_publish.flow import wait_for_selected_category

    page = AutoselectPage(appear_after=10_000)
    assert wait_for_selected_category(page, timeout=0.05, interval=0.01) == ""

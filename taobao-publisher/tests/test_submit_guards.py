# -*- coding: utf-8 -*-
"""给 ``submit`` 的硬前置条件补测试。

审查 `stage_submit` 时发现的漏洞：它读了 ``ctx.scratch["readback"]``，
但**只用于记录**，不作为放行条件。文档写着「真正的前置校验由前面的 readback
阶段负责」——那只是**对计划的假设**，不是被强制的不变量：任何直接调用
``run_stage(ctx, "submit")`` 的路径都会完全跳过 readback。

平台是**点击之后才校验**的（实测：标题为空时提交按钮仍然可用），
所以「按钮可用」根本不能当放行信号。

守卫现在放在**连页面之前**，因此可以完全离线测。
"""

from __future__ import annotations

import pathlib
import sys
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SUBPROJECT = REPO_ROOT / "taobao-publisher"
if str(SUBPROJECT) not in sys.path:
    sys.path.insert(0, str(SUBPROJECT))

from taobao_publish import stages  # noqa: E402
from taobao_publish.authorization import WriteAuthorization  # noqa: E402
from taobao_publish.models import PublishItem  # noqa: E402


def make_ctx(*, readback=None, dry_run=False, unlocked=True):
    item = PublishItem(record_id=1, record_name="测试商品", title="测试标题")
    ctx = stages.PipelineContext(
        item=item,
        dry_run=dry_run,
        authorization=WriteAuthorization(
            granted=frozenset({"upload_image", "save_draft", "submit_publish"}),
            submit_unlocked=unlocked,
            source="test",
        ),
    )
    if readback is not None:
        ctx.scratch["readback"] = readback
    return ctx


class SubmitRequiresReadbackTest(unittest.TestCase):
    """**没有通过的回读核对就不许提交。**"""

    def test_refuses_when_readback_never_ran(self) -> None:
        ctx = make_ctx(readback=None)
        outcome = stages.stage_submit(ctx)
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.error_code, "SUBMIT_WITHOUT_READBACK")
        self.assertTrue(outcome.blockers, "必须给出阻塞项说明为什么拒绝")

    def test_refuses_when_readback_is_not_a_mapping(self) -> None:
        ctx = make_ctx(readback="ok")
        outcome = stages.stage_submit(ctx)
        self.assertEqual(outcome.error_code, "SUBMIT_WITHOUT_READBACK")

    def test_refuses_when_readback_has_mismatches(self) -> None:
        ctx = make_ctx(readback={
            "matched": [{"label": "宝贝标题", "value": "X"}],
            "mismatched": [{"label": "一口价", "expected": "16.80", "actual": ""}],
            "unreadable": [],
        })
        outcome = stages.stage_submit(ctx)
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.error_code, "SUBMIT_BLOCKED_BY_FORM")

    def test_refuses_when_readback_has_unreadable_fields(self) -> None:
        ctx = make_ctx(readback={
            "matched": [], "mismatched": [],
            "unreadable": [{"label": "总库存", "reason": "LabelNotFound"}],
        })
        outcome = stages.stage_submit(ctx)
        self.assertEqual(outcome.error_code, "SUBMIT_BLOCKED_BY_FORM")

    def test_guard_runs_before_touching_the_browser(self) -> None:
        """守卫必须在**连页面之前**，否则条件不满足时也会去连一次浏览器。

        离线可测正是这个顺序带来的好处：ctx 里没有任何真实的 CDP 地址，
        如果守卫跑到连页面之后，这条用例会以连接错误而不是我们的错误码结束。
        """

        outcome = stages.stage_submit(make_ctx(readback=None))
        self.assertEqual(outcome.error_code, "SUBMIT_WITHOUT_READBACK")

    def test_dry_run_still_skips_before_the_guard(self) -> None:
        """dry-run 的跳过在**执行器**里，早于处理器——所以拿不到
        ``SUBMIT_WITHOUT_READBACK``，也不该拿到。这条只是把顺序钉住。"""

        import inspect

        source = inspect.getsource(stages.stage_submit)
        self.assertLess(
            source.index("SUBMIT_WITHOUT_READBACK"),
            source.index("_open_publish_page"),
            "守卫必须在连页面之前",
        )

    def test_authorization_gate_still_wins_over_the_readback_guard(self) -> None:
        """授权门在执行器里，比处理器更早——没授权时不该走到回读检查。

        这条防的是「把守卫写进处理器后，误以为处理器是唯一关卡」。
        """

        ctx = make_ctx(readback={"matched": [], "mismatched": [], "unreadable": []},
                       unlocked=False)
        run = stages.run_stage("submit", ctx, index=0, total=1, steps=[])
        self.assertFalse(run.outcome.ok)
        self.assertEqual(run.outcome.error_code, "SUBMIT_NOT_AUTHORIZED")


if __name__ == "__main__":
    unittest.main()

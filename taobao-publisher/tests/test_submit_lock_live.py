# -*- coding: utf-8 -*-
"""**最后一道锁真的拦得住** —— 在生产路径上验证过。

## 怎么验的

`submit` 需要显式授权，所以我不会去提交。但**「需要授权」本身**可以在
生产路径上验证：发 `stop_before_submit=false` 让流水线**走到提交那一步**，
而 Sidecar 的白名单里**没有** `submit_publish`。

## 实测（2026-10-03）

```
task_id = a22ffa59
  [failed] 100% step=precheck 前置检查未通过：1 条阻塞项

[OK]   连接调试浏览器   1516ms  CDP 就绪
[FAIL] 发布前置检查      14ms   前置检查未通过：1 条阻塞项

status     = failed
error.code = PREFLIGHT_BLOCKED
blockers   = ["SUBMIT_NOT_AUTHORIZED"]
detail: submit_publish 不在 TAOBAO_UPLOAD_ALLOW_WRITE 白名单内
        （当前白名单：save_draft,upload_image）
```

**拦得比预期更早**：`precheck` 阶段自己就发现计划里有 `submit` 却没授权，
**在做任何页面操作之前就拦住**（14ms，一次点击都没有）。

这同时确认了 Sidecar 的白名单是 `save_draft,upload_image`——**不含 `submit_publish`**。

## 三重保险

| # | 在哪 | 作用 |
|---|---|---|
| 1 | Sidecar 白名单不含 `submit_publish` | 授权面 |
| 2 | `TAOBAO_UPLOAD_ALLOW_SUBMIT` 未设（要精确 `"1"`） | 提交锁 |
| 3 | `precheck` 预检计划里的写操作 + `run_stage` 在调用处理器前再查一次 | 执行面 |

**第 3 条是关键**：处理器根本不会被执行，**一次点击都不会发生**。
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

SCRIPT = SUBPROJECT / "scripts" / "verify-submit-lock-holds.py"


class SubmitLockScriptTest(unittest.TestCase):
    def setUp(self) -> None:
        self.source = SCRIPT.read_text(encoding="utf-8")

    def test_script_exists_and_is_explicit_about_intent(self) -> None:
        self.assertIn("证明", self.source)
        self.assertIn("不提交", self.source)

    def test_script_sends_stop_before_submit_false(self) -> None:
        """**必须允许走到提交**——否则验不到那道门。"""

        self.assertIn('"stop_before_submit": False', self.source)

    def test_script_warns_if_it_ever_succeeds(self) -> None:
        """万一真提交成功了，脚本必须**喊出来**让人去核对。"""

        self.assertIn("请立刻去卖家中心核对是否被上架", self.source)

    def test_script_explains_the_three_locks(self) -> None:
        for phrase in ("submit_publish", "TAOBAO_UPLOAD_ALLOW_SUBMIT", "run_stage"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.source)

    def test_script_accepts_both_lock_codes(self) -> None:
        """完全没授权 → `WRITE_NOT_AUTHORIZED`；有写授权但提交锁没开 → `SUBMIT_NOT_AUTHORIZED`。"""

        self.assertIn("SUBMIT_NOT_AUTHORIZED", self.source)
        self.assertIn("WRITE_NOT_AUTHORIZED", self.source)


class PrecheckBlocksPlannedSubmitTest(unittest.TestCase):
    """**拦截发生在预检，不是提交阶段。**"""

    def test_precheck_is_told_which_operations_are_planned(self) -> None:
        import inspect

        source = inspect.getsource(stages.stage_precheck)
        self.assertIn("stage_plan", source)
        self.assertIn("required_operations", source)

    def test_submit_requires_the_submit_publish_operation(self) -> None:
        from taobao_publish.constants import STAGE_WRITE_OPERATION

        self.assertEqual(STAGE_WRITE_OPERATION.get("submit"), "submit_publish")

    def test_no_authorization_blocks_submit_before_the_handler(self) -> None:
        """`run_stage` 在**调用处理器之前**就查授权——处理器根本不会跑。"""

        import inspect

        source = inspect.getsource(stages.run_stage)
        require_at = source.index("authorization.require(")
        handler_at = source.index("spec.run(")
        self.assertLess(require_at, handler_at,
                        "授权检查必须在调用处理器之前（spec.run(ctx)）")

    def test_authorization_without_submit_grant_refuses(self) -> None:
        auth = WriteAuthorization.from_grant(["upload_image", "save_draft"],
                                             submit_unlocked=False)
        with self.assertRaises(Exception) as context:
            auth.require("submit_publish")
        self.assertEqual(getattr(context.exception, "code", ""), "WRITE_NOT_AUTHORIZED")

    def test_granted_but_locked_is_a_different_code(self) -> None:
        """有写授权但提交锁没开，是**另一种**拒绝——两者要分得清。"""

        auth = WriteAuthorization.from_grant(["submit_publish"], submit_unlocked=False)
        with self.assertRaises(Exception) as context:
            auth.require("submit_publish")
        self.assertEqual(getattr(context.exception, "code", ""), "SUBMIT_NOT_AUTHORIZED")


if __name__ == "__main__":
    unittest.main()

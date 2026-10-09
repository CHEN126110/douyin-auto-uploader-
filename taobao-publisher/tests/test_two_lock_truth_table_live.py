# -*- coding: utf-8 -*-
"""锁的真值表：**两把锁各自独立生效**。

## 完整真值表

| 白名单含 `submit_publish` | `ALLOW_SUBMIT=1` | 结果 | 验证方式 |
|---|---|---|---|
| ✗ | ✗ | `WRITE_NOT_AUTHORIZED` | 第 61 轮**实机** |
| **✓** | **✗** | **`SUBMIT_NOT_AUTHORIZED`** | **第 78 轮实机**（本轮） |
| ✗ | ✓ | `WRITE_NOT_AUTHORIZED`（白名单里没有它） | 单测 |
| ✓ | ✓ | 会执行 | **从未**——需要用户授权 |

## 本轮那格的实测

> 白名单 = `upload_image,save_draft,submit_publish`，`TAOBAO_UPLOAD_ALLOW_SUBMIT` 未设

```
blockers = ["SUBMIT_NOT_AUTHORIZED"]
detail   = submit_publish 已获白名单，但缺少第二把锁 TAOBAO_UPLOAD_ALLOW_SUBMIT=1
流水线跑到「提交」那一步了吗：否（在更早处停下）
```

**拦截发生在 `precheck`（0ms，页面一次没碰）。**

**为什么安全**：提交锁没开 → `require("submit_publish")` 必抛 → 处理器不会被执行。

**为什么值得单独验**：两把锁若只是「都通向同一个拒绝」，那第二把就是装饰。
`detail` 明确区分了「缺白名单」与「缺第二把锁」——**这个区分是实机验过的**。
"""
from __future__ import annotations

import pathlib
import sys
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SUBPROJECT = REPO_ROOT / "taobao-publisher"
if str(SUBPROJECT) not in sys.path:
    sys.path.insert(0, str(SUBPROJECT))

SCRIPT = SUBPROJECT / "scripts" / "verify-second-lock-holds.py"

from taobao_publish.authorization import WriteAuthorization  # noqa: E402


class TwoLockTruthTableTest(unittest.TestCase):
    """真值表四格——后三格可以在单测里直接验。"""

    def test_no_grant_at_all(self) -> None:
        auth = WriteAuthorization.from_grant([], submit_unlocked=False)
        with self.assertRaises(Exception) as context:
            auth.require("submit_publish")
        self.assertEqual(getattr(context.exception, "code", ""), "WRITE_NOT_AUTHORIZED")

    def test_granted_but_locked(self) -> None:
        """**本轮实机验的那一格。**"""

        auth = WriteAuthorization.from_grant(["upload_image", "save_draft", "submit_publish"],
                                             submit_unlocked=False)
        with self.assertRaises(Exception) as context:
            auth.require("submit_publish")
        self.assertEqual(getattr(context.exception, "code", ""), "SUBMIT_NOT_AUTHORIZED")

    def test_locked_flag_without_the_whitelist_entry(self) -> None:
        auth = WriteAuthorization.from_grant(["upload_image"], submit_unlocked=True)
        with self.assertRaises(Exception) as context:
            auth.require("submit_publish")
        self.assertEqual(getattr(context.exception, "code", ""), "WRITE_NOT_AUTHORIZED",
                         "白名单里没有它 → 仍是第一把锁的问题")

    def test_both_open_grants(self) -> None:
        auth = WriteAuthorization.from_grant(["submit_publish"], submit_unlocked=True)
        auth.require("submit_publish")   # 不抛

    def test_the_two_codes_are_different(self) -> None:
        """⚠️ **两把锁若通向同一个拒绝，第二把就是装饰。**"""

        no_grant = WriteAuthorization.from_grant([], submit_unlocked=False)
        locked = WriteAuthorization.from_grant(["submit_publish"], submit_unlocked=False)
        codes = []
        for auth in (no_grant, locked):
            with self.assertRaises(Exception) as context:
                auth.require("submit_publish")
            codes.append(getattr(context.exception, "code", ""))
        self.assertNotEqual(codes[0], codes[1])
        self.assertEqual(set(codes), {"WRITE_NOT_AUTHORIZED", "SUBMIT_NOT_AUTHORIZED"})


class SecondLockScriptTest(unittest.TestCase):
    def setUp(self) -> None:
        self.source = SCRIPT.read_text(encoding="utf-8")

    def test_it_sends_stop_before_submit_false(self) -> None:
        """**必须允许走到提交**——否则验不到第二把锁。"""

        self.assertIn('"stop_before_submit": False', self.source)

    def test_it_warns_if_submission_ever_succeeds(self) -> None:
        self.assertIn("请立刻去卖家中心核对", self.source)

    def test_it_distinguishes_the_two_rejection_codes(self) -> None:
        """⚠️ 若报的是 `WRITE_NOT_AUTHORIZED`，说明白名单没配对——**那与实测目的不符**。"""

        self.assertIn("SUBMIT_NOT_AUTHORIZED", self.source)
        self.assertIn("WRITE_NOT_AUTHORIZED", self.source)
        self.assertIn("与本次实测目的不符", self.source)

    def test_it_reports_whether_submit_was_reached(self) -> None:
        self.assertIn("流水线跑到「提交」那一步了吗", self.source)


class PrecheckStillBlocksFirstTest(unittest.TestCase):
    """拦截要发生在**动页面之前**。"""

    def test_precheck_checks_planned_write_operations(self) -> None:
        import inspect

        from taobao_publish import stages
        source = inspect.getsource(stages.stage_precheck)
        self.assertIn("required_operations", source)

    def test_run_stage_checks_authorization_before_the_handler(self) -> None:
        import inspect

        from taobao_publish import stages
        source = inspect.getsource(stages.run_stage)
        self.assertLess(source.index("authorization.require("), source.index("spec.run("))


if __name__ == "__main__":
    unittest.main()

# -*- coding: utf-8 -*-
"""**两道锁的真值表**——尤其是「授权不能压过 dry-run」那一格。

写门是两道：

```python
mutates = operation is not None or (spec is not None and spec.mutates_page)
if mutates and ctx.dry_run:                      # ① dry-run 拦住
    return StageRun(..., skipped_for_dry_run=True)

if operation is not None:
    try:
        ctx.authorization.require(operation)     # ② 授权拦住
    except TaobaoPublishError as exc:
        return StageRun(..., failed(...))
```

已有用例覆盖了三格：

| dry_run | 已授权 | 期望 | 现有覆盖 |
|---|---|---|---|
| True | 否 | 跳过（dry-run） | `test_write_stage_skipped_in_dry_run` |
| False | 否 | 失败 `WRITE_NOT_AUTHORIZED` | `test_write_stage_denied_without_authorization` |
| False | 是 | 走到执行 | 间接（各阶段自己的用例） |
| **True** | **是** | **仍须跳过** | ⚠️ **没有** |

最后一格是**唯一能证明「dry-run 检查在授权检查之前、且授权不构成绕过」**的用例。
如果两道的顺序写反了，或者哪天有人把 `require()` 提到前面，
**一份完整授权就能让 dry-run 变成真写入**——而那正是「默认零写入」红线的反面。
"""

from __future__ import annotations

import pathlib
import sys
import tempfile
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SUBPROJECT = REPO_ROOT / "taobao-publisher"
if str(SUBPROJECT) not in sys.path:
    sys.path.insert(0, str(SUBPROJECT))

from taobao_publish import stages  # noqa: E402
from taobao_publish.authorization import WriteAuthorization  # noqa: E402
from taobao_publish.constants import (  # noqa: E402
    STAGE_ORDER,
    STAGE_WRITE_OPERATION,
    WRITE_OPERATIONS,
)
from taobao_publish.models import (  # noqa: E402
    ImageSet,
    PublishItem,
    SkuEntry,
)
from taobao_publish.pipeline import StepRecord, run_stage  # noqa: E402


def make_item() -> PublishItem:
    return PublishItem(
        record_id=1,
        record_name="ID-真值表",
        title="真值表标题",
        images=ImageSet(main=["主图.jpg"], detail=[]),
        skus=[SkuEntry(spec_values={"尺码": "均码"}, price=1.0, stock=1)],
    )


def full_grant() -> WriteAuthorization:
    """**把所有写操作都授权**——用来证明授权压不过 dry-run。"""

    return WriteAuthorization.from_grant(
        sorted(WRITE_OPERATIONS), submit_unlocked=True, source="truth-table")


def run(stage: str, *, dry_run: bool, authorization: WriteAuthorization):
    ctx = stages.PipelineContext(item=make_item(), dry_run=dry_run,
                                 authorization=authorization)
    with tempfile.TemporaryDirectory(prefix="tb-truth-") as directory:
        ctx.artifacts_dir = directory
        return run_stage(stage, ctx, index=0, total=1,
                         steps=[StepRecord(name=stage)])


class TruthTableTest(unittest.TestCase):
    def test_write_stages_exist(self) -> None:
        """先确认这个用例组有对象可测——写阶段不能是空的。"""

        write_stages = [s for s in STAGE_ORDER
                        if STAGE_WRITE_OPERATION.get(s)]
        self.assertTrue(write_stages, "一个写阶段都没有，真值表就无从谈起")
        self.assertIn("submit", write_stages)

    def test_dry_run_true_not_authorized_is_skipped(self) -> None:
        outcome = run("upload_images", dry_run=True,
                      authorization=WriteAuthorization.none())
        self.assertTrue(outcome.skipped_for_dry_run)
        self.assertEqual(outcome.outcome.status, "skipped")

    def test_dry_run_true_with_full_grant_is_STILL_skipped(self) -> None:
        """⚠️ **这一格是整组用例的重点。**

        **完整授权也不能让 dry-run 变成真写入。** 如果哪天有人把
        `authorization.require()` 提到 `dry_run` 判断之前，
        或者把 dry-run 判断挪进 `require()` 之后，这一格会红。
        """

        outcome = run("upload_images", dry_run=True, authorization=full_grant())
        self.assertTrue(outcome.skipped_for_dry_run,
                        "已授权时 dry-run 仍必须跳过——否则默认零写入的红线就没了")
        self.assertEqual(outcome.outcome.status, "skipped")
        self.assertNotEqual(outcome.outcome.error_code, "WRITE_NOT_AUTHORIZED")

    def test_dry_run_false_not_authorized_fails(self) -> None:
        outcome = run("upload_images", dry_run=False,
                      authorization=WriteAuthorization.none())
        self.assertFalse(outcome.outcome.ok)
        self.assertEqual(outcome.outcome.error_code, "WRITE_NOT_AUTHORIZED")
        self.assertFalse(outcome.skipped_for_dry_run)

    def test_submit_without_any_grant_is_write_not_authorized(self) -> None:
        """**完全没授权**时，提交报的是 `WRITE_NOT_AUTHORIZED`。

        实测确认（第一版用例在这里写错了）：`require()` 里

        ```python
        if name == WRITE_SUBMIT_PUBLISH and name in self.granted:
            raise SubmitNotAuthorizedError(reason)
        raise WriteNotAuthorizedError(name, reason)
        ```

        ——`SUBMIT_NOT_AUTHORIZED` **只在「有写授权但提交锁没开」时**出现。
        两种拒绝要分得清：一种说「你根本没开写」，一种说「你开了写但没开提交」。
        """

        outcome = run("submit", dry_run=False, authorization=WriteAuthorization.none())
        self.assertFalse(outcome.outcome.ok)
        self.assertEqual(outcome.outcome.error_code, "WRITE_NOT_AUTHORIZED")

    def test_submit_granted_but_locked_is_submit_not_authorized(self) -> None:
        """**有写授权、但提交锁没开** —— 这一格才是 `SUBMIT_NOT_AUTHORIZED`。"""

        locked = WriteAuthorization.from_grant(
            ["submit_publish"], submit_unlocked=False, source="truth-table")
        outcome = run("submit", dry_run=False, authorization=locked)
        self.assertFalse(outcome.outcome.ok)
        self.assertEqual(outcome.outcome.error_code, "SUBMIT_NOT_AUTHORIZED",
                         "提交锁没开要与「完全没授权」区分开")

    def test_dry_run_beats_authorization_for_every_write_stage(self) -> None:
        """逐个写阶段验一遍——别只看 `upload_images`。

        `submit` 还有回读前置条件，所以它可能先因别的原因失败；
        这里只断言**它不是被授权放过去的**（即仍然是 skipped）。
        """

        grant = full_grant()
        for stage in STAGE_ORDER:
            if not STAGE_WRITE_OPERATION.get(stage):
                continue
            with self.subTest(stage=stage):
                outcome = run(stage, dry_run=True, authorization=grant)
                self.assertTrue(
                    outcome.skipped_for_dry_run,
                    "{} 在 dry-run + 完整授权下没有跳过".format(stage))


if __name__ == "__main__":
    unittest.main()

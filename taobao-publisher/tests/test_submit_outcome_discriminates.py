# -*- coding: utf-8 -*-
"""`wait_for_submit_outcome` 的判据：**只认新增的提示**。

## 缺陷（2026-10-03 实证）

原判据：

```python
if last.get("messages"):
    return last        # ← 页面上**任何**提示都算「有变化」
```

页面本来就飘着一堆 `.next-message`（说明文字、历史提示）。实测：

```
=== 点击前页面上的提示：5 条 ===
    发布页只展示基础素材……
    宝贝详情图【高/宽≤ 2】……
    点击查看详情
    SKU模式 · 【尺码】单层展示设置隐藏不启用SKU

=== wait_for_submit_outcome 的结果 ===
  耗时：**0.0 秒**（超时设的是 8 秒）
  返回的提示数：5
  其中**点击前就有**的：**5**
  新增的：（无）
```

**所以提交什么都没发生时，它也会立刻返回并报「观察到页面响应」**——
`stage_submit` 会拿一堆旧提示当成「提交的结果」。

**这是第 70~72 轮那个类的又一例**，只不过落在**唯一没跑过的那条路径**上。

## 修后

```
耗时 5.0s（超时 5s）     ← 之前是 0.0s
changed   = False        ← 如实报「没有观察到变化」
new_messages = []
```
"""

from __future__ import annotations

import inspect
import pathlib
import sys
import unittest
from unittest import mock

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SUBPROJECT = REPO_ROOT / "taobao-publisher"
if str(SUBPROJECT) not in sys.path:
    sys.path.insert(0, str(SUBPROJECT))

from taobao_publish import page, stages  # noqa: E402

HREF = "https://item.upload.taobao.com/sell/v2/publish.htm"


class FakeClient:
    """按顺序弹响应；用完之后一直返回最后一个。"""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def evaluate(self, _expression, **_kwargs):
        self.calls += 1
        if len(self.responses) > 1:
            return self.responses.pop(0)
        return self.responses[0]

    def close(self):
        """`stage_submit` 在 `finally` 里会关它。"""
        pass


class WaitForSubmitOutcomeTest(unittest.TestCase):
    def _wait(self, responses, before_messages, timeout=4.0):
        client = FakeClient(responses)
        with mock.patch.object(page.time, "sleep"):
            return page.wait_for_submit_outcome(
                client, HREF, before_messages=before_messages, timeout=timeout)

    def test_a_preexisting_message_is_not_a_change(self) -> None:
        """⚠️ **这一条就是实测的情形。**"""

        outcome = self._wait(
            [{"href": HREF, "messages": [{"text": "本来就有的说明"}]}],
            before_messages=["本来就有的说明"],
        )
        self.assertFalse(outcome["changed"])
        self.assertEqual(outcome["new_messages"], [])

    def test_a_new_message_is_a_change(self) -> None:
        outcome = self._wait(
            [{"href": HREF, "messages": [{"text": "本来就有的说明"},
                                         {"text": "提交失败：缺必填项"}]}],
            before_messages=["本来就有的说明"],
        )
        self.assertTrue(outcome["changed"])
        self.assertEqual(outcome["new_messages"], ["提交失败：缺必填项"])

    def test_a_url_change_is_a_change_even_with_no_new_message(self) -> None:
        outcome = self._wait(
            [{"href": HREF + "?done=1", "messages": [{"text": "老提示"}]}],
            before_messages=["老提示"],
        )
        self.assertTrue(outcome["changed"])

    def test_it_does_not_return_early_on_stale_messages(self) -> None:
        """**关键**：有旧提示时不能立刻返回。"""

        client = FakeClient([{"href": HREF, "messages": [{"text": "老提示"}]}])
        with mock.patch.object(page.time, "sleep"):
            page.wait_for_submit_outcome(client, HREF,
                                         before_messages=["老提示"], timeout=4.0)
        self.assertGreater(client.calls, 1, "应当在轮询，而不是第一次就返回")

    def test_without_a_baseline_it_is_documented_as_degraded(self) -> None:
        """不传基线时退化为「任何提示都算」——**调用方应当传**。"""

        source = inspect.getsource(page.wait_for_submit_outcome)
        self.assertIn("调用方应当传", source)

    def test_timeout_is_reported_as_not_changed(self) -> None:
        outcome = self._wait([{"href": HREF, "messages": []}], before_messages=[])
        self.assertFalse(outcome["changed"])


class StageSubmitReportsHonestlyTest(unittest.TestCase):
    def _run(self, responses, readback_matched=1):
        from taobao_publish.models import PublishItem

        client = FakeClient(responses)
        item = PublishItem(record_id=1, record_name="x", title="标题")
        ctx = stages.PipelineContext(item=item, dry_run=False)
        ctx.scratch["readback"] = {
            "matched": [{"label": "宝贝标题"}] * readback_matched,
            "mismatched": [], "unreadable": [],
        }
        # ⚠️ **把超时压短。**
        #
        # `sleep` 被 mock 掉之后，`wait_for_submit_outcome` 的循环按**真实时钟**
        # 等 deadline，会一路空转满 20 秒（实测 4 个用例跑了 52 秒）。
        #
        # 包一层只改超时——**判据本身不在这里验**，那是上面 6 条单测的事；
        # 这里验的是阶段**怎么报告**。
        real_wait = page.wait_for_submit_outcome

        def short_wait(client_, before_href, **kwargs):
            kwargs.setdefault("timeout", 0.5)
            return real_wait(client_, before_href, **kwargs)

        with mock.patch.object(stages, "_open_publish_page", return_value=client), \
                mock.patch.object(page, "wait_for_submit_outcome", short_wait), \
                mock.patch("taobao_publish.page.time.sleep"):
            return stages.stage_submit(ctx)

    def test_it_says_no_change_when_only_stale_messages_exist(self) -> None:
        """**原判据永远不会说这一句。**"""

        outcome = self._run([
            {"submit": {"present": True, "disabled": False}, "href": HREF},
            {"href": HREF, "messages": [{"text": "本来就有的说明文字"}]},
            {"ok": True},
            {"href": HREF, "messages": [{"text": "本来就有的说明文字"}]},
        ])
        self.assertTrue(outcome.ok)
        self.assertIn("没有观察到页面变化", outcome.summary)
        self.assertIn("都是点击前就有的", outcome.summary)

    def test_it_reports_only_the_new_messages(self) -> None:
        outcome = self._run([
            {"submit": {"present": True, "disabled": False}, "href": HREF},
            {"href": HREF, "messages": [{"text": "本来就有的说明文字"}]},
            {"ok": True},
            {"href": HREF, "messages": [{"text": "本来就有的说明文字"},
                                        {"text": "请填写必填项"}]},
        ])
        self.assertTrue(outcome.ok)
        self.assertIn("页面出现新提示", outcome.summary)
        self.assertIn("请填写必填项", outcome.summary)
        self.assertNotIn("本来就有的说明文字", outcome.summary)

    def test_it_still_never_claims_publish_success(self) -> None:
        outcome = self._run([
            {"submit": {"present": True, "disabled": False}, "href": HREF},
            {"href": HREF, "messages": []},
            {"ok": True},
            {"href": HREF + "?done=1", "messages": []},
        ])
        self.assertIs(outcome.data["publish_confirmed"], False)
        self.assertIn("不声称发布成功", outcome.summary)

    def test_it_carries_the_baseline_into_the_result(self) -> None:
        """`data` 里要有基线——否则事后无法判断「哪些提示是新的」。"""

        outcome = self._run([
            {"submit": {"present": True, "disabled": False}, "href": HREF},
            {"href": HREF, "messages": [{"text": "老提示"}]},
            {"ok": True},
            {"href": HREF, "messages": [{"text": "老提示"}]},
        ])
        self.assertIn("messages_before", outcome.data)
        self.assertIn("new_messages", outcome.data)
        self.assertIn("changed", outcome.data)


if __name__ == "__main__":
    unittest.main()

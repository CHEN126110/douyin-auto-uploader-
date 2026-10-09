# -*- coding: utf-8 -*-
"""就绪度输出**不许自相矛盾**。

修之前：

```
现在能否一键发布：    是                    ← 能
...
必填但不可写的字段（真实发布前必须补齐）：      ← 但这里说「必须补齐 10 个」！
  - item.title
  ...
```

而 `write_route_status` 里写得很清楚：

```python
"protocol_write_ready": contracts_ok and not field_blocked,   # ← 字段卡的是**协议路线**
"dom_write_ready":      contracts_ok and not selector_blocked, # ← 选择器卡的是 DOM 路线
```

我们走** DOM 路线**，它刚成功发布过一次。那 10 个字段与它无关。

这与第 25 轮修过的「`success: True` 底下挂 10 条阻塞项」是同一类：
**把「另一条路线的待办」说成了「本次的阻塞」。**
"""

from __future__ import annotations

import contextlib
import io
import pathlib
import sys
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SUBPROJECT = REPO_ROOT / "taobao-publisher"
if str(SUBPROJECT) not in sys.path:
    sys.path.insert(0, str(SUBPROJECT))

from taobao_publish import __main__ as cli  # noqa: E402
from taobao_publish.pipeline import describe_readiness  # noqa: E402


def readiness_text() -> str:
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        cli.cmd_readiness(type("A", (), {"json": False})())
    return buffer.getvalue()


class ReadinessHonestyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.text = readiness_text()
        self.readiness = describe_readiness()

    def test_does_not_claim_fields_block_publishing(self) -> None:
        """**不许**把协议路线的字段缺口说成「真实发布前必须补齐」。"""

        self.assertNotIn(
            "真实发布前必须补齐", self.text,
            "这句话把协议路线的缺口说成了发布阻塞——而 DOM 路线不依赖它们",
        )

    def test_blocked_fields_are_labelled_as_protocol_route(self) -> None:
        if not self.readiness.blocked_required_fields:
            self.skipTest("当前没有协议路线的字段缺口")
        self.assertIn("协议路线", self.text, "字段缺口必须标明归属路线")
        self.assertIn("DOM 路线", self.text, "要显式说明本次走哪条路")

    def test_dom_route_selectors_are_labelled_as_the_real_gate(self) -> None:
        """与之相对，**选择器**缺口是真的会挡住 DOM 路线——标签要区分开。"""

        if self.readiness.blocked_write_critical_selectors:
            self.assertIn("会挡住 DOM 路线", self.text)
        else:
            self.assertIn("DOM 路线不缺选择器", self.text)

    def test_publishable_and_no_contradiction(self) -> None:
        """能不能发布 = **两条路线里有任一条可用** 且 没有未实现/未完成阶段。

        这条把 `publishable` 的语义钉住：它与「协议路线字段是否齐」**无关**。
        """

        if self.readiness.publishable:
            self.assertTrue(
                self.readiness.dom_write_ready or self.readiness.protocol_write_ready,
                "说能发布，就得至少有一条可用路线",
            )
            self.assertEqual(self.readiness.unimplemented_stages, [])
            self.assertEqual(self.readiness.incomplete_stages, [])

    def test_text_never_says_can_publish_and_also_says_must_fix(self) -> None:
        """整体一致性：说了「能一键发布：是」，就不该在同一份输出里
        出现任何「必须补齐 / 必须先修」这类说法（除非它明确归属另一条路线）。"""

        if "现在能否一键发布：    是" not in self.text:
            self.skipTest("当前不可发布")
        for line in self.text.splitlines():
            if "必须补齐" in line or "必须先修" in line:
                self.assertTrue(
                    "协议路线" in line or "另一条路线" in line,
                    "这行在能发布的输出里说「必须补齐」却没标明是哪条路线的：{!r}".format(line),
                )


if __name__ == "__main__":
    unittest.main()

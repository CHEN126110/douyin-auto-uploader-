# -*- coding: utf-8 -*-
"""`_open_publish_page` 必须**先探健康再动手**。

## 实测（2026-10-03）

`select_category` 报了：

```
[PAGE_ERROR] 页面交互失败：等待 CDP Page.navigate 响应超时
```

**准确，但操作人分不清是「网慢」还是「页面卡死」。** 查下来是后者：

```
目标：https://item.upload.taobao.com/sell/ai/category.htm
  Runtime.evaluate 超时/失败：PageError
  Page.enable 失败：PageError
  导航历史 0 条
```

连 `Page.reload` 都没救回来（同一浏览器里另一个页面 reload 后 `readyState=complete`，
而这个仍然 `PageError`）。

**「连上了」不等于「能用」**——连接走 CDP 通道，命令要 renderer 执行。

不探这一下的话，每个阶段都要各自撞一次 25 秒超时，
最后只留下一句分不清原因的超时消息。
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

from taobao_publish import cdp, stages  # noqa: E402


class HealthProbeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.source = inspect.getsource(stages._open_publish_page)

    def test_it_probes_health_after_connecting(self) -> None:
        connect_at = self.source.index("PageClient.connect(")
        health_at = self.source.index("health_check(")
        self.assertLess(connect_at, health_at, "健康探测必须在连接之后")

    def test_the_probe_runs_before_any_stage_action(self) -> None:
        """⚠️ **在任何写操作之前**——否则每个阶段各自撞一次超时。"""

        health_at = self.source.index("health_check(")
        wait_at = self.source.index("wait_for_publish_form")
        self.assertLess(health_at, wait_at, "健康探测必须早于读表单")

    def test_the_error_says_what_to_do(self) -> None:
        """报错要能指导操作，不能只说「超时」。"""

        self.assertIn("renderer", self.source)
        self.assertIn("刷新", self.source)
        self.assertIn("关掉该标签页重开", self.source)

    def test_the_error_says_login_is_not_lost(self) -> None:
        """让人敢去重建标签页——登录态在 profile 里。"""

        self.assertIn("登录态在 profile 里", self.source)

    def test_a_frozen_page_is_refused(self) -> None:
        """替身：`health_check` 返回 False → 明确失败，且**关掉连接**。"""

        client = mock.MagicMock()
        client.health_check.return_value = False
        target = {"webSocketDebuggerUrl": "ws://x", "url": "https://item.upload.taobao.com/x"}

        ctx = mock.MagicMock()
        ctx.cdp_list_url = ""

        with mock.patch.object(cdp, "list_targets", return_value=[target]), \
                mock.patch.object(cdp, "select_publish_target", return_value=target), \
                mock.patch("taobao_publish.page.PageClient.connect", return_value=client):
            with self.assertRaises(Exception) as context:
                stages._open_publish_page(ctx)

        self.assertIn("renderer", str(context.exception))
        client.close.assert_called_once()

    def test_a_healthy_page_passes_the_probe(self) -> None:
        client = mock.MagicMock()
        client.health_check.return_value = True
        target = {"webSocketDebuggerUrl": "ws://x", "url": "https://item.upload.taobao.com/x"}

        ctx = mock.MagicMock()
        ctx.cdp_list_url = ""

        with mock.patch.object(cdp, "list_targets", return_value=[target]), \
                mock.patch.object(cdp, "select_publish_target", return_value=target), \
                mock.patch("taobao_publish.page.PageClient.connect", return_value=client), \
                mock.patch("taobao_publish.page.wait_for_publish_form", return_value=[]):
            with self.assertRaises(Exception) as context:
                stages._open_publish_page(ctx)

        # 健康这一关过了；是后面「填写页没渲染出任何一行」拦下的
        self.assertIn("填写页", str(context.exception))
        self.assertNotIn("renderer", str(context.exception))


if __name__ == "__main__":
    unittest.main()

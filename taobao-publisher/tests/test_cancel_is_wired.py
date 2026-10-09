# -*- coding: utf-8 -*-
"""取消能力**一直存在，但从来没被调用过**。

## 发现（2026-10-03）

| | `api.ts` | 界面 |
|---|---|---|
| **淘宝** 取消 | **有** `cancelTaobaoPublish` | **没有调用** ← |
| 抖店 取消 | 没有 | 没有 |

**任务一旦跑起来就没法停**，而阶段可以各跑 20 秒（整条链条约 1~2 分钟）。
**「真实发布」模式下这是真实的可用性缺口**——用户看着它一路写下去，没有刹车。

`api.ts` 里那个方法一直是**死代码**。

（顺带：**淘宝侧在这一项上比抖店完整**——抖店连 API 都没有。）

## 实机验证（dry-run 任务，不写平台）

```
启动 → running（10%，step=session）
请求取消 → HTTP 200「已请求取消（阶段边界生效，正在执行的那一步不会被打断）」
最终状态 = **cancelled**
已完成步骤 = 1（共 10）
[OK] 连接调试浏览器        ← 跑完的那一步保留了结果
[?]  其余 9 步            已请求取消，本阶段未执行
```

## 语义要如实

接口原话是「**不中断已经在跑的那一步**——阶段边界才会检查」。
所以界面提示写成「将在**当前阶段结束后**停止」，
**不能写成像「立刻停了」那样**。
"""
from __future__ import annotations

import pathlib
import re
import sys
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SUBPROJECT = REPO_ROOT / "taobao-publisher"
PANEL = REPO_ROOT / "tauri-app" / "src" / "components" / "TaobaoPublishPanel.vue"
API_TS = REPO_ROOT / "tauri-app" / "src" / "services" / "api.ts"
APP = REPO_ROOT / "tauri-app" / "python-sidecar" / "app.py"


def code_only(text: str) -> str:
    """剥掉注释——**本会话被文档字符串骗过多次**。"""

    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("//") or stripped.startswith("*"):
            continue
        lines.append(line)
    return "\n".join(lines)


class CancelIsWiredTest(unittest.TestCase):
    def setUp(self) -> None:
        self.panel = PANEL.read_text(encoding="utf-8")
        self.code = code_only(self.panel)

    def test_the_panel_calls_the_cancel_api(self) -> None:
        """⚠️ **这一条就是本轮发现的缺口。**"""

        self.assertIn("api.cancelTaobaoPublish", self.code)

    def test_there_is_a_button_for_it(self) -> None:
        template = self.panel[self.panel.index("<template>"):]
        self.assertIn("cancelPublish", template, "没有按钮，用户就没法触发")

    def test_the_button_only_shows_while_running(self) -> None:
        """跑完了还显示「取消任务」会让人以为点得动。"""

        source = self.panel
        index = source.index("取消任务")
        window = source[max(0, index - 500):index]
        self.assertIn("publishRunning", window)

    def test_the_cancelling_state_is_separate(self) -> None:
        """取消与启动可以同时为真——共用一个 loading 会互相干扰。"""

        self.assertIn("publishCancelling", self.code)
        self.assertNotIn("publishStarting = true;\n    const response = await api.cancelTaobaoPublish",
                         self.code)

    def test_the_message_says_when_it_takes_effect(self) -> None:
        """**语义如实**：阶段边界才停，不是立刻停。"""

        self.assertIn("当前阶段结束后", self.panel)

    def test_it_does_not_fake_the_task_state(self) -> None:
        """⚠️ 请求取消后**不许**自己把界面状态改成「已取消」——
        那会显示一个后端并不知道的状态。让轮询去读真的。"""

        source = code_only(self.panel)
        index = source.index("async function cancelPublish")
        body = source[index:index + 1200]
        self.assertNotIn("publishTask.value.status", body,
                         "取消后不该自己改任务状态——让轮询读真实的")


class SidecarCancelSemanticsTest(unittest.TestCase):
    def test_the_endpoint_exists(self) -> None:
        self.assertIn("/api/taobao/publish/cancel/<task_id>",
                      APP.read_text(encoding="utf-8"))

    def test_it_says_it_does_not_interrupt_the_running_step(self) -> None:
        source = APP.read_text(encoding="utf-8")
        start = source.index("def taobao_publish_cancel")
        end = source.index("\n@app.", start)
        body = source[start:end]
        self.assertIn("不中断已经在跑的那一步", body)

    def test_cancelling_a_finished_task_is_not_an_error(self) -> None:
        """跑完了再点取消（界面来不及刷新）不该报错。"""

        source = APP.read_text(encoding="utf-8")
        start = source.index("def taobao_publish_cancel")
        end = source.index("\n@app.", start)
        body = source[start:end]
        self.assertIn("任务已结束，无需取消", body)


class ApiMethodExistsTest(unittest.TestCase):
    def test_api_ts_has_it(self) -> None:
        self.assertIn("cancelTaobaoPublish", API_TS.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()

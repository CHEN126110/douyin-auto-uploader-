# -*- coding: utf-8 -*-
"""就绪度的**第三个出口**：Sidecar / 前端那条路。

前两个出口（流水线结果、CLI 面板）在之前两轮修过「把另一条路线的待办
说成本次的阻塞」。这一轮找到第三个，而且它最严重——**它是界面实际用的那个**：

后端 `desktop_readiness()`：

```python
"automatic_publish_ready": False,          # ← 硬编码
"message": "…自动填表、上传、草稿保存和上架尚未实现。",   # ← 全都已实现
```

前端还**主动强制**它陈旧：

```ts
if (... || data.automatic_publish_ready !== false) {
  throw new Error("淘宝路线状态与当前资料准备模式不一致，请检查后端版本");
}
```

**两边一起陈旧**：后端一旦如实报告，界面反而报错。
这些用例把「两边都不许再陈旧」钉住。
"""

from __future__ import annotations

import pathlib
import sys
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SUBPROJECT = REPO_ROOT / "taobao-publisher"
if str(SUBPROJECT) not in sys.path:
    sys.path.insert(0, str(SUBPROJECT))

from frontend_source_helper import code_only  # noqa: E402

from taobao_publish import desktop  # noqa: E402
from taobao_publish.pipeline import describe_readiness  # noqa: E402

TAURI = REPO_ROOT / "tauri-app"
PANEL = TAURI / "src" / "components" / "TaobaoPublishPanel.vue"
MANAGER = TAURI / "src" / "views" / "ProductManager.vue"
TYPES = TAURI / "src" / "types" / "index.ts"





class DesktopReadinessTruthTest(unittest.TestCase):
    def setUp(self) -> None:
        self.payload = desktop.desktop_readiness()
        self.readiness = describe_readiness()

    def test_automatic_publish_ready_is_derived_not_hardcoded(self) -> None:
        self.assertEqual(self.payload["automatic_publish_ready"],
                         bool(self.readiness.publishable),
                         "必须由真实状态推导，不能硬编码")

    def test_mode_reflects_the_pipeline(self) -> None:
        self.assertEqual(self.payload["mode"], "automated_pipeline")

    def test_stage_lists_are_consistent(self) -> None:
        self.assertEqual(self.payload["unimplemented_stages"], [])
        self.assertEqual(self.payload["incomplete_stages"], [])
        self.assertIn("submit", self.payload["live_unverified_stages"],
                      "submit 未实机验证，必须如实列出")

    def test_message_does_not_claim_things_are_unimplemented(self) -> None:
        """消息不许再说「尚未实现」——它们都实现了。"""

        message = self.payload["message"]
        for stale in ("尚未实现", "未启用", "不支持自动"):
            self.assertNotIn(stale, message, "陈旧文案：{!r}".format(stale))
        self.assertIn("提交前截停", message, "要说清止步于哪里")

    def test_two_routes_gates_are_reported_separately(self) -> None:
        """两条路线的门要分开报，并说明字段缺口**不关 DOM 路线**。"""

        self.assertIn("dom_write_ready", self.payload)
        self.assertIn("protocol_write_ready", self.payload)
        self.assertEqual(self.payload["dom_write_ready"], self.readiness.dom_write_ready)
        if self.payload["blocked_fields"]:
            # 断言实际写的那句——第一版查的是「不关」，而实际文案里没有这两个字。
            note = self.payload["blocked_fields_note"]
            self.assertIn("协议路线", note)
            self.assertIn("DOM", note)
        self.assertIn("DOM 路线", self.payload["blocked_selectors_note"])


class FrontendStaleGuardTest(unittest.TestCase):
    """前端不许再**强制**那个陈旧的不变量。"""

    def test_panel_does_not_require_automatic_publish_false(self) -> None:
        code = code_only(PANEL.read_text(encoding="utf-8"))
        self.assertNotIn("automatic_publish_ready !== false", code,
                         "后端已如实报告，前端再要求它为 false 会让界面反过来报错")
        self.assertNotIn('"manual_preparation"', code, "代码里还在期待旧模式名")

    def test_manager_does_not_require_automatic_publish_false(self) -> None:
        code = code_only(MANAGER.read_text(encoding="utf-8"))
        self.assertNotIn("automatic_publish_ready !== false", code)
        self.assertNotIn('"manual_preparation"', code)

    def test_types_declare_the_new_shape(self) -> None:
        source = TYPES.read_text(encoding="utf-8")
        self.assertIn('"automated_pipeline"', source)
        code = code_only(source)
        self.assertNotIn('automatic_publish_ready: false;', code,
                         "类型上写死 false 就等于把陈旧当契约")
        self.assertIn("automatic_publish_ready: boolean;", code)

    def test_no_frontend_file_still_expects_manual_preparation(self) -> None:
        """整棵前端源码树扫一遍——将来别处再写死也会被抓到。"""

        offenders = []
        for path in (TAURI / "src").rglob("*"):
            if not path.is_file() or path.suffix not in (".ts", ".vue"):
                continue
            if "manual_preparation" in path.read_text(encoding="utf-8"):
                offenders.append(path.name)
        self.assertEqual(offenders, [], "这些文件还在期待旧模式：{}".format(offenders))


if __name__ == "__main__":
    unittest.main()

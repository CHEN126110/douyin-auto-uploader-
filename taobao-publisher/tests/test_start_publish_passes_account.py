# -*- coding: utf-8 -*-
"""三个调用里，**只有真正写平台的那个没带账户标识**。

## 实测（2026-10-03）

| 面板里的调用 | 带 `account_profile`？ |
|---|---|
| `checkPreparation` | **带** |
| `buildPayload`（`exportPacket` 用） | **带** |
| **`startPublish`** | **不带** ← |

Sidecar 的 `_require_publish_platform`：

```python
if account_profile is not None:
    if account_profile != account['profile_name']:
        return ... code='ACCOUNT_CHANGED',
               msg='当前账户已改变，请刷新账户后重新检查发布资料'
```

**这个参数存在的理由就是防「准备时是 A、发布时是 B」。**

## 后果

为账户 A 准备了标题/价格/库存/类目，期间切到账户 B，点发布：
Sidecar 只检查「当前是淘宝账户」，**不检查是不是准备时的那个** →
**把为 A 准备的资料发到 B 上**。

面板的 `contextMatches` 是客户端守卫；服务端这道是纵深防御，
**它不该是唯一一道，也不该被完全跳过**。

## 实机（改后）

```
错误账户标识 → HTTP 409, code=ACCOUNT_CHANGED
                「当前账户已改变，请刷新账户后重新检查发布资料」
正确账户标识 → HTTP 200
```

## 同源问题

这与第 66~68 轮那类同源：**守卫存在，但没接上去**。
而且这里是**同一份代码里三处调用用法不一致**——
比「忘了写」更隐蔽，因为旁边两处是对的，看起来像是有意为之。
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

    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("//") or stripped.startswith("*"):
            continue
        lines.append(line)
    return "\n".join(lines)


class StartPublishPassesAccountTest(unittest.TestCase):
    def setUp(self) -> None:
        self.panel = PANEL.read_text(encoding="utf-8")

    def test_start_publish_passes_the_account_profile(self) -> None:
        """⚠️ **这一条就是实测发现的缺口。**"""

        match = re.search(r"api\.startTaobaoPublish\(recordId,\s*\{(.*?)\n\s*\}\);",
                          self.panel, re.S)
        self.assertIsNotNone(match, "找不到 startTaobaoPublish 的调用")
        body = code_only(match.group(1))
        self.assertIn("accountProfile", body,
                      "startPublish 必须带 accountProfile——否则 Sidecar 的一致性校验被完全跳过")

    def test_the_other_two_calls_also_pass_it(self) -> None:
        """三处用法要一致。"""

        code = code_only(self.panel)
        self.assertIn("account_profile: accountProfile", code)

    def test_the_comment_explains_why(self) -> None:
        """注释要写清后果，不能只写「加上它」。"""

        self.assertIn("ACCOUNT_CHANGED", self.panel)
        self.assertIn("发到 B 上", self.panel)


class ApiForwardsItTest(unittest.TestCase):
    def test_api_ts_sends_account_profile_when_given(self) -> None:
        source = API_TS.read_text(encoding="utf-8")
        self.assertIn("account_profile: options.accountProfile", source)

    def test_it_omits_it_when_absent(self) -> None:
        """不给就不发——**不编一个空串**（那会让 Sidecar 报「必须是非空文本」）。"""

        source = API_TS.read_text(encoding="utf-8")
        self.assertIn("options.accountProfile ?", source)


class SidecarEnforcesItTest(unittest.TestCase):
    def test_the_guard_exists(self) -> None:
        source = APP.read_text(encoding="utf-8")
        self.assertIn("ACCOUNT_CHANGED", source)
        self.assertIn("当前账户已改变，请刷新账户后重新检查发布资料", source)

    def test_it_returns_409(self) -> None:
        source = APP.read_text(encoding="utf-8")
        start = source.index("def _require_publish_platform")
        end = source.index("\ndef ", start + 10)
        body = source[start:end]
        self.assertIn("ACCOUNT_CHANGED", body)
        self.assertIn("409", body)

    def test_it_is_optional_but_the_panel_now_always_sends_it(self) -> None:
        """Sidecar 侧「不传就不校验」是有意的（CLI 等调用方可能没有账户概念），
        **但界面必须传**——界面一定有账户。"""

        source = APP.read_text(encoding="utf-8")
        start = source.index("def _require_publish_platform")
        end = source.index("\ndef ", start + 10)
        self.assertIn("if account_profile is not None:", source[start:end])


if __name__ == "__main__":
    unittest.main()

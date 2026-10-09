# -*- coding: utf-8 -*-
"""淘宝运费模板：**后端能读、接口转发、前端会请求** —— 三层缺一不可。

## 用户的原话（会话早期）

> 登录完成之后应该看看呀获取店铺相关的信息 **比如设置的运费模板等**

## 三层缺口（同一件事被挡了三次）

| 层 | 原状态 |
|---|---|
| `src/shop_session.py` | 找 **mtop 协议接口名** → 一直 `not_captured` |
| `app.py` 的接口 | 不复制 `current`（上游给了，界面看不到） |
| `SettingsPanel.vue` | `platform !== "douyin"` → **直接 return，根本不请求** |

**而且形成闭环矛盾**：`stage_fill_freight` 的阻塞项里写着

> 「模板名读不到时应先去 **`/api/shop/freight-templates`** 取」

——流水线让你去用一个对淘宝返回空的接口。

## 实测（2026-10-03，走 HTTP）

```
platform  = taobao
status    = ok
shop_name = 猫咪宝贝袜子铺
templates = ["极兔快递", "系统模板-商家默认模板"]
detail    = 从发布表单的运费模板下拉里读到 2 个模板（DOM 路线）
```

**与 `fill_freight` 报的「该店铺共 2 个模板」完全一致。**
"""

from __future__ import annotations

import pathlib
import sys
import unittest

from tests.frontend_source_helper import code_only

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SUBPROJECT = REPO_ROOT / "taobao-publisher"
if str(SUBPROJECT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

SHOP_SESSION = REPO_ROOT / "src" / "shop_session.py"
APP = REPO_ROOT / "tauri-app" / "python-sidecar" / "app.py"
PANEL = REPO_ROOT / "tauri-app" / "src" / "components" / "SettingsPanel.vue"
TYPES = REPO_ROOT / "tauri-app" / "src" / "types" / "index.ts"


class ShopSessionUsesDomTest(unittest.TestCase):
    """后端必须走 **DOM**，不靠没实证的协议接口名。"""

    def setUp(self) -> None:
        source = SHOP_SESSION.read_text(encoding="utf-8")
        start = source.index("def read_taobao_freight_templates(")
        end = source.index("\ndef ", start + 10)
        self.body = source[start:end]

    def test_uses_the_dom_helpers(self) -> None:
        for name in ("list_targets", "select_publish_target",
                     "open_freight_dropdown", "read_freight_options",
                     "read_freight_template"):
            with self.subTest(helper=name):
                self.assertIn(name, self.body)

    def test_no_longer_returns_not_captured(self) -> None:
        """`not_captured` 是「等协议接口」时代的状态，DOM 路线不该再返回它。"""

        self.assertNotIn('"status": "not_captured"', self.body)

    def test_reports_need_publish_page_instead_of_guessing(self) -> None:
        """不在发布表单上就如实说，**不替调用方导航**（导航有副作用）。"""

        self.assertIn("need_publish_page", self.body)

    def test_empty_options_is_never_ok(self) -> None:
        """⚠️ **空列表绝不等于「该店铺没有模板」。**"""

        self.assertIn("不等于该店铺没有模板", self.body)
        # 空选项必须走 read_failed，不能返回 ok
        marker = "if not options:"
        self.assertIn(marker, self.body)
        tail = self.body[self.body.index(marker):]
        self.assertIn('"status": "read_failed"', tail[:600])

    def test_imports_are_lazy(self) -> None:
        """`src/` 不该在模块导入期就依赖子项目。"""

        self.assertIn("from taobao_publish import", self.body)

    def test_reads_current_before_opening_the_dropdown(self) -> None:
        """下拉是**开关**——先读当前值，再展开，否则可能读到空。

        ⚠️ **必须剥掉注释与文档字符串再判。**
        这个函数的文档里就列着 `read_freight_template` 的名字，
        直接 `index()` 会命中文档那一行——本会话第 9 次踩这个坑。
        """

        code = code_only(self.body)
        current_at = code.index("read_freight_template")
        open_at = code.index("open_freight_dropdown")
        self.assertLess(current_at, open_at, "必须先读当前值再展开下拉")


class EndpointForwardsCurrentTest(unittest.TestCase):
    def test_current_is_in_the_forwarded_payload(self) -> None:
        """上游给了 `current`，接口不转发的话界面永远看不到。"""

        source = APP.read_text(encoding="utf-8")
        start = source.index("def shop_freight_templates()")
        end = source.index("\n@app.", start)
        body = source[start:end]
        self.assertIn("'current'", body)


class FrontendRequestsTaobaoTest(unittest.TestCase):
    """⚠️ 前端原先对淘宝**直接 return**，后端修好也看不到。"""

    def setUp(self) -> None:
        self.source = PANEL.read_text(encoding="utf-8")
        start = self.source.index("async function loadFreightTemplates(")
        end = self.source.index("\n}", start)
        self.body = self.source[start:end]

    def test_taobao_is_not_short_circuited(self) -> None:
        self.assertNotIn('account?.platform !== "douyin")\n', self.body,
                         "淘宝仍被提前 return 挡住")
        self.assertIn('account?.platform !== "taobao"', self.body)

    def test_old_wrong_copy_is_gone(self) -> None:
        """「抖音运费模板需切换到抖音账户后读取」已经不成立。"""

        self.assertNotIn("需切换到抖音账户后读取", self.source)

    def test_distinguishes_not_read_from_no_templates(self) -> None:
        """「没读到」与「没有模板」必须分开说。"""

        self.assertIn("这不等于该店铺没有模板", self.source)
        self.assertIn("need_publish_page", self.source)

    def test_no_hardcoded_douyin_in_the_shared_path(self) -> None:
        self.assertNotIn("抖音运费模板", self.source)


class TypeCoversNewStatusesTest(unittest.TestCase):
    def test_status_union_has_the_dom_route_statuses(self) -> None:
        source = TYPES.read_text(encoding="utf-8")
        start = source.index("export interface ShopFreightTemplates {")
        end = source.index("\n}", start)
        body = source[start:end]
        for status in ("need_publish_page", "read_failed", "unavailable", "not_captured"):
            with self.subTest(status=status):
                self.assertIn('"{}"'.format(status), body)

    def test_current_is_declared(self) -> None:
        source = TYPES.read_text(encoding="utf-8")
        start = source.index("export interface ShopFreightTemplates {")
        end = source.index("\n}", start)
        self.assertIn("current?:", source[start:end])


class PipelineBlockerPointsAtAWorkingEndpointTest(unittest.TestCase):
    """闭环：流水线让人去用的接口，**现在真的能用**。"""

    def test_the_stage_points_at_this_endpoint(self) -> None:
        stages = (SUBPROJECT / "taobao_publish" / "stages.py").read_text(encoding="utf-8")
        self.assertIn("/api/shop/freight-templates", stages,
                      "阶段里的指引必须指向真实存在的接口")

    def test_that_endpoint_exists_in_the_sidecar(self) -> None:
        source = APP.read_text(encoding="utf-8")
        self.assertIn("/api/shop/freight-templates", source)


if __name__ == "__main__":
    unittest.main()

# -*- coding: utf-8 -*-
r"""审计脚本自己的两个缺口——**它报“Tauri 命令 0 个”时我差点信了**。

## 缺口一：抽不到 `async` 方法

```ts
export const tauriCommands = {
  /** 打开文件夹 */
  async openFolder(path: string): Promise<void> {     // ← 抽到的是 "async"
```

正则 `^\s{2}(\w+)\s*[(:]` 把 `async` 当成了方法名，
于是 Tauri 命令**一个都没抽到**，报告写着「Tauri 命令 0 个」。

**一个报「0 个」的检查器，看起来像「一切正常」。** 这是本轮修的第一件事。

## 缺口二：只查了一个方向

只查了「前端 → 后端」，**没查反方向**：
Sidecar 的路由里，哪些前端从没调过？

第 68 轮的淘宝运费模板就是这一类——**接口在、能力在，但界面够不着**。

## 补上之后的结论（2026-10-03）

```
api.ts：48 个 api 方法、2 个 Tauri 命令

--- 前端 → 后端：与发布/淘宝/账户有关、且没人调用 ---
    （无）

反方向：Sidecar 的淘宝/店铺路由，前端调过吗？
    [有] /api/shop/add          [有] /api/shop/current
    [有] /api/shop/freight-templates …
    [有] /api/taobao/publish/{start,status,cancel,tasks,prepare,export}
    [有] /api/taobao/readiness
```

**13 条路由全部接上，两个方向都干净。**
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SUBPROJECT = REPO_ROOT / "taobao-publisher"
if str(SUBPROJECT) not in sys.path:
    sys.path.insert(0, str(SUBPROJECT))

SCRIPT = SUBPROJECT / "scripts" / "audit-unwired-capabilities.py"
spec = importlib.util.spec_from_file_location("unwired_audit", SCRIPT)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)

API_TS = REPO_ROOT / "tauri-app" / "src" / "services" / "api.ts"
APP = REPO_ROOT / "tauri-app" / "python-sidecar" / "app.py"


class ExtractorTest(unittest.TestCase):
    """⚠️ **`async` 不是方法名。**"""

    def test_it_reads_async_methods(self) -> None:
        block = """
export const tauriCommands = {
  /** 打开文件夹 */
  async openFolder(path: string): Promise<void> {
  },

  async getAppInfo(): Promise<{
  },
};
"""
        names = audit.extract_members(block)
        self.assertIn("openFolder", names, "`async` 前缀不能被当成方法名")
        self.assertIn("getAppInfo", names)

    def test_it_does_not_return_async_as_a_name(self) -> None:
        block = "  async openFolder(): void {\n  },\n"
        self.assertNotIn("async", audit.extract_members(block))

    def test_it_reads_plain_methods(self) -> None:
        block = "  getTaobaoReadiness(): Promise<X> {\n  },\n"
        self.assertIn("getTaobaoReadiness", audit.extract_members(block))

    def test_it_reads_property_style(self) -> None:
        block = "  baseURL: string,\n"
        self.assertIn("baseURL", audit.extract_members(block))


class RealTreeTest(unittest.TestCase):
    """对**真实文件**跑一遍——数字要对得上。"""

    def test_tauri_commands_are_found(self) -> None:
        source = API_TS.read_text(encoding="utf-8")
        start = source.index("{", source.index("export const tauriCommands"))
        block = audit.brace_block(source, start)
        names = audit.extract_members(block)
        self.assertGreaterEqual(len(names), 2,
                                "至少要抽到 openFolder 与 getAppInfo——"
                                "报「0 个」的检查器看起来像「一切正常」")
        self.assertIn("openFolder", names)

    def test_api_methods_are_found(self) -> None:
        source = API_TS.read_text(encoding="utf-8")
        start = source.index("{", source.index("export const api"))
        block = audit.brace_block(source, start)
        names = audit.extract_members(block)
        self.assertGreater(len(names), 30, "api 方法应当有几十个")
        self.assertIn("startTaobaoPublish", names)

    def test_brace_block_is_balanced(self) -> None:
        block = audit.brace_block("a { b { c } d } e", 2)
        self.assertEqual(block, "{ b { c } d }")


class TaobaoSurfaceIsWiredTest(unittest.TestCase):
    """⚠️ **反方向**：Sidecar 的淘宝/店铺路由，前端都调过吗？"""

    def test_every_taobao_and_shop_route_is_reachable_from_the_frontend(self) -> None:
        import re

        app_source = APP.read_text(encoding="utf-8")
        routes = sorted(set(
            m.group(1) for m in re.finditer(
                r"@app\.(?:route|get|post)\('(/api/(?:taobao|shop)[^']*)'", app_source)))

        self.assertGreaterEqual(len(routes), 10, "淘宝/店铺路由应当有十几条")

        corpus = "\n".join(
            path.read_text(encoding="utf-8", errors="ignore")
            for path in (REPO_ROOT / "tauri-app" / "src").rglob("*")
            if path.is_file() and path.suffix in (".ts", ".vue")
            and "node_modules" not in path.parts)

        unreachable = []
        for route in routes:
            stem = re.sub(r"<[^>]+>", "", route).rstrip("/")
            if stem and stem not in corpus:
                unreachable.append(route)

        self.assertEqual(unreachable, [],
                         "这些淘宝/店铺路由前端够不着（第 68 轮的运费模板就是这一类）：\n  "
                         + "\n  ".join(unreachable))


if __name__ == "__main__":
    unittest.main()

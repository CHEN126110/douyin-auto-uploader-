# -*- coding: utf-8 -*-
"""补齐审计的**两个缺口**，并做**反方向**的检查。

## 缺口一：`tauriCommands` 一个都没抽到

上一版报「Tauri 命令 0 个」——**不是真没有**，是我的正则把 `async` 当成了方法名：

```ts
export const tauriCommands = {
  /** 打开文件夹 */
  async openFolder(path: string): Promise<void> {     // ← 抽到的是 "async"
```

## 缺口二：只查了「前端 → 后端」

**反过来也该查**：Sidecar 的路由里，哪些前端从没调过？

第 68 轮的淘宝运费模板就是这一类——**接口在、能力在，但界面够不着**。

## 判据（保守）

「没被调用」**不等于**「该接」——有些是给 CLI / MCP / 外部用的。
所以这份报告是**清单，不是结论**。

特别地：`/api/taobao/*` 与 `/api/shop/*` 里**给界面用的**那些才要接；
CLI 与 MCP 用的不算。
"""

from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]
SRC = REPO / "tauri-app" / "src"
API_TS = SRC / "services" / "api.ts"
APP = REPO / "tauri-app" / "python-sidecar" / "app.py"

#: 定义体里会出现的普通单词，别当成方法名。
NOT_NAMES = {"async", "if", "return", "const", "let", "export", "import",
             "get", "post", "await", "new", "try", "catch", "finally", "else"}


def extract_members(block: str) -> set:
    """从对象字面量里抽方法名。**要能吃下 `async name(`。"""

    names = set()
    for match in re.finditer(r"^\s{2}(?:async\s+)?(\w+)\s*[(:]", block, re.M):
        name = match.group(1)
        if name not in NOT_NAMES:
            names.add(name)
    return names


def brace_block(source: str, start: int) -> str:
    """从 `start` 处的 `{` 起，取配平的整块。"""

    depth = 0
    for index in range(start, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[start:index + 1]
    return source[start:]


def read_corpus():
    corpus = {}
    for path in SRC.rglob("*"):
        if not path.is_file() or path.suffix not in (".ts", ".vue"):
            continue
        if "node_modules" in path.parts:
            continue
        if path.resolve() == API_TS.resolve():
            continue
        corpus[path.relative_to(SRC)] = path.read_text(encoding="utf-8", errors="ignore")
    return corpus


def used_by(name: str, corpus) -> bool:
    pattern = re.compile(r"\b" + re.escape(name) + r"\b")
    return any(pattern.search(text) for text in corpus.values())


api_source = API_TS.read_text(encoding="utf-8")
corpus = read_corpus()

print("=" * 78)
print("没人用的能力：两个方向")
print("=" * 78)

# --- 前端 → 后端 -------------------------------------------------------------
api_block = brace_block(api_source, api_source.index("export const api"))
api_methods = extract_members(api_block)

tauri_at = api_source.find("export const tauriCommands")
tauri_block = brace_block(api_source, api_source.index("{", tauri_at))
tauri_methods = extract_members(tauri_block)

print()
print("  api.ts：{} 个 api 方法、{} 个 Tauri 命令".format(
    len(api_methods), len(tauri_methods)))

KEYWORDS = ("taobao", "publish", "shop", "cancel", "packet", "prepare",
            "upload", "readiness", "folder", "appinfo", "backend")


def relevant(names):
    return sorted(n for n in names
                  if any(k in n.lower() for k in KEYWORDS))


unused_api = [n for n in sorted(api_methods) if not used_by(n, corpus)]
unused_tauri = [n for n in sorted(tauri_methods) if not used_by(n, corpus)]

print()
print("  --- 前端 → 后端：与发布/淘宝/账户有关、且没人调用 ---")
hits = relevant(unused_api) + relevant(unused_tauri)
for name in hits:
    print("      {}".format(name))
if not hits:
    print("      （无）")

print()
print("  --- 其余没人调用的 api 方法（供人工判断）---")
for name in unused_api:
    if name in hits:
        continue
    print("      {}".format(name))

# --- 后端 → 前端（反方向）---------------------------------------------------
print()
print("=" * 78)
print("反方向：Sidecar 的淘宝/店铺路由，前端调过吗？")
print("=" * 78)

app_source = APP.read_text(encoding="utf-8")
routes = []
for match in re.finditer(r"@app\.(?:route|get|post)\('(/api/(?:taobao|shop)[^']*)'",
                         app_source):
    routes.append(match.group(1))

frontend_text = "\n".join(corpus.values()) + api_source

print()
for route in sorted(set(routes)):
    # 把 `<task_id>` 这类占位符换成通配，做前缀匹配
    stem = re.sub(r"<[^>]+>", "", route).rstrip("/")
    called = stem and stem in frontend_text
    print("  {} {:<52} {}".format("[有]  " if called else "[没有]", route,
                                  "" if called else "← 前端没调"))

print()
print("=" * 78)
print("**这是清单，不是结论。** 有些路由是给 CLI / MCP / 外部用的，不算缺口。")

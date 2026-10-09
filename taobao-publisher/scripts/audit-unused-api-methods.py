# -*- coding: utf-8 -*-
"""系统化：**`api.ts` 里哪些方法与 Tauri 命令从来没被调用过？**

## 为什么

第 79、80 两轮都靠同一条线索找到真问题：

| 轮次 | 发现 | 后果 |
|---|---|---|
| 79 | `account_profile` 没传给启动接口 | **可能把为 A 准备的资料发到 B** |
| 80 | `cancelTaobaoPublish` 有、界面没调 | **任务没有刹车** |

**两次都不是功能缺失，而是「已经写好的东西没人用」。**

## 判据（保守）

「没被调用」**不等于**「该接」——有些方法给别处用、或本就该留着。
所以这份报告是**清单，不是结论**，每条要人工看。

排除：`api.ts` 自己的定义、注释、以及同一个文件内的转发。
"""

from __future__ import annotations

import pathlib
import re
import sys

SRC = pathlib.Path(__file__).resolve().parents[2] / "tauri-app" / "src"
API_TS = SRC / "services" / "api.ts"

#: 不参与判定的目录/文件。
SKIP_PARTS = ("node_modules",)

source = API_TS.read_text(encoding="utf-8")

# --- 1) 抽出 api.ts 里定义的方法名 ------------------------------------------
#    形态：`  name(...): Promise<...> {` 或 `  name: {`
methods = set()
for match in re.finditer(r"^\s{2}(\w+)\s*[(:]", source, re.M):
    name = match.group(1)
    if name in ("if", "return", "const", "let", "export", "import", "get", "post"):
        continue
    methods.add(name)

# --- 2) 抽出 Tauri 命令 ------------------------------------------------------
tauri_names = set()
block = re.search(r"tauriCommands\s*=\s*\{(.*?)\n\};", source, re.S)
if block:
    tauri_names = set(re.findall(r"^\s{2}(\w+)\s*[(:]", block.group(1), re.M))

print("=" * 78)
print("`api.ts` 的方法 / Tauri 命令：哪些从来没被调用过")
print("=" * 78)
print()
print("  api.ts 里定义的方法 {} 个，Tauri 命令 {} 个".format(len(methods), len(tauri_names)))
print()

# --- 3) 统计调用面 ------------------------------------------------------------
others = []
for path in SRC.rglob("*"):
    if not path.is_file() or path.suffix not in (".ts", ".vue"):
        continue
    if any(part in SKIP_PARTS for part in path.parts):
        continue
    if path.resolve() == API_TS.resolve():
        continue
    others.append(path)

corpus = {}
for path in others:
    corpus[path] = path.read_text(encoding="utf-8", errors="ignore")


def used_by(name: str):
    hits = []
    pattern = re.compile(r"\b" + re.escape(name) + r"\b")
    for path, text in corpus.items():
        if pattern.search(text):
            hits.append(path.relative_to(SRC))
    return hits


unused_api, unused_tauri = [], []
for name in sorted(methods):
    if not used_by(name):
        unused_api.append(name)
for name in sorted(tauri_names):
    if not used_by(name):
        unused_tauri.append(name)


def tauri_related(names):
    """只报与淘宝/发布/账户有关的——那些才可能影响 objective。"""
    keywords = ("taobao", "publish", "shop", "cancel", "packet", "prepare",
                "upload", "readiness")
    return [n for n in names if any(k in n.lower() for k in keywords)]


print("  --- 与发布/淘宝/账户有关、且没人调用的 api 方法 ---")
related_api = tauri_related(unused_api)
for name in related_api:
    print("      {}".format(name))
if not related_api:
    print("      （无）")

print()
print("  --- 与发布/淘宝/账户有关、且没人调用的 Tauri 命令 ---")
related_tauri = tauri_related(unused_tauri)
for name in related_tauri:
    print("      {}".format(name))
if not related_tauri:
    print("      （无）")

print()
print("  --- 其余没人调用的 api 方法（可能本就不该接，供人工判断）---")
for name in unused_api:
    if name in related_api:
        continue
    print("      {}".format(name))

print()
print("=" * 78)
print("**这是清单，不是结论。**「没被调用」不等于「该接」——")
print("有些方法给别处用、或本就该留着。每条要人工看。")

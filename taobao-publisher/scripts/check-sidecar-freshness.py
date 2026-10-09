# -*- coding: utf-8 -*-
"""检查**冻结的 Sidecar 是不是比它打包的源码旧**。

## 为什么

2026-10-03 实测：

```
python-backend.exe   17:52:36   （冻结时间）
taobao_publish/page.py 20:03:45  （源码修改时间）
```

**运行中的 Sidecar 带着约两小时的陈旧代码**——包括第 56–59 轮的全部修复
（`fill_props` 能填属性、上传不再死锁、阶段交接等待）。

表现是 `/api/taobao/readiness` 返回**第 42 轮就已改掉**的值
（`mode: manual_preparation`、`automatic_publish_ready: False`）。
**界面因此跑着一个"填不了属性、传不了图"的版本，而没有任何东西发现。**

## 判据：**按内容哈希**，不按 mtime

实测源码的 mtime 会自己往前跑而内容不变（`stages.py` 20:24、20:31 各一次，
哈希不变）。按 mtime 判会**误报陈旧**，而误报的检查器迟早被忽略。

构建时 `build_sidecar.py` 写下 `.source-manifest.json`；检查器重算哈希比对。

## 定位：**人工在交付前跑的检查，不是门**

做成门的话，「开发中源码比产物新」也会被判红——**那是常态，不是问题**。
所以它是脚本：要发版、要交给用户之前跑一次。

## 为什么这个检查值得有

它不是"代码错了"，是**产物与源码脱节**——同一类问题还有：

* exe 打包了旧的 `contracts/*.json`；
* `src-tauri/sidecar/` 里混进了杂物（已有 `verify_output_dir()` 管）。

**改完 Python 不重建 exe，一切看起来都正常。**

用法::

    python taobao-publisher/scripts/check-sidecar-freshness.py
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys
from datetime import datetime

SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
SUBPROJECT = SCRIPT_DIR.parent
REPO_ROOT = SUBPROJECT.parent

EXE = REPO_ROOT / "tauri-app" / "src-tauri" / "sidecar" / "python-backend.exe"

#: 会被打进 sidecar 的源码/契约（改了它们就该重建）。
WATCHED = (
    SUBPROJECT / "taobao_publish",
    SUBPROJECT / "contracts",
    REPO_ROOT / "tauri-app" / "python-sidecar" / "app.py",
    REPO_ROOT / "src",
)

SKIP_SUFFIXES = (".pyc",)
SKIP_DIRS = {"__pycache__", ".pytest_cache", "tmp"}


def newest_mtime(paths) -> tuple[float, str]:
    newest, where = 0.0, ""
    for root in paths:
        if not root.exists():
            continue
        candidates = [root] if root.is_file() else [
            p for p in root.rglob("*")
            if p.is_file()
            and p.suffix not in SKIP_SUFFIXES
            and not any(part in SKIP_DIRS for part in p.parts)
        ]
        for path in candidates:
            stamp = path.stat().st_mtime
            if stamp > newest:
                newest = stamp
                # **仓库外的路径也要能报**：`relative_to` 对它们会抛 ValueError
                # （合成测试暴露的——原先只测了仓库内的路径）。
                try:
                    where = str(path.relative_to(REPO_ROOT))
                except ValueError:
                    where = str(path)
    return newest, where



#: 构建时写下的源码清单（`build_sidecar.py` 的 `write_source_manifest()`）。
MANIFEST = REPO_ROOT / "tauri-app" / "python-sidecar" / ".source-manifest.json"

#: 前端：源码 → `dist/`。改了 `.vue` 不跑 `npm run build`，**界面看到的还是旧前端**。
FRONTEND_SRC = REPO_ROOT / "tauri-app" / "src"
FRONTEND_DIST = REPO_ROOT / "tauri-app" / "dist"


def check_frontend() -> tuple:
    """``(verdict, source_time, dist_time, where)``。

    `dist/` 是生成物、每次构建都会重写，所以 **mtime 判据在这里够用**
    （不像 Sidecar 那样需要内容哈希——那里的 mtime 会自己乱跑而内容不变）。
    """

    source_time, where = newest_mtime([FRONTEND_SRC])
    dist_time, _ = newest_mtime([FRONTEND_DIST])
    if not FRONTEND_DIST.is_dir():
        return "no-dist", source_time, 0.0, where
    if source_time > dist_time:
        return "stale", source_time, dist_time, where
    return "fresh", source_time, dist_time, where


def load_manifest():
    """读构建清单；没有就返回 ``None``。"""

    import json

    if not MANIFEST.is_file():
        return None
    try:
        return json.loads(MANIFEST.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def hash_watched() -> dict:
    """重算被看守文件的内容哈希。"""

    import hashlib

    entries = {}
    for root in WATCHED:
        if not root.exists():
            continue
        paths = [root] if root.is_file() else sorted(root.rglob("*"))
        for path in paths:
            if not path.is_file() or path.suffix in SKIP_SUFFIXES:
                continue
            if any(part in SKIP_DIRS for part in path.parts):
                continue
            try:
                entries[str(path.relative_to(REPO_ROOT))] = hashlib.sha256(
                    path.read_bytes()).hexdigest()
            except OSError:
                continue
    return entries


def compare_with_manifest() -> tuple:
    """``(verdict, changed, removed, added, built_at)``。

    ``verdict`` 取 ``'fresh'`` / ``'stale'`` / ``'no-manifest'``。
    """

    manifest = load_manifest()
    if manifest is None:
        return "no-manifest", [], [], [], ""
    recorded = manifest.get("files") or {}
    current = hash_watched()
    changed = sorted(k for k in recorded if k in current and current[k] != recorded[k])
    removed = sorted(k for k in recorded if k not in current)
    added = sorted(k for k in current if k not in recorded)
    verdict = "fresh" if not (changed or removed or added) else "stale"
    return verdict, changed, removed, added, str(manifest.get("built_at") or "")



def check_frontend_and_report() -> int:
    """查前端 dist/ 是否比 src/ 旧。返回退出码。

    与 Sidecar 那个坑同类：改了 .vue 不跑 
pm run build，
    **界面看到的还是旧前端**——而没有任何东西会报错。
    """

    verdict, source_time, dist_time, where = check_frontend()
    stamp = lambda t: (datetime.fromtimestamp(t).strftime("%Y-%m-%d %H:%M:%S")
                       if t else "—")
    print()
    print("  ---- 前端 ----")
    if verdict == "no-dist":
        print("  没有 dist/（没构建过前端）——界面用的是 Tauri 打包时的旧产物")
        print("  构建：cd tauri-app && npm run build")
        return 1
    print("  dist 最新：  {}".format(stamp(dist_time)))
    print("  源码最新：  {}  {}".format(stamp(source_time), where))
    if verdict == "stale":
        print()
        print("  [陈旧] 前端源码比 dist 新 {} 分钟——**界面看到的是旧前端**".format(
            int((source_time - dist_time) // 60)))
        print("  构建：cd tauri-app && npm run build（然后刷新界面）")
        return 1
    print("  [新鲜] dist 不早于前端源码")
    return 0

def main() -> int:
    print("=" * 74)
    print("Sidecar 产物新鲜度检查")
    print("=" * 74)

    if not EXE.is_file():
        print("找不到 {}——还没构建过，跳过。".format(EXE.relative_to(REPO_ROOT)))
        return 0

    exe_time = EXE.stat().st_mtime
    source_time, source_where = newest_mtime(WATCHED)

    print("  冻结产物：{}  {}".format(
        EXE.relative_to(REPO_ROOT),
        datetime.fromtimestamp(exe_time).strftime("%Y-%m-%d %H:%M:%S")))

    # ⚠️ **先按内容哈希判**：mtime 会自己往前跑而内容不变，按它判会误报。
    verdict, changed, removed, added, built_at = compare_with_manifest()

    if verdict == "fresh":
        print("  源码内容：与构建清单一致（构建于 {}）".format(built_at or "未知"))
        print("  最新 mtime：{}  {}".format(
            datetime.fromtimestamp(source_time).strftime("%Y-%m-%d %H:%M:%S"),
            source_where))
        print()
        print("  [新鲜] 内容哈希与构建时一致")
        print("         ⚠️ **按 mtime 会误报**：实测源码的 mtime 会自己往前跑而内容不变。")
        return check_frontend_and_report()

    if verdict == "stale":
        print("  源码内容：**与构建清单不一致**（构建于 {}）".format(built_at or "未知"))
        print()
        for label, items in (("改了", changed), ("没了", removed), ("多了", added)):
            for name in items[:6]:
                print("    [{}] {}".format(label, name))
            if len(items) > 6:
                print("    [{}] …另有 {} 个".format(label, len(items) - 6))
        print()
        print("  [陈旧] 打包的源码与当前源码不一致")
        print()
        print("  重建：cd tauri-app/python-sidecar && python build_sidecar.py")
        return 1

    print("  最新源码：{}  {}".format(
        datetime.fromtimestamp(source_time).strftime("%Y-%m-%d %H:%M:%S"), source_where))
    print()
    print("  ⚠️ 没有构建清单（{}）——退回 mtime 判据，**可能误报**。".format(
        MANIFEST.name))
    print("     下次 `python build_sidecar.py` 会写下清单。")
    print()

    if source_time > exe_time:
        delta = source_time - exe_time
        print("  [陈旧] 源码比产物新 {} 分钟".format(int(delta // 60)))
        print()
        print("  改完 Python 不重建 exe，**一切看起来都正常**——")
        print("  但运行中的 Sidecar 用的是旧代码（实测：陈旧两小时，")
        print("  `/api/taobao/readiness` 返回第 42 轮就已改掉的值）。")
        print()
        print("  重建：cd tauri-app/python-sidecar && python build_sidecar.py")
        return 1

    print("  [新鲜] 产物不早于它所打包的源码")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

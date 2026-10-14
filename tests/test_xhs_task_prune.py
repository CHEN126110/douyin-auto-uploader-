# -*- coding: utf-8 -*-
"""小红书批量任务记录的清理上限（计划 3.3）。

为什么需要它：`_xhs_tasks` 是 sidecar 进程内的字典，批量填表每次都会新增一条 ✗ ——
不清理就随使用一直积累 ✓。这里钉住三条边界：

1. 超过 TTL 的**已结束**任务被清掉；
2. 只保留最近 N 条已结束任务（最新的一定在、最早的一定被丢）；
3. **运行中/待处理**的任务绝不被清；时间戳损坏的也保留（读不到就不猜 ✗）。

按本仓库约定，用 `ast` 只抽取被测函数与常量，**不导入整个 sidecar** ✓。
被测函数按模块全局名读取任务字典，因此测试把字典注入到**它的**命名空间 ✓。
"""
from __future__ import annotations

import ast
import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
APP_PATH = REPO / "tauri-app" / "python-sidecar" / "app.py"

FUNCTION = "_prune_xhs_tasks_locked"
CONSTANTS = ("XHS_TASK_KEEP_FINISHED", "XHS_TASK_FINISHED_TTL_HOURS")


def _load_namespace() -> dict:
    """抽取被测函数与常量，返回可用的命名空间（含注入用的 _xhs_tasks）。"""
    tree = ast.parse(APP_PATH.read_text(encoding="utf-8"))
    nodes = [
        node for node in tree.body
        if (isinstance(node, ast.FunctionDef) and node.name == FUNCTION)
        or (isinstance(node, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id in CONSTANTS for t in node.targets))
    ]
    assert any(isinstance(n, ast.FunctionDef) and n.name == FUNCTION for n in nodes), \
        "app.py 里找不到 " + FUNCTION
    # app.py 用的是 `from datetime import datetime`（**类**，不是模块 ✗）——
    # 注入错形状会在 datetime.now() 处报 AttributeError（实测踩过 ✓）。
    namespace: dict = {"datetime": datetime.datetime, "_xhs_tasks": {}}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(APP_PATH), "exec"), namespace)
    for name in CONSTANTS:
        assert name in namespace, "常量缺失：" + name
    return namespace


def _task(task_id: str, status: str, *, minutes_ago: float = 0.0) -> dict:
    stamp = (datetime.datetime.now() - datetime.timedelta(minutes=minutes_ago)).isoformat()
    return {
        "task_id": task_id,
        "status": status,
        "created_at": stamp,
        "finished_at": stamp if status in ("succeeded", "failed", "cancelled") else None,
    }


def test_prune_drops_expired_and_never_touches_unfinished():
    namespace = _load_namespace()
    tasks = {
        "old": _task("old", "succeeded", minutes_ago=25 * 60),   # 超 24h → 应删
        "fresh": _task("fresh", "succeeded", minutes_ago=1),     # 近期 → 应留
        "running": _task("running", "running"),                  # 运行中 → 必须留
        "pending": _task("pending", "pending"),                  # 待处理 → 必须留
        "broken": {"task_id": "broken", "status": "failed",
                   "created_at": "不是时间", "finished_at": "也不是"},  # 读不到时间 → 留
    }
    namespace["_xhs_tasks"] = tasks
    removed = namespace[FUNCTION]()

    assert removed == 1
    assert "old" not in tasks
    assert "fresh" in tasks
    assert "running" in tasks and "pending" in tasks
    assert "broken" in tasks, "时间戳读不到时必须保留，不能猜 ✗"


def test_prune_keeps_only_latest_finished_within_cap():
    namespace = _load_namespace()
    keep = namespace["XHS_TASK_KEEP_FINISHED"]
    assert keep >= 1
    tasks = {"old": _task("old", "succeeded", minutes_ago=25 * 60)}
    total = keep + 10
    for index in range(total):
        tasks["r%02d" % index] = _task("r%02d" % index, "succeeded",
                                       minutes_ago=total - index)
    tasks["running"] = _task("running", "running")
    namespace["_xhs_tasks"] = tasks

    namespace[FUNCTION]()

    finished = [t for t in tasks.values()
                if t["status"] in ("succeeded", "failed", "cancelled")]
    assert len(finished) == keep, "应恰好保留 %d 条已结束任务，实际 %d" % (keep, len(finished))
    assert "r%02d" % (total - 1) in tasks, "最新的必须保留"
    assert "r00" not in tasks, "最早的必须被清掉"
    assert "running" in tasks

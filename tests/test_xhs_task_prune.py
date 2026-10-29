# -*- coding: utf-8 -*-
"""小红书批量任务记录的清理上限（计划 3.3）。

为什么需要它：任务字典是 sidecar 进程内的字典，批量填表每次都会新增一条 ✗ ——
不清理就随使用一直积累 ✓。这里钉住三条边界：

1. 超过 TTL 的**已结束**任务被清掉；
2. 只保留最近 N 条已结束任务（最新的一定在、最早的一定被丢）；
3. **运行中/待处理**的任务绝不被清；时间戳损坏的也保留（读不到就不猜 ✗）。

2026-10-20 起任务字典和清理函数属于 ``XhsBatchService``（原先是 ``app.py`` 的模块全局，本测试靠 ``ast`` 抽取）：
现在直接构造服务对象，不需要浏览器、数据库，也不导入整个 sidecar ✓。
"""
from __future__ import annotations

import datetime
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from src.sidecar import xhs_batch_service  # noqa: E402
from src.sidecar.xhs_batch_service import XhsBatchService  # noqa: E402


def _service() -> XhsBatchService:
    # 清理只读写任务字典，其余依赖（商品表、图片、端口段）用不到
    return XhsBatchService(record_model=None, get_pic_list=None, shop_session=None,
                           host="127.0.0.1", port_start=9500, port_end=9599)


def _task(task_id: str, status: str, *, minutes_ago: float = 0.0) -> dict:
    stamp = (datetime.datetime.now() - datetime.timedelta(minutes=minutes_ago)).isoformat()
    return {
        "task_id": task_id,
        "status": status,
        "created_at": stamp,
        "finished_at": stamp if status in ("succeeded", "failed", "cancelled") else None,
    }


def test_prune_drops_expired_and_never_touches_unfinished():
    service = _service()
    tasks = service.tasks
    tasks.update({
        "old": _task("old", "succeeded", minutes_ago=25 * 60),   # 超 24h → 应删
        "fresh": _task("fresh", "succeeded", minutes_ago=1),     # 近期 → 应留
        "running": _task("running", "running"),                  # 运行中 → 必须留
        "pending": _task("pending", "pending"),                  # 待处理 → 必须留
        "broken": {"task_id": "broken", "status": "failed",
                   "created_at": "不是时间", "finished_at": "也不是"},  # 读不到时间 → 留
    })
    removed = service.prune_finished_locked()

    assert removed == 1
    assert "old" not in tasks
    assert "fresh" in tasks
    assert "running" in tasks and "pending" in tasks
    assert "broken" in tasks, "时间戳读不到时必须保留，不能猜 ✗"


def test_prune_keeps_only_latest_finished_within_cap():
    service = _service()
    keep = xhs_batch_service.XHS_TASK_KEEP_FINISHED
    assert keep >= 1
    tasks = service.tasks
    tasks["old"] = _task("old", "succeeded", minutes_ago=25 * 60)
    total = keep + 10
    for index in range(total):
        tasks["r%02d" % index] = _task("r%02d" % index, "succeeded", minutes_ago=total - index)
    tasks["running"] = _task("running", "running")

    service.prune_finished_locked()

    finished = [t for t in tasks.values() if t["status"] in ("succeeded", "failed", "cancelled")]
    assert len(finished) == keep, "应恰好保留 %d 条已结束任务，实际 %d" % (keep, len(finished))
    assert "r%02d" % (total - 1) in tasks, "最新的必须保留"
    assert "r00" not in tasks, "最早的必须被清掉"
    assert "running" in tasks

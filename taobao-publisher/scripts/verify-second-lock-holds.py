# -*- coding: utf-8 -*-
"""补锁的真值表上缺的那一格。

## 已有的那格（第 61 轮）

白名单**不含** `submit_publish` → `precheck` 就拦下（`SUBMIT_NOT_AUTHORIZED`，
14ms，页面一次没碰）。

## 缺的那格（本轮）

白名单**含** `submit_publish`，但 `TAOBAO_UPLOAD_ALLOW_SUBMIT` **未设**。

**两把锁必须各自独立生效**，所以这一格要验两件事：

1. **仍然被拦下**（`SUBMIT_NOT_AUTHORIZED`）——而不是被放行；
2. 拒绝理由是**第二把锁**（提交锁），不是第一把——若两处都对就对得上，
   代码里那两处 `require()` 是同一个入口，所以「理由」表现为
   `detail` 里点名 `TAOBAO_UPLOAD_ALLOW_SUBMIT`。

**为什么安全**：提交锁没开，`require("submit_publish")` 必抛，
处理器根本不会被执行——**一次点击都不会发生**。

## 顺带

跑之前先**直接问授权对象**，把两把锁的状态打出来，
免得只看流水线结果、看不出是哪一把拦的。
"""

from __future__ import annotations

import json
import pathlib
import sys
import time
import urllib.error
import urllib.request

SUB = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(SUB))
sys.path.insert(0, str(SUB.parent))

SIDECAR = "http://127.0.0.1:5001"
CATEGORY = ("女士内衣/男士内衣/家居服",
            "短袜/打底袜/丝袜/美腿袜（新）",
            "一次性袜子")


def post(path, payload, timeout=30.0):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        SIDECAR + path, data=body, method="POST",
        headers={"Content-Type": "application/json; charset=utf-8"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def get(path, timeout=30.0):
    with urllib.request.urlopen(SIDECAR + path, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    print("=" * 78)
    print("锁的真值表：补「白名单含 submit_publish、但提交锁未开」这一格")
    print("=" * 78)
    print()

    # --- 先看 Sidecar 侧两把锁的实际状态 ---
    print("--- Sidecar 的授权状态 ---")
    try:
        readiness = (get("/api/taobao/readiness").get("data") or {})
        print("  readiness.mode =", readiness.get("mode"))
    except Exception as exc:  # noqa: BLE001
        print("  读就绪度失败：{}".format(type(exc).__name__))
        return 1

    # 问一次「提交需要什么」——用 readiness 里带的说明（若有）
    for key in ("submit_requires", "authorization", "write_operations"):
        if key in readiness:
            print("  {} = {}".format(key, json.dumps(readiness[key], ensure_ascii=False)[:160]))

    print()
    print("  预期：白名单含 submit_publish，但 TAOBAO_UPLOAD_ALLOW_SUBMIT 未设")
    print("        → require('submit_publish') 必抛 SUBMIT_NOT_AUTHORIZED")
    print()

    # --- 发任务：允许走到提交 ---
    payload = {
        "record_id": 1,
        "platform": "taobao",
        "account_profile": "taobao-19d2c8e3",
        "dry_run": False,
        # ⚠️ **允许走到提交** —— 这一步就是用来验第二把锁的。
        "stop_before_submit": False,
        "product": {
            "title": "第二把锁验证DSH001",
            "guide_title": "导购锁验证",
            "category_path": ">".join(CATEGORY),
            "freight_template_name": "极兔快递",
            "props": [{"prop_name": "品牌", "value_name": "无品牌/无注册商标"}],
            "skus": [{"spec_values": {"尺码": "M(37-41)"}, "price": 16.8, "stock": 200}],
        },
    }

    try:
        started = post("/api/taobao/publish/start", payload)
    except urllib.error.HTTPError as exc:
        print("启动失败 HTTP {}：{}".format(exc.code, exc.read().decode("utf-8")[:200]))
        return 1

    task_id = (started.get("data") or {}).get("task_id")
    if not task_id:
        print("没拿到 task_id：", json.dumps(started, ensure_ascii=False)[:200])
        return 1
    print("  task_id =", task_id)
    print()

    task = {}
    deadline = time.time() + 1800
    last = None
    while time.time() < deadline:
        time.sleep(10)
        task = (get("/api/taobao/publish/status/{}".format(task_id)).get("data") or {})
        if task.get("status") != last:
            print("  [{}] {}% {}".format(task.get("status"), task.get("progress"),
                                         str(task.get("message"))[:64]))
            last = task.get("status")
        if task.get("status") in ("succeeded", "failed", "cancelled"):
            break

    print()
    result = task.get("result") or {}
    print("--- 阶段 ---")
    for step in (result.get("steps") or []):
        marker = {"ok": "[OK]  ", "failed": "[FAIL]", "skipped": "[SKIP]",
                  "running": "[..]  "}.get(step.get("status"), "[?]   ")
        print("{} {:<17} {:>7}ms  {}".format(marker, step.get("label"), step.get("elapsed_ms"),
                                            str(step.get("summary"))[:66]))

    print()
    print("--- 判定 ---")
    error = (result.get("error") or {}).get("code")
    blockers = result.get("blockers") or []
    codes = [error] + [b.get("code") for b in blockers]
    print("  status            =", task.get("status"))
    print("  publish_confirmed =", task.get("publish_confirmed"))
    print("  error.code        =", error)
    print("  blockers          =", json.dumps([b.get("code") for b in blockers], ensure_ascii=False))

    reached_submit = any(str(s.get("label") or "").find("提交") >= 0
                         for s in (result.get("steps") or []))
    print("  流水线跑到「提交」那一步了吗：", "是" if reached_submit else "否（在更早处停下）")

    for blocker in blockers:
        detail = str(blocker.get("detail") or "")
        if detail:
            print("  blocker detail    =", detail[:160])

    print()
    if "SUBMIT_NOT_AUTHORIZED" in [str(c) for c in codes]:
        print("结论：**被第二把锁拦住**（SUBMIT_NOT_AUTHORIZED）——商品没有被提交。")
        return 0
    if "WRITE_NOT_AUTHORIZED" in [str(c) for c in codes]:
        print("结论：被**第一把**锁拦住（WRITE_NOT_AUTHORIZED）。")
        print("      ⚠️ 这说明白名单**没有**包含 submit_publish —— 与本次实测目的不符，")
        print("         请检查 Sidecar 的环境变量。")
        return 2
    if task.get("status") == "succeeded" and task.get("publish_confirmed"):
        print("⚠️ **流水线报发布成功** —— 请立刻去卖家中心核对！")
        return 3
    print("结论：没被授权门拦住（error.code={}）—— 需要人工看上面。".format(error))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

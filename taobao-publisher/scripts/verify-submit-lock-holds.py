# -*- coding: utf-8 -*-
"""证明**最后一道锁真的拦得住** —— 不提交，但让流水线走到提交那一步。

## 为什么值得做

`submit` 从未执行过，因为需要显式授权。但**「需要授权」本身**还没在
生产路径上验证过——单元测试验过 `run_stage` 的门，而 Sidecar 那条路没验过。

这个脚本发：

```
dry_run            = false
stop_before_submit = false     ← 允许走到提交
```

于是流水线**会走到 `submit` 那一步**，然后被拦下来。

## 为什么它不可能提交（三重）

1. Sidecar 的写白名单是 `TAOBAO_UPLOAD_ALLOW_WRITE=upload_image,save_draft`
   ——**不含 `submit_publish`**；
2. `TAOBAO_UPLOAD_ALLOW_SUBMIT` **未设**（提交锁要精确等于 `"1"`）；
3. `run_stage` 在**调用阶段处理器之前**就 `authorization.require(operation)`
   ——处理器根本不会被执行，**一次点击都不会发生**。

再加一层：`stage_submit` 自己还硬要求 `ctx.scratch["readback"]` 存在
（第 29 轮加的），而本次 `readback` 会正常产生。

## 预期

`submit` 阶段失败，错误码是 `SUBMIT_NOT_AUTHORIZED` 或 `WRITE_NOT_AUTHORIZED`，
`blockers` 里说得清是授权问题。**商品没有被提交。**

用法::

    python taobao-publisher/scripts/verify-submit-lock-holds.py
"""

from __future__ import annotations

import json
import os
import pathlib
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime

SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
SUBPROJECT = SCRIPT_DIR.parent
TMP_DIR = SUBPROJECT / "tmp"

SIDECAR = "http://127.0.0.1:5001"

CATEGORY_PATH = ("女士内衣/男士内衣/家居服",
                 "短袜/打底袜/丝袜/美腿袜（新）",
                 "一次性袜子")

TITLE = "提交锁验证DSH001"

#: 这两个错误码都表示**被授权门拦住**。
LOCK_CODES = ("SUBMIT_NOT_AUTHORIZED", "WRITE_NOT_AUTHORIZED")


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
    print("=" * 76)
    print("证明最后一道锁拦得住（stop_before_submit=false，但白名单不含 submit_publish）")
    print("=" * 76)

    product = {
        "title": TITLE,
        "guide_title": "导购提交锁验证",
        "category_path": ">".join(CATEGORY_PATH),
        "freight_template_name": "极兔快递",
        "props": [{"prop_name": "品牌", "value_name": "无品牌/无注册商标"}],
        "skus": [{"spec_values": {"尺码": "M(37-41)"}, "price": 16.8, "stock": 200}],
    }

    payload = {
        "record_id": 1,
        "platform": "taobao",
        "account_profile": "taobao-19d2c8e3",
        "dry_run": False,
        # ⚠️ **允许走到提交**——这一步就是用来验证「走到提交也提交不了」。
        "stop_before_submit": False,
        "product": product,
    }

    print("POST /api/taobao/publish/start")
    print("  dry_run            = {}".format(payload["dry_run"]))
    print("  stop_before_submit = {}  ← 允许走到提交".format(payload["stop_before_submit"]))
    print()
    print("为什么它不可能提交（三重）：")
    print("  ① Sidecar 白名单 TAOBAO_UPLOAD_ALLOW_WRITE 不含 submit_publish")
    print("  ② TAOBAO_UPLOAD_ALLOW_SUBMIT 未设（要精确等于 \"1\"）")
    print("  ③ run_stage 在**调用处理器之前**就检查授权")
    print()

    try:
        started = post("/api/taobao/publish/start", payload)
    except urllib.error.HTTPError as exc:
        print("启动失败 HTTP {}：{}".format(exc.code, exc.read().decode("utf-8")[:300]))
        return 1

    if not started.get("success"):
        print("启动失败：{}".format(json.dumps(started, ensure_ascii=False)[:300]))
        return 1

    task_id = (started.get("data") or {}).get("task_id")
    print("task_id = {}".format(task_id))
    print()

    deadline = time.time() + 1800
    task = {}
    last = None
    while time.time() < deadline:
        time.sleep(15)
        task = (get("/api/taobao/publish/status/{}".format(task_id)).get("data") or {})
        state = task.get("status")
        if state != last:
            print("  [{}] {}% step={} {}".format(
                state, task.get("progress"), task.get("current_step"),
                str(task.get("message"))[:66]))
            last = state
        if state in ("succeeded", "failed", "cancelled"):
            break

    print()
    print("=" * 76)
    result = task.get("result") or {}
    steps = result.get("steps") or []
    for step in steps:
        marker = {"ok": "[OK]  ", "failed": "[FAIL]", "skipped": "[SKIP]",
                  "running": "[..]  "}.get(step.get("status"), "[?]   ")
        print("{} {:<18} {:>7}ms  {}".format(
            marker, step.get("label"), step.get("elapsed_ms"),
            str(step.get("summary"))[:72]))

    print()
    blockers = result.get("blockers") or []
    error = result.get("error") or {}
    codes = [error.get("code")] + [b.get("code") for b in blockers]
    blocked = [code for code in codes if code in LOCK_CODES]

    print("  status            = {}".format(task.get("status")))
    print("  publish_confirmed = {}".format(task.get("publish_confirmed")))
    print("  error.code        = {}".format(error.get("code")))
    print("  blockers          = {}".format(
        json.dumps([b.get("code") for b in blockers], ensure_ascii=False)))
    print()

    TMP_DIR.mkdir(parents=True, exist_ok=True)
    out = TMP_DIR / "submit-lock-{}.json".format(datetime.now().strftime("%Y%m%d%H%M%S"))
    out.write_text(json.dumps({
        "captured_at": datetime.now().isoformat(timespec="seconds"),
        "intent": "证明提交锁拦得住；**不提交**",
        "stop_before_submit": False,
        "never_did": ["提交宝贝信息"],
        "task": task,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print("产物：{}".format(out))
    print()

    if blocked:
        print("结论：**提交被授权门拦住了**（{}）—— 商品没有被提交。".format(
            "、".join(sorted(set(blocked)))))
        for b in blockers:
            if b.get("code") in LOCK_CODES:
                print("       {}".format(str(b.get("detail"))[:110]))
        return 0

    if task.get("status") == "succeeded":
        print("⚠️ **流水线报成功了** —— 请立刻去卖家中心核对是否被上架！")
        return 2

    print("结论：提交没成功，但**不是**被授权门拦的（code={}）—— 需要人工看上面。".format(
        error.get("code")))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

# -*- coding: utf-8 -*-
"""验证**生产路径**：前端 → Sidecar → 流水线，端到端（除 `submit`）。

## 为什么

前几轮的实机验证都走 **CLI / 脚本**（`smoke-full-chain-live.py` 直接调阶段处理器）。
而用户实际走的是：

```
界面 → POST /api/taobao/publish/start → Sidecar 建任务 → pipeline.run_from_record
```

**两条路径不等价**：Sidecar 还要做参数校验、`product` 翻译、授权解析、任务表登记。

## 这次发什么

```
dry_run            = false      ← 真的写（但有白名单拦着）
stop_before_submit = true       ← 提交前截停
product            = 界面会收集的那套
```

Sidecar 的写白名单是 `upload_image,save_draft`，**不含 `submit_publish`**，
`TAOBAO_UPLOAD_ALLOW_SUBMIT` 也没设——所以**即使请求允许提交，也提交不了**。

## 预期

`session` → `precheck` → 8 个阶段全部 ok → 停在 `submit` 之前，
`publish_confirmed` 恒为 `false`，`blockers = []`。

用法::

    python taobao-publisher/scripts/verify-sidecar-publish-path.py
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
REPO_ROOT = SUBPROJECT.parent
TMP_DIR = SUBPROJECT / "tmp"

SIDECAR = "http://127.0.0.1:5001"

CATEGORY_PATH = ("女士内衣/男士内衣/家居服",
                 "短袜/打底袜/丝袜/美腿袜（新）",
                 "一次性袜子")

TITLE = "Sidecar路径冒烟DSH001"
GUIDE_TITLE = "导购Sidecar冒烟"


def post(path: str, payload: dict, timeout: float = 30.0):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        SIDECAR + path, data=body, method="POST",
        headers={"Content-Type": "application/json; charset=utf-8"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def get(path: str, timeout: float = 30.0):
    with urllib.request.urlopen(SIDECAR + path, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def find_main_images(limit: int = 5):
    """合规的是 `_1x1` 那套（800x800，比例 1.0）。"""

    base = (pathlib.Path(os.environ["LOCALAPPDATA"]) / "com.dyin.sock-publisher"
            / "uploads" / "products")
    if not base.is_dir():
        return []
    for product in sorted(base.iterdir()):
        main = product / "主图"
        if not main.is_dir():
            continue
        files = sorted(str(p) for p in main.iterdir() if p.name.endswith("_1x1.jpg"))
        if files:
            return files[:limit]
    return []


def main() -> int:
    print("=" * 76)
    print("生产路径验证：前端 → Sidecar → 流水线（提交前截停）")
    print("=" * 76)

    readiness = get("/api/taobao/readiness")
    data = readiness.get("data") or {}
    print("Sidecar 就绪度：mode={} publishable={} 未实机验证={}".format(
        data.get("mode"), data.get("automatic_publish_ready"),
        data.get("live_unverified_stages")))
    print()

    images = find_main_images()
    print("主图（合规 1:1，{} 张）".format(len(images)))
    if not images:
        print("找不到合规主图——upload_images 会失败")
    print()

    product = {
        "title": TITLE,
        "guide_title": GUIDE_TITLE,
        "category_path": ">".join(CATEGORY_PATH),
        "freight_template_name": "极兔快递",
        "props": [{"prop_name": "品牌", "value_name": "无品牌/无注册商标"}],
        "skus": [{"spec_values": {"尺码": "M(37-41)"}, "price": 16.8, "stock": 200}],
    }

    payload = {
        "record_id": 1,
        "platform": "taobao",
        "account_profile": "taobao-19d2c8e3",
        # **真的写**，但服务端白名单里没有 submit_publish。
        "dry_run": False,
        # **提交前截停。**
        "stop_before_submit": True,
        "product": product,
    }

    print("POST /api/taobao/publish/start")
    print("  dry_run            = {}".format(payload["dry_run"]))
    print("  stop_before_submit = {}".format(payload["stop_before_submit"]))
    print("  product            = {} 个字段".format(len(product)))
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
    print("task_id = {}  dry_run={}  stop_before_submit={}".format(
        task_id, (started.get("data") or {}).get("dry_run"),
        (started.get("data") or {}).get("stop_before_submit")))
    print()

    deadline = time.time() + 1800
    last = None
    while time.time() < deadline:
        time.sleep(15)
        status = get("/api/taobao/publish/status/{}".format(task_id))
        task = status.get("data") or {}
        state = task.get("status")
        if state != last:
            print("  [{}] {}% step={} {}".format(
                state, task.get("progress"), task.get("current_step"),
                str(task.get("message"))[:70]))
            last = state
        if state in ("succeeded", "failed", "cancelled"):
            break

    print()
    print("=" * 76)
    result = (task or {}).get("result") or {}
    steps = result.get("steps") or task.get("steps") or []
    for step in steps:
        marker = {"ok": "[OK]  ", "failed": "[FAIL]", "skipped": "[SKIP]",
                  "running": "[..]  "}.get(step.get("status"), "[?]   ")
        print("{} {:<18} {:>7}ms  {}".format(
            marker, step.get("label"), step.get("elapsed_ms"),
            str(step.get("summary"))[:76]))

    print()
    print("  status            = {}".format(task.get("status")))
    print("  publish_confirmed = {}（**恒为 false**：提交成功与否不由本任务判定）".format(
        task.get("publish_confirmed")))
    print("  blockers          = {}".format(len(result.get("blockers") or [])))
    print("  dry_run           = {}".format(task.get("dry_run")))
    print("  stopped_before_submit = {}".format(result.get("stopped_before_submit")))

    TMP_DIR.mkdir(parents=True, exist_ok=True)
    out = TMP_DIR / "sidecar-publish-path-{}.json".format(
        datetime.now().strftime("%Y%m%d%H%M%S"))
    out.write_text(json.dumps({
        "captured_at": datetime.now().isoformat(timespec="seconds"),
        "path": "frontend -> sidecar -> pipeline",
        "dry_run": False,
        "stop_before_submit": True,
        "never_did": ["提交宝贝信息", "保存草稿"],
        "task": task,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print()
    print("产物：{}".format(out))

    ok = task.get("status") == "succeeded" and not (result.get("blockers") or [])
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

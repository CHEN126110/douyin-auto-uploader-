# -*- coding: utf-8 -*-
"""**终态验证**：走生产路径（界面 → Sidecar → 流水线）跑一遍，然后回答两个问题。

1. 流水线跑完之后，表单是不是**平台认可的**（没有可见的校验错误）？
2. 页面上还剩哪些可见提示？**逐条分类**——哪些是说明文字、哪些是校验错误。

第 73 轮就是靠这个办法发现了「至少有一个sku的价格大于0」——
**平台的报错比我们自己的核对更权威**。
"""

from __future__ import annotations

import json
import pathlib
import sys
import time
import urllib.request

# scripts/ 的上一级才是 	aobao_publish 包所在。
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from taobao_publish import page  # noqa: E402

SIDECAR = "http://127.0.0.1:5001"
CATEGORY = ("女士内衣/男士内衣/家居服",
            "短袜/打底袜/丝袜/美腿袜（新）",
            "一次性袜子")

#: 判定「这是校验错误」的关键词。**保守**：只列明确的否定/要求类措辞。
ERROR_MARKERS = ("大于0", "请先", "不能为空", "必须", "错误", "失败", "无效",
                 "请填写", "请选择", "不符合", "超出", "不支持")

print("=" * 76)
print("终态验证：生产路径 + 平台侧的可见状态")
print("=" * 76)

payload = {
    "record_id": 1,
    "platform": "taobao",
    "account_profile": "taobao-19d2c8e3",
    "dry_run": False,
    "stop_before_submit": True,
    "product": {
        "title": "终态验证DSH001",
        "guide_title": "导购终态验证",
        "category_path": ">".join(CATEGORY),
        "freight_template_name": "极兔快递",
        "props": [{"prop_name": "品牌", "value_name": "无品牌/无注册商标"}],
        "skus": [{"spec_values": {"尺码": "M(37-41)"}, "price": 16.8, "stock": 200}],
    },
}

body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
request = urllib.request.Request(SIDECAR + "/api/taobao/publish/start", data=body,
                                 method="POST",
                                 headers={"Content-Type": "application/json; charset=utf-8"})
with urllib.request.urlopen(request, timeout=30) as response:
    started = json.loads(response.read().decode("utf-8"))
task_id = (started.get("data") or {}).get("task_id")
print()
print("task_id =", task_id)

task = {}
deadline = time.time() + 900
last = None
while time.time() < deadline:
    time.sleep(10)
    with urllib.request.urlopen(
            "{}/api/taobao/publish/status/{}".format(SIDECAR, task_id), timeout=30) as response:
        task = (json.loads(response.read().decode("utf-8")).get("data") or {})
    if task.get("status") != last:
        print("  [{}] {}% {}".format(task.get("status"), task.get("progress"),
                                     str(task.get("message"))[:60]))
        last = task.get("status")
    if task.get("status") in ("succeeded", "failed", "cancelled"):
        break

print()
result = task.get("result") or {}
print("=== 阶段 ===")
for step in (result.get("steps") or []):
    marker = {"ok": "[OK]  ", "failed": "[FAIL]", "skipped": "[SKIP]",
              "running": "[..]  "}.get(step.get("status"), "[?]   ")
    print("{} {:<17} {:>7}ms  {}".format(marker, step.get("label"), step.get("elapsed_ms"),
                                        str(step.get("summary"))[:70]))

print()
print("--- 汇总 ---")
print("  status            =", task.get("status"))
print("  publish_confirmed =", task.get("publish_confirmed"))
print("  blockers          =", len(result.get("blockers") or []))

# --- 平台侧 ---
print()
print("=" * 76)
print("平台侧的可见状态（比我们自己的核对更权威）")
print("=" * 76)

with urllib.request.urlopen("http://127.0.0.1:9502/json/list", timeout=8) as response:
    targets = json.loads(response.read().decode("utf-8"))
pages = [t for t in targets
         if t.get("type") == "page" and "item.upload.taobao.com" in str(t.get("url"))]
if not pages:
    print("  （没有发布页）")
    raise SystemExit(0)

with page.PageClient.connect(pages[0]["webSocketDebuggerUrl"]) as client:
    detail = client.evaluate("""(() => {
      const out = [];
      for (const el of document.querySelectorAll('.next-message, [class*="message"]')) {
        const text = (el.textContent || '').trim();
        if (!text) continue;
        const rect = el.getBoundingClientRect();
        const style = window.getComputedStyle(el);
        const visible = rect.height > 0 && rect.width > 0 && style.display !== 'none'
                        && style.visibility !== 'hidden' && Number(style.opacity) > 0;
        if (!visible) continue;
        out.push({ text: text.slice(0, 90), cls: String(el.className).slice(0, 60) });
      }
      return out;
    })()""")

    markers = ERROR_MARKERS
    suspects, notes = [], []
    seen = set()
    for item in (detail or []):
        key = item["text"][:40]
        if key in seen:
            continue
        seen.add(key)
        bucket = suspects if any(m in item["text"] for m in markers) else notes
        bucket.append(item)

    print()
    print("  ⚠️ 疑似**校验错误**（{} 条）：".format(len(suspects)))
    for item in suspects:
        print("     - {}".format(item["text"]))
    if not suspects:
        print("     （无）")
    print()
    print("  ℹ️ 说明性文字（{} 条，前 6 条）：".format(len(notes)))
    for item in notes[:6]:
        print("     - {}".format(item["text"]))

    print()
    print("  SKU 行：", page.read_sku_row_numbers(client))
    state = (page.read_submit_state(client) or {}).get("submit") or {}
    print("  提交按钮：present={} disabled={} visible={}".format(
        state.get("present"), state.get("disabled"), state.get("visible")))

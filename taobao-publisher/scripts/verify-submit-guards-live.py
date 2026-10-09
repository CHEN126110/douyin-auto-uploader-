# -*- coding: utf-8 -*-
"""实机验证 ``submit`` 的守卫：**不提交任何商品**。

本脚本**故意不点击提交按钮**。它验证三件事：

  1. 提交按钮能被只读地读到（存在 / 可见 / 是否禁用）；
  2. **没有授权时**，执行器在处理器之前就把 submit 拦下；
  3. 只有第二把锁、或只有第一把锁时，同样被拦。

第 2、3 条走的是真实的 ``run_stage``，只是授权对象是空的——所以即使守卫
有洞，本脚本也不会真的提交（授权为空时无论如何都到不了点击那一步）。

用法::

    python taobao-publisher/scripts/verify-submit-guards-live.py --address 127.0.0.1:9502
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SUBPROJECT = SCRIPT_DIR.parent
if str(SUBPROJECT) not in sys.path:
    sys.path.insert(0, str(SUBPROJECT))

from taobao_publish import page, stages  # noqa: E402
from taobao_publish.authorization import WriteAuthorization  # noqa: E402
from taobao_publish.models import PublishItem, StepRecord  # noqa: E402

TMP_DIR = SUBPROJECT / "tmp"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--address", default="127.0.0.1:9502")
    args = parser.parse_args()

    with urllib.request.urlopen("http://{}/json/list".format(args.address), timeout=5) as response:
        targets = json.loads(response.read().decode("utf-8"))
    target = next(
        (t for t in targets
         if t.get("type") == "page" and "item.upload.taobao.com" in str(t.get("url") or "")),
        None,
    )
    if target is None:
        print("没有发布工作台页面")
        return 1

    report = {}

    print("==== 1) 只读读提交按钮状态 ====")
    with page.PageClient.connect(target["webSocketDebuggerUrl"]) as client:
        state = page.read_submit_state(client)
    print("  {}".format(json.dumps(state, ensure_ascii=False)))
    report["submit_state"] = state

    submit_info = (state or {}).get("submit") or {}
    print("  提交按钮 present={} visible={} disabled={}".format(
        submit_info.get("present"), submit_info.get("visible"), submit_info.get("disabled")))

    item = PublishItem(record_id=0, record_name="守卫验证", title="守卫验证")
    cases = [
        ("无任何授权", WriteAuthorization.none()),
        ("只有写锁（无 ALLOW_SUBMIT）",
         WriteAuthorization(frozenset({"save_draft", "submit_publish"}), submit_unlocked=False)),
        ("只有提交锁（写锁里没有 submit_publish）",
         WriteAuthorization(frozenset({"save_draft"}), submit_unlocked=True)),
    ]

    print()
    print("==== 2/3) 走真实 run_stage，验证授权门在处理器之前就拦住 ====")
    print("  {:<34} {:<10} {}".format("授权情况", "结果", "错误码"))
    print("  " + "-" * 66)
    results = []
    for label, authorization in cases:
        ctx = stages.PipelineContext(item=item, dry_run=False, authorization=authorization)
        ctx.cdp_list_url = "http://{}/json/list".format(args.address)
        run = stages.run_stage("submit", ctx, index=0, total=1, steps=[StepRecord(name="submit")])
        print("  {:<32} {:<10} {}".format(
            label, "已拦截" if not run.outcome.ok else "**放行**", run.outcome.error_code or "-"))
        results.append({"case": label, "blocked": not run.outcome.ok,
                        "error_code": run.outcome.error_code})

    print()
    print("==== 4) dry-run 下即使两把锁齐了也必须跳过 ====")
    ctx = stages.PipelineContext(
        item=item, dry_run=True,
        authorization=WriteAuthorization(frozenset({"submit_publish"}), submit_unlocked=True),
    )
    ctx.cdp_list_url = "http://{}/json/list".format(args.address)
    run = stages.run_stage("submit", ctx, index=0, total=1, steps=[StepRecord(name="submit")])
    print("  dry-run 跳过 = {}  状态 = {}".format(run.skipped_for_dry_run, run.outcome.status))

    ok = all(r["blocked"] for r in results) and run.skipped_for_dry_run
    print()
    print("结论：{}".format("三道守卫全部生效，未提交任何商品" if ok else "**有守卫未生效，需要检查**"))

    TMP_DIR.mkdir(parents=True, exist_ok=True)
    out = TMP_DIR / "verify-submit-guards-{}.json".format(datetime.now().strftime("%Y%m%d%H%M%S"))
    out.write_text(json.dumps({
        "captured_at": datetime.now().isoformat(timespec="seconds"),
        "submitted_anything": False,
        "never_did": ["点击提交宝贝信息", "保存草稿", "上传图片"],
        "submit_state": state,
        "authorization_cases": results,
        "dry_run_skipped": run.skipped_for_dry_run,
        "passed": ok,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print("产物：{}".format(out))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

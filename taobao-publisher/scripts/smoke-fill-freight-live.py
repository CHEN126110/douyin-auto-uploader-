# -*- coding: utf-8 -*-
"""实机冒烟：跑一遍 ``fill_freight``（选运费模板），验证后恢复原值。

**这是写操作**（会改选运费模板），必须显式传 ``--allow-write``。
**不保存草稿、不上架、不提交。**

用法::

    python taobao-publisher/scripts/smoke-fill-freight-live.py --address 127.0.0.1:9502 --allow-write
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
from taobao_publish.models import PublishItem  # noqa: E402

TMP_DIR = SUBPROJECT / "tmp"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--address", default="127.0.0.1:9502")
    parser.add_argument("--allow-write", action="store_true")
    parser.add_argument("--template", default="", help="要选的模板名；留空则自动挑一个非当前的")
    parser.add_argument("--bad-name", default="", help="故意传一个不存在的模板名，验证 fail-closed")
    args = parser.parse_args()

    if not args.allow_write:
        print("这是写操作（会改选运费模板），必须显式加 --allow-write。")
        return 2

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
    ws_url = target["webSocketDebuggerUrl"]

    with page.PageClient.connect(ws_url) as client:
        print("页面：{}".format(str(client.evaluate("location.href.split('?')[0]"))[:90]))
        current = page.read_freight_template(client)
        page.open_freight_dropdown(client)
        options = page.read_freight_options(client)
        client.evaluate("document.body.click(); document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true})); 'x'")
    print("当前模板：{!r}".format(current))
    print("可选模板：{}".format(json.dumps(options, ensure_ascii=False)))
    print()

    if args.bad_name:
        wanted = args.bad_name
        print("（故意用一个不存在的名字验证 fail-closed）")
    elif args.template:
        wanted = args.template
    else:
        wanted = next((o for o in options if o != current), "")

    if not wanted:
        print("没有可切换的模板，退出")
        return 1

    print("目标模板：{!r}".format(wanted))
    item = PublishItem(record_id=0, record_name="实机冒烟", title="冒烟", freight_template_name=wanted)
    ctx = stages.PipelineContext(item=item, dry_run=False)
    ctx.cdp_list_url = "http://{}/json/list".format(args.address)

    print()
    print("==== 调用阶段处理器 fill_freight ====")
    outcome = stages.STAGE_HANDLERS["fill_freight"].run(ctx)
    print("  ok      : {}".format(outcome.ok))
    print("  status  : {}".format(outcome.status))
    print("  summary : {}".format(outcome.summary))
    if outcome.error_code:
        print("  error   : {}".format(outcome.error_code))
    for blocker in outcome.blockers:
        print("  blocker : [{}] {} -> {}".format(blocker.code, blocker.field, blocker.detail[:80]))

    restored = None
    if outcome.ok and current:
        print()
        print("==== 恢复原值 ====")
        restore_item = PublishItem(record_id=0, record_name="恢复", title="冒烟",
                                   freight_template_name=current)
        restore_ctx = stages.PipelineContext(item=restore_item, dry_run=False)
        restore_ctx.cdp_list_url = "http://{}/json/list".format(args.address)
        restore = stages.STAGE_HANDLERS["fill_freight"].run(restore_ctx)
        print("  ok={} {}".format(restore.ok, restore.summary[:90]))
        with page.PageClient.connect(ws_url) as client:
            restored = page.read_freight_template(client)
        print("  恢复后：{!r}".format(restored))

    TMP_DIR.mkdir(parents=True, exist_ok=True)
    out = TMP_DIR / "smoke-fill-freight-{}.json".format(datetime.now().strftime("%Y%m%d%H%M%S"))
    out.write_text(json.dumps({
        "captured_at": datetime.now().isoformat(timespec="seconds"),
        "wrote": True,
        "never_did": ["保存草稿", "提交宝贝信息", "上传图片"],
        "current_before": current,
        "options": options,
        "wanted": wanted,
        "intentionally_bad": bool(args.bad_name),
        "outcome": {"ok": outcome.ok, "status": outcome.status, "summary": outcome.summary,
                    "error_code": outcome.error_code,
                    "blockers": [{"code": b.code, "field": b.field, "detail": b.detail}
                                 for b in outcome.blockers]},
        "restored_to": restored,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print()
    print("产物：{}".format(out))
    if args.bad_name:
        # 这种情况下“成功”意味着正确地拒绝了
        ok = (not outcome.ok) and outcome.error_code == "FREIGHT_TEMPLATE_NOT_FOUND"
        print("结论：{}".format("fail-closed 生效（不存在的模板被拒绝）" if ok else "未按预期拒绝"))
        return 0 if ok else 1
    ok = outcome.ok and (restored == current or not current)
    print("结论：{}".format("运费模板选择与回读通过，现场已恢复" if ok else "未通过，见上"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

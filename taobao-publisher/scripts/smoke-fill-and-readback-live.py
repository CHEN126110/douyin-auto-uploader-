# -*- coding: utf-8 -*-
"""实机冒烟：``fill_base`` → ``readback``，验证「写入 → 整体核对」闭环。

**这是写操作**，必须显式传 ``--allow-write``。写入**不保存草稿、不上架、不提交**，
脚本结束前恢复原值。

用法::

    python taobao-publisher/scripts/smoke-fill-and-readback-live.py --address 127.0.0.1:9502 --allow-write
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
from taobao_publish.models import PublishItem, SkuEntry  # noqa: E402

TMP_DIR = SUBPROJECT / "tmp"
SMOKE_TITLE = "冒烟测试标题DSH002"
SMOKE_OUTER = "DSH-OUT-002"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--address", default="127.0.0.1:9502")
    parser.add_argument("--allow-write", action="store_true")
    args = parser.parse_args()

    if not args.allow_write:
        print("这是写操作（会改页面表单值），必须显式加 --allow-write。")
        print("（不保存草稿、不上架、不提交；脚本会恢复原值）")
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
        before = {
            "宝贝标题": page.read_text_field(client, "宝贝标题"),
            "商家编码": page.read_text_field(client, "商家编码"),
            "总库存": page.read_text_field(client, "总库存"),
        }
    print("原始值：{}".format(json.dumps(before, ensure_ascii=False)))
    print()

    item = PublishItem(
        record_id=0, record_name="实机冒烟", title=SMOKE_TITLE, outer_id=SMOKE_OUTER,
        skus=[SkuEntry({"颜色": "黑"}, price=16.8, stock=6),
              SkuEntry({"颜色": "白"}, price=19.9, stock=4)],
    )
    ctx = stages.PipelineContext(item=item, dry_run=False)
    ctx.cdp_list_url = "http://{}/json/list".format(args.address)

    print("==== 1) fill_base ====")
    base = stages.STAGE_HANDLERS["fill_base"].run(ctx)
    print("  ok={} status={}".format(base.ok, base.status))
    print("  {}".format(base.summary))

    print()
    print("==== 2) fill_price_stock ====")
    price = stages.STAGE_HANDLERS["fill_price_stock"].run(ctx)
    print("  ok={} status={}".format(price.ok, price.status))
    print("  {}".format(price.summary))

    print()
    print("==== 3) readback（整体核对）====")
    rb = stages.STAGE_HANDLERS["readback"].run(ctx)
    print("  ok={} status={}".format(rb.ok, rb.status))
    print("  {}".format(rb.summary))
    for blocker in rb.blockers:
        print("  blocker: [{}] {} <- {}".format(blocker.code, blocker.field, blocker.detail[:70]))

    print()
    print("==== 4) 恢复原值 ====")
    restored = {}
    try:
        with page.PageClient.connect(ws_url) as client:
            for label, original in before.items():
                page.fill_text_field(client, label, original or "")
                restored[label] = page.read_text_field(client, label)
    except Exception as exc:  # noqa: BLE001
        print("  恢复出错：{}: {}".format(type(exc).__name__, exc))
    print("  恢复后：{}".format(json.dumps(restored, ensure_ascii=False)))

    TMP_DIR.mkdir(parents=True, exist_ok=True)
    out = TMP_DIR / "smoke-fill-readback-{}.json".format(datetime.now().strftime("%Y%m%d%H%M%S"))
    out.write_text(json.dumps({
        "captured_at": datetime.now().isoformat(timespec="seconds"),
        "wrote": True,
        "never_did": ["保存草稿", "提交宝贝信息", "上传图片"],
        "before": before,
        "restored": restored,
        "stages": {
            "fill_base": {"ok": base.ok, "summary": base.summary, "data": base.data},
            "fill_price_stock": {"ok": price.ok, "summary": price.summary, "data": price.data},
            "readback": {"ok": rb.ok, "summary": rb.summary,
                         "blockers": [{"code": b.code, "field": b.field, "detail": b.detail}
                                      for b in rb.blockers]},
        },
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print()
    print("产物：{}".format(out))
    ok = base.ok and price.ok and rb.ok and all(
        (restored.get(k) or "") == (before.get(k) or "") for k in before)
    print("结论：{}".format("填表与回读闭环通过，现场已恢复" if ok else "未通过，见上"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

# -*- coding: utf-8 -*-
"""实验：找到**到底是谁**把一口价/总库存清掉的。

E-126 的第一个假设（`fill_skus` 的异步重渲染）**已被证伪**：
写入后盯着看 45 秒，值一直没变。

那么嫌疑在中间那一步——`fill_freight`（选运费模板）会打开下拉、点选项，
很可能触发一次表单重渲染。本脚本按 e2e 的顺序复现：

  1. 写一口价 / 总库存，回读确认；
  2. 跑一次 ``fill_freight``；
  3. 再读一次，看值还在不在。

**会改未保存表单状态**，不保存草稿、不提交。

用法::

    python taobao-publisher/scripts/experiment-who-wipes-price.py --address 127.0.0.1:9502 --allow-write
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SUBPROJECT = SCRIPT_DIR.parent
if str(SUBPROJECT) not in sys.path:
    sys.path.insert(0, str(SUBPROJECT))

from taobao_publish import page, stages  # noqa: E402
from taobao_publish.authorization import WriteAuthorization  # noqa: E402
from taobao_publish.models import PublishItem, SkuEntry  # noqa: E402

TMP_DIR = SUBPROJECT / "tmp"

SNAP_JS = r"""
(() => {
  const rows = Array.from(document.querySelectorAll('.sell-component-info-wrapper-wrap'));
  const pick = (want) => {
    for (const r of rows) {
      const label = r.querySelector('.sell-component-info-wrapper-label');
      if (!label) continue;
      if ((label.textContent || '').trim() !== want) continue;
      const input = r.querySelector('input');
      return input ? String(input.value || '') : null;
    }
    return null;
  };
  return {
    price: pick('一口价'),
    stock: pick('总库存'),
    title: pick('宝贝标题'),
    skuRows: document.querySelectorAll('tr.sku-table-row').length,
    freight: (() => {
      const all = Array.from(document.querySelectorAll('div,span,label'));
      const anchor = all.filter(el => (el.textContent || '').trim() === '运费模板');
      if (!anchor.length) return null;
      let node = anchor[anchor.length - 1];
      for (let hop = 0; hop <= 4 && node; hop++) {
        const c = node.querySelector('input,[role="combobox"]');
        if (c) return String(c.value || '') || c.getAttribute('aria-valuetext') || '';
        node = node.parentElement;
      }
      return null;
    })(),
  };
})()
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--address", default="127.0.0.1:9502")
    parser.add_argument("--allow-write", action="store_true")
    parser.add_argument("--template", default="系统模板-商家默认模板")
    args = parser.parse_args()

    if not args.allow_write:
        print("这会改未保存表单状态，必须显式加 --allow-write。")
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

    steps = []
    with page.PageClient.connect(target["webSocketDebuggerUrl"]) as client:
        start = client.evaluate(SNAP_JS)
        print("起始：{}".format(json.dumps(start, ensure_ascii=False)))
        steps.append({"step": "start", "snap": start})

        print()
        print("── 1) 写一口价 '16.80' / 总库存 '111' ──")
        page.fill_text_field(client, "一口价", "16.80")
        page.fill_text_field(client, "总库存", "111")
        after_write = client.evaluate(SNAP_JS)
        print("  {}".format(json.dumps(after_write, ensure_ascii=False)))
        steps.append({"step": "write", "snap": after_write})

        print()
        print("── 2) 跑一次 fill_freight（选 {!r}）──".format(args.template))
        item = PublishItem(record_id=0, record_name="实验", title="实验",
                           freight_template_name=args.template)
        ctx = stages.PipelineContext(item=item, dry_run=False,
                                     authorization=WriteAuthorization.none())
        ctx.cdp_list_url = "http://{}/json/list".format(args.address)
        outcome = stages.stage_fill_freight(ctx)
        print("  ok={} {}".format(outcome.ok, outcome.summary[:100]))
        steps.append({"step": "fill_freight", "ok": outcome.ok, "summary": outcome.summary})

        time.sleep(2)
        after_freight = client.evaluate(SNAP_JS)
        print("  {}".format(json.dumps(after_freight, ensure_ascii=False)))
        steps.append({"step": "after_freight", "snap": after_freight})

        print()
        print("── 3) 再等 10 秒看有没有延迟覆盖 ──")
        for second in range(10):
            time.sleep(1.0)
        after_wait = client.evaluate(SNAP_JS)
        print("  {}".format(json.dumps(after_wait, ensure_ascii=False)))
        steps.append({"step": "after_wait", "snap": after_wait})

    print()
    print("==== 结论 ====")
    print("  写入后：      一口价={!r} 总库存={!r} 标题={!r}".format(
        after_write.get("price"), after_write.get("stock"), after_write.get("title")))
    print("  fill_freight 后：一口价={!r} 总库存={!r} 标题={!r}".format(
        after_freight.get("price"), after_freight.get("stock"), after_freight.get("title")))
    lost = (after_write.get("price") != after_freight.get("price")
            or after_write.get("stock") != after_freight.get("stock"))
    print("  → {}".format(
        "**fill_freight 把价格库存清掉了**" if lost
        else "fill_freight 没有影响价格库存；真凶另有其人"))

    TMP_DIR.mkdir(parents=True, exist_ok=True)
    out = TMP_DIR / "who-wipes-{}.json".format(datetime.now().strftime("%Y%m%d%H%M%S"))
    out.write_text(json.dumps({
        "captured_at": datetime.now().isoformat(timespec="seconds"),
        "wrote": True,
        "never_did": ["保存草稿", "提交宝贝信息"],
        "lost_after_freight": lost,
        "steps": steps,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print()
    print("产物：{}".format(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

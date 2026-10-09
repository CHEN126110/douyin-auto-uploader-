# -*- coding: utf-8 -*-
"""实验：写入一口价 / 总库存之后，**盯着看它会不会被异步清掉**。

E-126 的怀疑：`fill_skus` 建表引发的重渲染是**异步**的，可能晚于
`fill_price_stock` 的写入到达，把值清掉。上一轮实测：

    fill_price_stock 阶段：写入 16.80 / 200，**当场回读确认通过**
    readback 阶段：       一口价=''、总库存='0'

本脚本做一件事：写入这两个值，然后**每秒读一次、连读 60 秒**，
把「什么时候被清掉」记录下来。

**会改未保存表单状态**，不保存草稿、不提交。

用法::

    python taobao-publisher/scripts/experiment-price-wipe.py --address 127.0.0.1:9502 --allow-write
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

from taobao_publish import page  # noqa: E402

TMP_DIR = SUBPROJECT / "tmp"

#: 读一口价 / 总库存 / SKU 行数 / 主图位数的现状。
SNAP_JS = r"""
(() => {
  const rows = Array.from(document.querySelectorAll('.sell-component-info-wrapper-wrap'));
  const pick = (want) => {
    for (const r of rows) {
      const label = r.querySelector('.sell-component-info-wrapper-label');
      const text = label ? (label.textContent || '').trim() : '';
      if (text !== want) continue;
      const input = r.querySelector('input');
      return input ? String(input.value || '') : null;
    }
    return null;
  };
  return {
    price: pick('一口价'),
    stock: pick('总库存'),
    skuRows: document.querySelectorAll('tr.sku-table-row').length,
    skuPriceInputs: Array.from(document.querySelectorAll('tr.sku-table-row input'))
      .map(i => String(i.value || '')).filter(Boolean).slice(0, 6),
  };
})()
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--address", default="127.0.0.1:9502")
    parser.add_argument("--allow-write", action="store_true")
    parser.add_argument("--watch", type=int, default=60)
    args = parser.parse_args()

    if not args.allow_write:
        print("这会写入一口价/总库存（改未保存表单状态），必须显式加 --allow-write。")
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

    samples = []
    with page.PageClient.connect(target["webSocketDebuggerUrl"]) as client:
        before = client.evaluate(SNAP_JS)
        print("写入前：{}".format(json.dumps(before, ensure_ascii=False)))

        print()
        print("── 写入一口价 '16.80'、总库存 '111' ──")
        try:
            page.fill_text_field(client, "一口价", "16.80")
            page.fill_text_field(client, "总库存", "111")
            print("  写入调用完成")
        except Exception as exc:  # noqa: BLE001
            print("  写入失败：{}".format(exc))
            return 1

        immediately = client.evaluate(SNAP_JS)
        print("  立即回读：{}".format(json.dumps(immediately, ensure_ascii=False)))

        print()
        print("盯着看 {} 秒（每秒一次）…".format(args.watch))
        print("  {:>4}  {:<10} {:<10} {}".format("t", "一口价", "总库存", "SKU行数"))
        print("  " + "-" * 44)
        wiped_at = None
        for second in range(args.watch):
            time.sleep(1.0)
            snap = client.evaluate(SNAP_JS)
            samples.append({"t": second + 1, "snap": snap})
            print("  {:>4}  {!r:<10} {!r:<10} {}".format(
                second + 1, str(snap.get("price")), str(snap.get("stock")),
                snap.get("skuRows")))
            if wiped_at is None and (snap.get("price") != "16.80" or snap.get("stock") != "111"):
                wiped_at = second + 1
                print("       ↑ **值变了**")

    print()
    print("==== 结论 ====")
    print("  写入后立即：一口价={!r} 总库存={!r}".format(
        immediately.get("price"), immediately.get("stock")))
    final = samples[-1]["snap"] if samples else {}
    print("  {} 秒后：   一口价={!r} 总库存={!r}".format(args.watch,
                                                        final.get("price"), final.get("stock")))
    if wiped_at:
        print("  → **第 {} 秒被改掉了**（确认存在异步覆盖）".format(wiped_at))
    else:
        print("  → {} 秒内没有被改掉（本次未复现异步覆盖）".format(args.watch))

    TMP_DIR.mkdir(parents=True, exist_ok=True)
    out = TMP_DIR / "price-wipe-{}.json".format(datetime.now().strftime("%Y%m%d%H%M%S"))
    out.write_text(json.dumps({
        "captured_at": datetime.now().isoformat(timespec="seconds"),
        "wrote": True,
        "never_did": ["保存草稿", "提交宝贝信息"],
        "before": before,
        "immediately": immediately,
        "wiped_at_second": wiped_at,
        "samples": samples,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print()
    print("产物：{}".format(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

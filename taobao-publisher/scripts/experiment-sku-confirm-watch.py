# -*- coding: utf-8 -*-
"""实验：点「确认创建」后**密集观测**，看抽屉与表格到底有没有变化。

E-092 里点了「确认创建」后抽屉不关、表格不出现，但只等了 5 秒。
可能是异步慢、可能有确认弹层、也可能真的被校验挡住了。

本脚本点一次「确认创建」，然后每秒读一次状态，连续 15 次，
把每一次的「抽屉开否 / 表格数 / 可见弹层 / 提示」都记下来。
**只点「确认创建」，不保存草稿、不提交。**

用法::

    python taobao-publisher/scripts/experiment-sku-confirm-watch.py --address 127.0.0.1:9502 --allow-create
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

WATCH_JS = r"""
(() => {
  const drawer = document.querySelector('.sku-decouple-drawer-container');
  const wrapper = document.querySelector('.sell-sku-table-wrapper-new');
  const popups = Array.from(document.querySelectorAll('.next-overlay-inner, .next-select-popup-wrap'))
    .filter(e => e.getBoundingClientRect().height > 0)
    .map(e => String(e.className).slice(0, 70));
  const msgs = Array.from(document.querySelectorAll('.next-message, .next-feedback, [class*="error"]'))
    .filter(el => el.getBoundingClientRect().height > 0)
    .map(el => (el.textContent || '').trim().slice(0, 90)).filter(Boolean);
  const seen = new Set(); const uniq = [];
  for (const m of msgs) { if (seen.has(m)) continue; seen.add(m); uniq.push(m); }
  return {
    drawerOpen: Boolean(drawer && drawer.getBoundingClientRect().height > 0),
    tables: wrapper ? wrapper.querySelectorAll('table').length : -1,
    wrapperText: wrapper ? (wrapper.textContent || '').trim().slice(0, 60) : null,
    popups,
    messages: uniq.slice(0, 6),
  };
})()
"""

CONFIRM_JS = r"""
(() => {
  const footer = document.querySelector('.sku-decouple-drawer-footer');
  if (!footer) return { ok: false, reason: 'no_footer' };
  const btns = Array.from(footer.querySelectorAll('button'))
    .filter(b => (b.textContent || '').trim() === '确认创建');
  if (btns.length !== 1) return { ok: false, reason: 'not_unique' };
  btns[0].click();
  return { ok: true, disabled: btns[0].disabled === true };
})()
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--address", default="127.0.0.1:9502")
    parser.add_argument("--allow-create", action="store_true")
    parser.add_argument("--seconds", type=int, default=15)
    args = parser.parse_args()

    if not args.allow_create:
        print("这会点「确认创建」，必须显式加 --allow-create。")
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

    with page.PageClient.connect(target["webSocketDebuggerUrl"]) as client:
        before = client.evaluate(WATCH_JS)
        print("点击前：{}".format(json.dumps(before, ensure_ascii=False)[:260]))
        if not (before or {}).get("drawerOpen"):
            print("抽屉没开着，先跑 create-sku-specs.py 把值加上")
            return 1

        clicked = client.evaluate(CONFIRM_JS)
        print("点「确认创建」：{}".format(json.dumps(clicked, ensure_ascii=False)))

        samples = []
        print()
        print("  {:>3}  {:<8} {:<7} {}".format("t", "抽屉", "表格数", "弹层/提示"))
        print("  " + "-" * 70)
        for second in range(args.seconds):
            time.sleep(1.0)
            state = client.evaluate(WATCH_JS)
            samples.append({"t": second + 1, "state": state})
            note = ""
            if (state or {}).get("popups"):
                note += "popups=" + str(len(state["popups"]))
            if (state or {}).get("messages"):
                note += " | " + "; ".join(state["messages"][:2])[:70]
            print("  {:>3}  {:<8} {:<7} {}".format(
                second + 1, str((state or {}).get("drawerOpen")),
                str((state or {}).get("tables")), note[:80]))

    final = samples[-1]["state"] if samples else {}
    changed = False
    for sample in samples:
        s = sample["state"]
        if not s.get("drawerOpen") or s.get("tables", 0) > (before or {}).get("tables", 0):
            changed = True
            break

    print()
    print("==== 结论 ====")
    print("  点击前：抽屉={} 表格数={}".format(
        (before or {}).get("drawerOpen"), (before or {}).get("tables")))
    print("  观测后：抽屉={} 表格数={}".format(final.get("drawerOpen"), final.get("tables")))
    print("  是否有变化：{}".format("是" if changed else "否"))

    TMP_DIR.mkdir(parents=True, exist_ok=True)
    out = TMP_DIR / "sku-confirm-watch-{}.json".format(datetime.now().strftime("%Y%m%d%H%M%S"))
    out.write_text(json.dumps({
        "captured_at": datetime.now().isoformat(timespec="seconds"),
        "clicked_confirm_create": True,
        "never_did": ["保存草稿", "提交宝贝信息", "上传图片"],
        "before": before,
        "clicked": clicked,
        "samples": samples,
        "changed": changed,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print()
    print("产物：{}".format(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

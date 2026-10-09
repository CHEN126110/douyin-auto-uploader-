# -*- coding: utf-8 -*-
"""实验：验证「确认创建」不生效是否因为**另一个属性（颜色分类）为空**。

假设：分层展示·选择标准属性模式下，**所有选中的属性都必须有值**；
颜色分类(0) 为空 → 校验静默失败 → 抽屉不关、表格不出现、也没有提示。

做法：
  1. 点击「颜色分类」的 ``.prop-item.selected`` 取消勾选，只留「尺码」；
  2. 再点「确认创建」，密集观测 12 秒。

若这次成功（抽屉关闭 / 表格出现），假设成立。

**不保存草稿、不提交、不上传图片。**

用法::

    python taobao-publisher/scripts/experiment-sku-deselect-prop.py --address 127.0.0.1:9502 --allow-create
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

PROPS_JS = r"""
(() => {
  const items = Array.from(document.querySelectorAll('.sku-decouple-drawer-container .prop-item'));
  return items.map((el, i) => ({
    index: i,
    text: (el.textContent || '').trim().slice(0, 16),
    selected: String(el.className).includes('selected'),
    visible: el.getBoundingClientRect().height > 0,
  }));
})()
"""

DESELECT_JS = r"""
(() => {
  const WANT = __WANT__;
  const items = Array.from(document.querySelectorAll('.sku-decouple-drawer-container .prop-item'));
  const hits = items.filter(el => (el.textContent || '').trim().includes(WANT));
  if (hits.length !== 1) return { ok: false, reason: 'not_unique', hitCount: hits.length };
  hits[0].click();
  return { ok: true, wasSelected: String(hits[0].className).includes('selected') };
})()
"""

WATCH_JS = r"""
(() => {
  const drawer = document.querySelector('.sku-decouple-drawer-container');
  const wrapper = document.querySelector('.sell-sku-table-wrapper-new');
  return {
    drawerOpen: Boolean(drawer && drawer.getBoundingClientRect().height > 0),
    tables: wrapper ? wrapper.querySelectorAll('table').length : -1,
    wrapperText: wrapper ? (wrapper.textContent || '').trim().slice(0, 60) : null,
    props: Array.from(document.querySelectorAll('.sku-decouple-drawer-container .prop-item'))
      .map(el => ({ text: (el.textContent || '').trim().slice(0, 12),
                    selected: String(el.className).includes('selected') })),
    blocks: Array.from(document.querySelectorAll('.sku-decouple-drawer-container .common-wrap'))
      .map(w => {
        const h = w.querySelector('.header');
        const t = h ? (h.textContent || '').trim() : '';
        const m = t.match(/\((\d+)\)/);
        return { header: t.slice(0, 20), count: m ? Number(m[1]) : null };
      }),
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
    parser.add_argument("--prop", default="颜色分类")
    parser.add_argument("--seconds", type=int, default=12)
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
        start = client.evaluate(WATCH_JS)
        print("起始：抽屉={} 表格数={}".format(start["drawerOpen"], start["tables"]))
        print("  属性：{}".format(json.dumps(start["props"], ensure_ascii=False)))
        print("  区块：{}".format(json.dumps(start["blocks"], ensure_ascii=False)))
        if not start["drawerOpen"]:
            print("抽屉没开着——先跑 create-sku-specs.py")
            return 1

        print()
        print("── 取消勾选 {!r} ──".format(args.prop))
        deselected = client.evaluate(DESELECT_JS.replace("__WANT__", json.dumps(args.prop, ensure_ascii=False)))
        print("  {}".format(json.dumps(deselected, ensure_ascii=False)))
        time.sleep(2.0)
        after_deselect = client.evaluate(WATCH_JS)
        print("  属性：{}".format(json.dumps(after_deselect["props"], ensure_ascii=False)))

        print()
        print("── 再点「确认创建」 ──")
        clicked = client.evaluate(CONFIRM_JS)
        print("  {}".format(json.dumps(clicked, ensure_ascii=False)))

        samples = []
        print()
        print("  {:>3}  {:<8} {:<7} {}".format("t", "抽屉", "表格数", "区块"))
        print("  " + "-" * 66)
        for second in range(args.seconds):
            time.sleep(1.0)
            state = client.evaluate(WATCH_JS)
            samples.append({"t": second + 1, "state": state})
            print("  {:>3}  {:<8} {:<7} {}".format(
                second + 1, str(state["drawerOpen"]), str(state["tables"]),
                json.dumps([b["count"] for b in state["blocks"]], ensure_ascii=False)))
            if not state["drawerOpen"] or state["tables"] > 0:
                print("      ↑ 出现变化")
                break

    final = samples[-1]["state"] if samples else {}
    succeeded = (not final.get("drawerOpen")) or final.get("tables", 0) > 0
    print()
    print("==== 结论 ====")
    print("  取消勾选后点击：{}".format("成功（抽屉关闭或表格出现）" if succeeded else "仍无变化"))
    print("  → 假设「另一个属性为空导致校验失败」{}".format("成立" if succeeded else "不成立"))

    TMP_DIR.mkdir(parents=True, exist_ok=True)
    out = TMP_DIR / "sku-deselect-prop-{}.json".format(datetime.now().strftime("%Y%m%d%H%M%S"))
    out.write_text(json.dumps({
        "captured_at": datetime.now().isoformat(timespec="seconds"),
        "never_did": ["保存草稿", "提交宝贝信息", "上传图片"],
        "start": start,
        "deselected": deselected,
        "after_deselect": after_deselect,
        "clicked": clicked,
        "samples": samples,
        "hypothesis_held": succeeded,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print()
    print("产物：{}".format(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

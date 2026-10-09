# -*- coding: utf-8 -*-
"""勘察：规格抽屉（``.sku-decouple-drawer``）内部结构。

上一轮拿到了抽屉与底部按钮，但没看清「属性行 + 规格值输入」怎么组织。
本脚本重新打开抽屉，逐层读内部结构，**不点任何确认/创建按钮**。

用法::

    python taobao-publisher/scripts/probe-sku-drawer-inner.py --address 127.0.0.1:9502
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

OPEN_JS = """
(() => {
  const TEXT = '+ 创建规格';
  const btns = Array.from(document.querySelectorAll('button'))
    .filter(b => (b.textContent || '').trim() === TEXT);
  if (btns.length !== 1) return { ok: false, hitCount: btns.length };
  btns[0].click();
  return { ok: true };
})()
"""

INNER_JS = r"""
(() => {
  const drawer = document.querySelector('.sku-decouple-drawer-container');
  if (!drawer) return { found: false };

  const describe = (el) => ({
    tag: el.tagName.toLowerCase(),
    className: typeof el.className === 'string' ? el.className.slice(0, 100) : '',
    text: (el.children.length === 0 ? (el.textContent || '').trim() : '').slice(0, 40),
    childCount: el.children.length,
    inputs: el.querySelectorAll('input,textarea,[role="combobox"]').length,
    buttons: Array.from(el.querySelectorAll('button')).length,
  });

  // 逐层走一层，看主干
  const rows = [];
  const walk = (el, depth) => {
    if (depth > 3 || rows.length > 60) return;
    for (const kid of Array.from(el.children)) {
      rows.push({ depth, ...describe(kid) });
      walk(kid, depth + 1);
    }
  };
  walk(drawer, 0);

  // 属性行：实测底纹里有「颜色分类」「尺码」
  const attrRows = Array.from(drawer.querySelectorAll('div'))
    .filter(el => {
      const t = (el.textContent || '').trim();
      return t.length > 0 && t.length <= 12 &&
        ['颜色', '颜色分类', '尺码'].some(k => t === k || t.startsWith(k)) &&
        el.children.length <= 3;
    })
    .slice(0, 6)
    .map(el => {
      let node = el, chain = [];
      for (let i = 0; i < 4 && node; i++) {
        chain.push({ tag: node.tagName.toLowerCase(),
                     className: typeof node.className === 'string' ? node.className.slice(0, 90) : '',
                     childCount: node.children.length,
                     inputs: node.querySelectorAll('input,[role="combobox"]').length });
        node = node.parentElement;
      }
      return { text: (el.textContent || '').trim().slice(0, 16), chain };
    });

  // 抽屉里的全部输入控件
  const inputs = Array.from(drawer.querySelectorAll('input,textarea,[role="combobox"]'))
    .filter(el => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; })
    .slice(0, 14)
    .map(el => ({
      tag: el.tagName.toLowerCase(),
      role: el.getAttribute('role') || '',
      placeholder: el.getAttribute('placeholder') || '',
      className: typeof el.className === 'string' ? el.className.slice(0, 70) : '',
    }));

  return {
    found: true,
    drawerClass: String(drawer.className).slice(0, 110),
    structure: rows,
    attrRows,
    inputs,
  };
})()
"""

CLOSE_JS = """
(() => {
  const btns = Array.from(document.querySelectorAll('button'));
  const cancel = btns.find(b => ['取消', '关闭'].includes((b.textContent || '').trim()));
  if (cancel) { cancel.click(); return 'clicked_cancel'; }
  document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', keyCode: 27, bubbles: true }));
  return 'escape';
})()
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--address", default="127.0.0.1:9502")
    parser.add_argument("--wait", type=float, default=3.0)
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

    with page.PageClient.connect(target["webSocketDebuggerUrl"]) as client:
        opened = client.evaluate(OPEN_JS)
        if not isinstance(opened, dict) or not opened.get("ok"):
            print("打开抽屉失败：{}".format(json.dumps(opened, ensure_ascii=False)))
            return 1
        time.sleep(args.wait)
        data = client.evaluate(INNER_JS)
        closed = client.evaluate(CLOSE_JS)

    if not isinstance(data, dict) or not data.get("found"):
        print("没找到抽屉容器 .sku-decouple-drawer-container")
        return 1

    print("抽屉容器：{}".format(data["drawerClass"]))
    print()
    print("==== 主干结构（前 60 个节点）====")
    print("  {:>2} {:<6} {:<6} {:<6} {:<42} {}".format("d", "tag", "childs", "inputs", "className", "ownText"))
    for row in data["structure"]:
        print("  {:>2} {:<6} {:<6} {:<6} {:<42} {!r}".format(
            row["depth"], row["tag"], row["childCount"], row["inputs"],
            row["className"][:40], row["text"][:30]))
    print()
    print("==== 属性行候选 ====")
    for item in data["attrRows"]:
        print("  {!r}".format(item["text"]))
        for level in item["chain"]:
            print("      <{}> childs={} inputs={} class={}".format(
                level["tag"], level["childCount"], level["inputs"], level["className"][:70]))
    print()
    print("==== 抽屉内可见输入控件 ====")
    for item in data["inputs"]:
        print("  <{}> role={:<10} ph={!r:<22} class={}".format(
            item["tag"], item["role"] or "-", item["placeholder"][:20], item["className"][:56]))
    print()
    print("关闭动作：{}".format(closed))

    TMP_DIR.mkdir(parents=True, exist_ok=True)
    out = TMP_DIR / "sku-drawer-inner-{}.json".format(datetime.now().strftime("%Y%m%d%H%M%S"))
    out.write_text(json.dumps({
        "captured_at": datetime.now().isoformat(timespec="seconds"),
        "clicked_confirm": False,
        "close_action": closed,
        **data,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print()
    print("产物：{}".format(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

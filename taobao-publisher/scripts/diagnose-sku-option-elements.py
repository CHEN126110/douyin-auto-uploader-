# -*- coding: utf-8 -*-
"""诊断：规格值下拉弹层里**到底是什么元素**在承载候选。

上一轮：弹层可见（200x349），但 `.next-menu-item` / `[role=option]` / `li` 都是 0 个。
而更早一次用更宽的选择器读到了 14 个候选——说明候选元素既不是 li 也不是 option。

本脚本把弹层连同**每一层的类名与文本**dump 出来，由结构说话。
**只读**：只点开下拉，不选值，结束前取消。

用法::

    python taobao-publisher/scripts/diagnose-sku-option-elements.py --address 127.0.0.1:9502
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

OPEN_DRAWER_JS = """
(() => {
  const btns = Array.from(document.querySelectorAll('button'))
    .filter(b => (b.textContent || '').trim() === '+ 创建规格');
  if (btns.length !== 1) return { ok: false, hitCount: btns.length };
  btns[0].click();
  return { ok: true };
})()
"""

CLICK_VALUE_JS = r"""
(() => {
  const drawer = document.querySelector('.sku-decouple-drawer-container');
  if (!drawer) return { ok: false, reason: 'no_drawer' };
  const block = Array.from(drawer.querySelectorAll('.common-wrap')).find(w => {
    const h = w.querySelector('.header');
    return h && (h.textContent || '').includes('尺码');
  });
  if (!block) return { ok: false, reason: 'no_block' };
  const inputs = Array.from(block.querySelectorAll('input,[role="combobox"]')).filter(el => {
    const r = el.getBoundingClientRect();
    if (r.height === 0) return false;
    const cls = typeof el.className === 'string' ? el.className : '';
    return !cls.includes('checkbox') && !cls.includes('radio');
  });
  if (!inputs.length) return { ok: false, reason: 'no_input' };
  inputs[0].click();
  inputs[0].focus();
  return { ok: true };
})()
"""

DUMP_JS = r"""
(() => {
  const popup = Array.from(document.querySelectorAll('.next-select-popup-wrap'))
    .filter(e => e.getBoundingClientRect().height > 0)[0];
  if (!popup) return { found: false };

  const rows = [];
  const walk = (el, depth) => {
    if (depth > 5 || rows.length > 60) return;
    for (const kid of Array.from(el.children).slice(0, 12)) {
      const cls = typeof kid.className === 'string' ? kid.className : '';
      rows.push({
        depth,
        tag: kid.tagName.toLowerCase(),
        className: cls.slice(0, 90),
        childCount: kid.children.length,
        ownText: kid.children.length === 0 ? (kid.textContent || '').trim().slice(0, 26) : '',
        hasReact: Object.keys(kid).some(k => k.startsWith('__react')),
      });
      walk(kid, depth + 1);
    }
  };
  walk(popup, 0);

  // 叶子文本元素（最可能就是候选项）
  const leaves = Array.from(popup.querySelectorAll('*'))
    .filter(el => el.children.length === 0 && (el.textContent || '').trim())
    .slice(0, 18)
    .map(el => ({
      tag: el.tagName.toLowerCase(),
      className: typeof el.className === 'string' ? el.className.slice(0, 70) : '',
      text: (el.textContent || '').trim().slice(0, 26),
      parentTag: el.parentElement ? el.parentElement.tagName.toLowerCase() : '',
      parentClass: el.parentElement && typeof el.parentElement.className === 'string'
        ? el.parentElement.className.slice(0, 70) : '',
    }));

  return { found: true, popupClass: String(popup.className).slice(0, 110), rows, leaves };
})()
"""

CLOSE_JS = """
(() => {
  document.body.click();
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
    parser.add_argument("--wait", type=float, default=2.5)
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
        if not (client.evaluate(OPEN_DRAWER_JS) or {}).get("ok"):
            print("开抽屉失败")
            return 1
        time.sleep(args.wait)
        if not (client.evaluate(CLICK_VALUE_JS) or {}).get("ok"):
            print("点值输入失败")
            client.evaluate(CLOSE_JS)
            return 1
        time.sleep(args.wait)
        data = client.evaluate(DUMP_JS)
        closed = client.evaluate(CLOSE_JS)

    if not isinstance(data, dict) or not data.get("found"):
        print("没有可见的 .next-select-popup-wrap")
        return 1

    print("弹层 class：{}".format(data["popupClass"]))
    print()
    print("==== 逐层结构 ====")
    print("  {:>2} {:<6} {:<6} {:<40} {}".format("d", "tag", "childs", "className", "ownText"))
    for row in data["rows"]:
        print("  {:>2} {:<6} {:<6} {:<40} {!r}".format(
            row["depth"], row["tag"], row["childCount"], row["className"][:38], row["ownText"][:24]))
    print()
    print("==== 叶子文本元素（最可能是候选）====")
    for item in data["leaves"]:
        print("  <{}> {:<40} {!r}".format(item["tag"], item["className"][:38], item["text"][:24]))
        print("        父: <{}> {}".format(item["parentTag"], item["parentClass"][:52]))
    print()
    print("关闭动作：{}".format(closed))

    TMP_DIR.mkdir(parents=True, exist_ok=True)
    out = TMP_DIR / "sku-option-elements-{}.json".format(datetime.now().strftime("%Y%m%d%H%M%S"))
    out.write_text(json.dumps({
        "captured_at": datetime.now().isoformat(timespec="seconds"),
        "selected_nothing": True,
        "close_action": closed,
        **data,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print("产物：{}".format(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

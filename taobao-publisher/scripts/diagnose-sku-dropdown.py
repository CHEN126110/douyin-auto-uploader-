# -*- coding: utf-8 -*-
"""诊断：点开「尺码」值输入后，**所有可见弹层**分别在哪、有什么。

上一版探测 `shown: []`，而更早一次同样点击读到了 14 个候选。差别只可能在我
筛选弹层的方式上——所以这次不做任何过滤，把页面上**全部**可见 overlay
连同它们的选择器路径、父链、候选数一起列出来。

**纯只读**（只点开下拉，不选值），结束前点「取消」。

用法::

    python taobao-publisher/scripts/diagnose-sku-dropdown.py --address 127.0.0.1:9502
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
  const chain = (el) => {
    const parts = [];
    let node = el;
    for (let i = 0; i < 4 && node; i++) {
      const cls = typeof node.className === 'string' ? node.className.trim().split(/\s+/)[0] : '';
      parts.push(node.tagName.toLowerCase() + (cls ? '.' + cls : ''));
      node = node.parentElement;
    }
    return parts.join(' < ');
  };

  const out = [];
  // 不过滤，全部 overlay 都列出来
  for (const el of Array.from(document.querySelectorAll('.next-overlay-inner, .next-select-popup-wrap'))) {
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) continue;
    const items = el.querySelectorAll('.next-menu-item, [role="option"], li');
    out.push({
      className: String(el.className).slice(0, 110),
      chain: chain(el),
      width: Math.round(r.width),
      height: Math.round(r.height),
      menuItemCount: items.length,
      sample: Array.from(items).slice(0, 10).map(i => (i.textContent || '').trim()).filter(Boolean),
      insideDrawer: Boolean(el.closest('.sku-decouple-drawer-container')),
    });
  }
  return { overlays: out, count: out.length };
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
        print("页面：{}".format(str(client.evaluate("location.href.split('?')[0]"))[:90]))
        opened = client.evaluate(OPEN_DRAWER_JS)
        print("开抽屉：{}".format(json.dumps(opened, ensure_ascii=False)))
        if not isinstance(opened, dict) or not opened.get("ok"):
            return 1
        time.sleep(args.wait)

        clicked = client.evaluate(CLICK_VALUE_JS)
        print("点尺码输入：{}".format(json.dumps(clicked, ensure_ascii=False)))
        if not isinstance(clicked, dict) or not clicked.get("ok"):
            client.evaluate(CLOSE_JS)
            return 1
        time.sleep(args.wait)

        dump = client.evaluate(DUMP_JS)
        closed = client.evaluate(CLOSE_JS)

    print()
    print("==== 可见 overlay {} 个 ====".format((dump or {}).get("count")))
    for item in (dump or {}).get("overlays", []):
        print("  {}x{}  menuItem={}  insideDrawer={}".format(
            item["width"], item["height"], item["menuItemCount"], item["insideDrawer"]))
        print("      class={}".format(item["className"][:100]))
        print("      chain={}".format(item["chain"][:110]))
        if item["sample"]:
            print("      候选={}".format(json.dumps(item["sample"][:10], ensure_ascii=False)))
    print()
    print("关闭动作：{}".format(closed))

    TMP_DIR.mkdir(parents=True, exist_ok=True)
    out = TMP_DIR / "sku-dropdown-diagnose-{}.json".format(datetime.now().strftime("%Y%m%d%H%M%S"))
    out.write_text(json.dumps({
        "captured_at": datetime.now().isoformat(timespec="seconds"),
        "selected_nothing": True,
        "close_action": closed,
        **dump,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print("产物：{}".format(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

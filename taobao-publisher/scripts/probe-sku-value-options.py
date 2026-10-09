# -*- coding: utf-8 -*-
"""勘察：规格值输入框**聚焦之后**是否弹出候选项。

上一轮：往「主色(必选)」里输入并回车，计数没变（仍是 0）。说明「加入」不是回车。
实测该输入可能是**标准色板/标准属性**，必须从候选项里选，不能自由文本。

本脚本只聚焦输入框并读弹出的候选列表，**不选任何值、不点确认**。

用法::

    python taobao-publisher/scripts/probe-sku-value-options.py --address 127.0.0.1:9502
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
  const btns = Array.from(document.querySelectorAll('button'))
    .filter(b => (b.textContent || '').trim() === '+ 创建规格');
  if (btns.length !== 1) return { ok: false, hitCount: btns.length };
  btns[0].click();
  return { ok: true };
})()
"""

#: 聚焦「尺码」块的 combobox 并点开（它是 role=combobox，最可能带候选值）。
FOCUS_JS = r"""
(() => {
  const WHICH = __WHICH__;
  const drawer = document.querySelector('.sku-decouple-drawer-container');
  if (!drawer) return { ok: false, reason: 'no_drawer' };
  const wraps = Array.from(drawer.querySelectorAll('.common-wrap'));
  const block = wraps.find(w => {
    const h = w.querySelector('.header');
    return h && (h.textContent || '').includes(WHICH);
  });
  if (!block) return { ok: false, reason: 'no_block', available: wraps.map(w => {
    const h = w.querySelector('.header'); return h ? (h.textContent || '').trim().slice(0, 16) : '';
  }) };
  const inputs = Array.from(block.querySelectorAll('input,[role="combobox"]'))
    .filter(el => {
      const r = el.getBoundingClientRect();
      if (r.height === 0) return false;
      const cls = typeof el.className === 'string' ? el.className : '';
      return !cls.includes('checkbox') && !cls.includes('radio');
    });
  if (!inputs.length) return { ok: false, reason: 'no_input' };
  const el = inputs[0];
  el.click();
  el.focus();
  return { ok: true, placeholder: el.getAttribute('placeholder') || '', role: el.getAttribute('role') || '' };
})()
"""

#: 读所有可见弹层里的候选项。
OPTIONS_JS = r"""
(() => {
  const overlays = Array.from(document.querySelectorAll(
    '.next-overlay-inner, .next-select-popup-wrap, .next-menu, [class*="popup"]'))
    .filter(e => e.getBoundingClientRect().height > 0)
    .map(e => {
      const texts = Array.from(e.querySelectorAll('li, .next-menu-item-text, .next-tag, [class*="option"], [class*="item"]'))
        .map(x => (x.textContent || '').trim())
        .filter(t => t && t.length <= 20);
      return {
        className: typeof e.className === 'string' ? e.className.slice(0, 110) : '',
        height: Math.round(e.getBoundingClientRect().height),
        itemCount: texts.length,
        sample: [...new Set(texts)].slice(0, 20),
      };
    });
  return { overlayCount: overlays.length, overlays };
})()
"""

CLOSE_JS = """
(() => {
  document.body.click();
  const btns = Array.from(document.querySelectorAll('button'));
  const cancel = btns.find(b => ['取消', '关闭'].includes((b.textContent || '').trim()));
  if (cancel) { cancel.click(); return 'clicked_cancel'; }
  return 'body_click';
})()
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--address", default="127.0.0.1:9502")
    parser.add_argument("--which", default="尺码")
    parser.add_argument("--wait", type=float, default=2.0)
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
            print("打开抽屉失败")
            return 1
        time.sleep(args.wait)

        focused = client.evaluate(FOCUS_JS.replace("__WHICH__", json.dumps(args.which, ensure_ascii=False)))
        print("聚焦 {!r} 块：{}".format(args.which, json.dumps(focused, ensure_ascii=False)[:220]))
        if not isinstance(focused, dict) or not focused.get("ok"):
            client.evaluate(CLOSE_JS)
            return 1

        time.sleep(args.wait)
        options = client.evaluate(OPTIONS_JS)
        closed = client.evaluate(CLOSE_JS)

    print()
    print("可见弹层：{} 个".format((options or {}).get("overlayCount")))
    for item in (options or {}).get("overlays", []):
        print("  h={} items={} class={}".format(item["height"], item["itemCount"], item["className"][:70]))
        if item["sample"]:
            print("      候选：{}".format(json.dumps(item["sample"][:14], ensure_ascii=False)))
    print()
    print("关闭动作：{}".format(closed))

    TMP_DIR.mkdir(parents=True, exist_ok=True)
    out = TMP_DIR / "sku-value-options-{}.json".format(datetime.now().strftime("%Y%m%d%H%M%S"))
    out.write_text(json.dumps({
        "captured_at": datetime.now().isoformat(timespec="seconds"),
        "clicked_confirm": False,
        "close_action": closed,
        "focused": focused,
        "options": options,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print()
    print("产物：{}".format(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

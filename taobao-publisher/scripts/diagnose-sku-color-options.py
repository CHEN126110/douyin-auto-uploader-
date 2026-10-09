# -*- coding: utf-8 -*-
"""诊断：「颜色分类」块的值输入是什么形态、候选有哪些。

「尺码」块已经实证：点开 → ``.options-item`` 候选 → 点中 → 计数 +1。
「颜色分类」块的输入框 placeholder 是「主色(必选)」，还多一个「备注(可选)」，
形态可能不同（淘宝的主色通常是**色板**而不是文字列表）。

**只读**：点开下拉读候选，不选值，结束前取消。

用法::

    python taobao-publisher/scripts/diagnose-sku-color-options.py --address 127.0.0.1:9502
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

CLICK_COLOR_JS = r"""
(() => {
  const drawer = document.querySelector('.sku-decouple-drawer-container');
  if (!drawer) return { ok: false, reason: 'no_drawer' };
  const block = Array.from(drawer.querySelectorAll('.common-wrap')).find(w => {
    const h = w.querySelector('.header');
    return h && (h.textContent || '').includes('颜色');
  });
  if (!block) return { ok: false, reason: 'no_block' };
  const inputs = Array.from(block.querySelectorAll('input,[role="combobox"]')).filter(el => {
    const r = el.getBoundingClientRect();
    if (r.height === 0) return false;
    const cls = typeof el.className === 'string' ? el.className : '';
    return !cls.includes('checkbox') && !cls.includes('radio');
  });
  if (!inputs.length) return { ok: false, reason: 'no_input' };
  // 逐个试：先点 placeholder 含「主色」的那个
  const target = inputs.find(el => (el.getAttribute('placeholder') || '').includes('主色')) || inputs[0];
  target.click();
  target.focus();
  return {
    ok: true,
    placeholder: target.getAttribute('placeholder') || '',
    role: target.getAttribute('role') || '',
    allPlaceholders: inputs.map(el => el.getAttribute('placeholder') || ''),
  };
})()
"""

#: 读「颜色分类」块里所有可交互元素，看它到底是色板还是列表。
INSPECT_JS = r"""
(() => {
  const drawer = document.querySelector('.sku-decouple-drawer-container');
  if (!drawer) return { found: false };
  const block = Array.from(drawer.querySelectorAll('.common-wrap')).find(w => {
    const h = w.querySelector('.header');
    return h && (h.textContent || '').includes('颜色');
  });
  if (!block) return { found: false, reason: 'no_block' };

  const describe = (el) => ({
    tag: el.tagName.toLowerCase(),
    className: typeof el.className === 'string' ? el.className.slice(0, 80) : '',
    text: el.children.length === 0 ? (el.textContent || '').trim().slice(0, 24) : '',
    visible: el.getBoundingClientRect().height > 0,
  });

  // 块内所有带 class 的元素（去重后按类名分组）
  const byClass = {};
  for (const el of Array.from(block.querySelectorAll('*'))) {
    const cls = typeof el.className === 'string' ? el.className.trim() : '';
    if (!cls) continue;
    const first = cls.split(/\s+/)[0];
    byClass[first] = (byClass[first] || 0) + 1;
  }

  // 块内可点元素
  const clickable = Array.from(block.querySelectorAll(
    'button, [class*="item"], [class*="color"], [class*="swatch"], [class*="tag"]'))
    .slice(0, 20).map(describe);

  return { found: true, blockClass: String(block.className).slice(0, 80), byClass, clickable };
})()
"""

#: 页面上所有可见弹层里的候选。
OPTIONS_JS = r"""
(() => {
  const out = [];
  for (const root of Array.from(document.querySelectorAll('.next-select-popup-wrap, .next-overlay-inner'))) {
    const r = root.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) continue;
    if (root.classList.contains('sku-decouple-drawer')) continue;
    const items = Array.from(root.querySelectorAll('.options-item, .next-menu-item, [role="option"]'));
    out.push({
      className: String(root.className).slice(0, 100),
      width: Math.round(r.width),
      height: Math.round(r.height),
      itemCount: items.length,
      sample: items.slice(0, 16).map(i => {
        const t = i.querySelector('.info-content') || i;
        return (t.textContent || '').trim().slice(0, 24);
      }).filter(Boolean),
    });
  }
  return { overlays: out };
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

        inspect = client.evaluate(INSPECT_JS)
        print("==== 颜色分类块结构 ====")
        if isinstance(inspect, dict) and inspect.get("found"):
            print("  块 class：{}".format(inspect.get("blockClass")))
            print("  类名分布：{}".format(json.dumps(inspect.get("byClass"), ensure_ascii=False)[:400]))
            print("  可点元素：")
            for item in (inspect.get("clickable") or [])[:10]:
                print("    <{}> {:<40} vis={} {!r}".format(
                    item["tag"], item["className"][:38], item["visible"], item["text"][:20]))

        clicked = client.evaluate(CLICK_COLOR_JS)
        print()
        print("点颜色值输入：{}".format(json.dumps(clicked, ensure_ascii=False)[:220]))
        time.sleep(args.wait)

        options = client.evaluate(OPTIONS_JS)
        closed = client.evaluate(CLOSE_JS)

    print()
    print("==== 可见弹层 ====")
    for item in (options or {}).get("overlays", []):
        print("  {}x{} items={} class={}".format(
            item["width"], item["height"], item["itemCount"], item["className"][:70]))
        if item["sample"]:
            print("      候选：{}".format(json.dumps(item["sample"][:14], ensure_ascii=False)))
    print()
    print("关闭动作：{}".format(closed))

    TMP_DIR.mkdir(parents=True, exist_ok=True)
    out = TMP_DIR / "sku-color-options-{}.json".format(datetime.now().strftime("%Y%m%d%H%M%S"))
    out.write_text(json.dumps({
        "captured_at": datetime.now().isoformat(timespec="seconds"),
        "selected_nothing": True,
        "close_action": closed,
        "inspect": inspect,
        "clicked": clicked,
        "options": options,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print("产物：{}".format(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

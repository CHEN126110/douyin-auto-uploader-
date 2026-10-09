# -*- coding: utf-8 -*-
"""勘察：类目页「品牌」下拉的选项结构。

背景：选完类目后「确认，下一步」仍 disabled，页面提示必须先选品牌
（E-077）。这是 `select_category` 的最后一个未知点。

边界：只**展开下拉**（纯前端动作，不选任何值），读选项列表后按 Esc 收起。

用法::

    python taobao-publisher/scripts/probe-brand-dropdown.py --address 127.0.0.1:9502
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

from taobao_publish import locating, page  # noqa: E402

TMP_DIR = SUBPROJECT / "tmp"

#: 展开品牌下拉：点行内那个 combobox。
OPEN_JS = """
(() => {
  const items = Array.from(document.querySelectorAll('.sell-catProp-item-common'));
  const hit = items.filter(item => {
    const label = item.querySelector('label');
    return label && (label.textContent || '').trim() === '品牌';
  });
  if (hit.length !== 1) return { ok: false, reason: hit.length === 0 ? 'not_found' : 'ambiguous', hitCount: hit.length };
  const control = hit[0].querySelector('input[role="combobox"], input');
  if (!control) return { ok: false, reason: 'no_control' };
  control.click();
  control.focus();
  return { ok: true, placeholder: control.getAttribute('placeholder') || '' };
})()
"""

#: 读下拉选项。Fusion 的选项通常在 .next-menu-item 或 [role=option] 上。
OPTIONS_JS = """
(() => {
  const selectors = ['.next-menu-item', '[role="option"]', '.next-select-menu .next-menu-item',
                     '.next-overlay-inner li', '.next-tree-node-label'];
  const out = {};
  for (const sel of selectors) {
    const els = Array.from(document.querySelectorAll(sel))
      .filter(e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; });
    out[sel] = {
      count: els.length,
      sample: els.slice(0, 10).map(e => ({
        text: (e.textContent || '').trim().slice(0, 26),
        className: typeof e.className === 'string' ? e.className.slice(0, 80) : '',
        role: e.getAttribute('role') || '',
      })),
    };
  }
  const menus = Array.from(document.querySelectorAll('.next-overlay-inner, .next-menu'))
    .filter(e => e.getBoundingClientRect().height > 0)
    .map(e => ({
      className: typeof e.className === 'string' ? e.className.slice(0, 90) : '',
      textStart: (e.textContent || '').trim().slice(0, 70),
      itemCount: e.querySelectorAll('li, [role="option"]').length,
    }));
  return { bySelector: out, visibleMenus: menus };
})()
"""

CLOSE_JS = """
(() => {
  document.body.click();
  const esc = new KeyboardEvent('keydown', { key: 'Escape', keyCode: 27, bubbles: true });
  document.dispatchEvent(esc);
  return 'closed';
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
        print("页面：{}".format(str(client.evaluate("location.href.split('?')[0]"))[:90]))
        print("已选类目：{}".format(
            json.dumps(client.evaluate(
                "Array.from(document.querySelectorAll('.category-item.selected')).map(e=>(e.textContent||'').trim())"
            ), ensure_ascii=False)))

        opened = client.evaluate(OPEN_JS)
        print()
        print("展开品牌下拉：{}".format(json.dumps(opened, ensure_ascii=False)[:200]))
        if not isinstance(opened, dict) or not opened.get("ok"):
            return 1

        time.sleep(args.wait)
        options = client.evaluate(OPTIONS_JS)
        client.evaluate(CLOSE_JS)

    if not isinstance(options, dict):
        print("没读到选项")
        return 1

    print()
    print("==== 可见的下拉菜单 ====")
    for menu in options.get("visibleMenus") or []:
        print("  <{}> items={} text={!r}".format(
            menu["className"][:60], menu["itemCount"], menu["textStart"][:50]))
    if not options.get("visibleMenus"):
        print("  （没有可见菜单）")

    print()
    print("==== 按选择器统计候选选项 ====")
    for sel, info in (options.get("bySelector") or {}).items():
        print("  {:<42} 可见 {} 个".format(sel, info["count"]))
        for sample in info["sample"][:6]:
            print("        {!r:<28} role={} class={}".format(
                sample["text"][:26], sample["role"] or "-", sample["className"][:50]))

    TMP_DIR.mkdir(parents=True, exist_ok=True)
    out = TMP_DIR / "brand-dropdown-{}.json".format(datetime.now().strftime("%Y%m%d%H%M%S"))
    out.write_text(json.dumps({
        "captured_at": datetime.now().isoformat(timespec="seconds"),
        "selected_nothing": True,
        "not_done": ["选择品牌值", "确认下一步", "保存草稿", "提交"],
        "opened": opened,
        **options,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print()
    print("产物：{}".format(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

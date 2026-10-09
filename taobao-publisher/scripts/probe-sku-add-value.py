# -*- coding: utf-8 -*-
"""交互勘察：在规格抽屉里**加一个规格值**，看它怎么变成已选项。

只做「输入值 + 回车」，然后读回计数（header 上的 ``(N)``）。
**不点「确认创建」**，结束前点「取消」丢弃。因此不会创建任何规格、不产生草稿。

为什么先做这一步：`fill_skus` 的核心就是「把 spec_values 填进抽屉」。
值的加入机制（回车？点候选？失焦？）必须实证，不能猜。

用法::

    python taobao-publisher/scripts/probe-sku-add-value.py --address 127.0.0.1:9502 --value 黑色
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

#: 读每个属性块的 header 计数与已选值标签。
STATE_JS = r"""
(() => {
  const drawer = document.querySelector('.sku-decouple-drawer-container');
  if (!drawer) return { found: false };
  const wraps = Array.from(drawer.querySelectorAll('.common-wrap'));
  return {
    found: true,
    blocks: wraps.map(w => {
      const header = w.querySelector('.header');
      const headerText = header ? (header.textContent || '').trim() : '';
      const tags = Array.from(w.querySelectorAll('.next-tag, [class*="tag-body"], [class*="value-tag"]'))
        .map(el => (el.textContent || '').trim()).filter(Boolean).slice(0, 10);
      const inputs = Array.from(w.querySelectorAll('input,textarea,[role="combobox"]'))
        .filter(el => el.getBoundingClientRect().height > 0)
        .map(el => ({ ph: el.getAttribute('placeholder') || '',
                      cls: typeof el.className === 'string' ? el.className.slice(0, 50) : '',
                      value: String(el.value || '').slice(0, 20) }));
      // header 里的计数
      const m = headerText.match(/\((\d+)\)/);
      return { headerText: headerText.slice(0, 40), count: m ? Number(m[1]) : null, tags, inputs };
    }),
    footerButtons: Array.from(drawer.querySelectorAll('.sku-decouple-drawer-footer button'))
      .map(b => (b.textContent || '').trim()).filter(Boolean),
  };
})()
"""

#: 往「颜色分类」块的主色输入里填值并回车。
TYPE_JS = r"""
(() => {
  const VALUE = __VALUE__;
  const drawer = document.querySelector('.sku-decouple-drawer-container');
  if (!drawer) return { ok: false, reason: 'no_drawer' };
  const wraps = Array.from(drawer.querySelectorAll('.common-wrap'));
  // 挑「颜色分类」那一块；退一步挑第一块
  let block = wraps.find(w => {
    const h = w.querySelector('.header');
    return h && (h.textContent || '').includes('颜色');
  }) || wraps[0];
  if (!block) return { ok: false, reason: 'no_block' };

  const inputs = Array.from(block.querySelectorAll('input,textarea,[role="combobox"]'))
    .filter(el => {
      const r = el.getBoundingClientRect();
      if (r.height === 0) return false;
      const cls = typeof el.className === 'string' ? el.className : '';
      return !cls.includes('checkbox') && !cls.includes('radio');
    });
  if (!inputs.length) return { ok: false, reason: 'no_value_input' };
  const input = inputs[0];

  const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
  setter.call(input, VALUE);
  input.dispatchEvent(new Event('input', { bubbles: true }));
  input.dispatchEvent(new Event('change', { bubbles: true }));
  input.focus();

  // 回车是最常见的「确认加入」手势
  for (const type of ['keydown', 'keypress', 'keyup']) {
    input.dispatchEvent(new KeyboardEvent(type, {
      key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true, cancelable: true,
    }));
  }
  return { ok: true, typedInto: input.getAttribute('placeholder') || '(无 placeholder)' };
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
    parser.add_argument("--value", default="黑色")
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

        before = client.evaluate(STATE_JS)
        print("==== 加值前 ====")
        for block in (before or {}).get("blocks", []):
            print("  {!r} count={} tags={} inputs={}".format(
                block["headerText"], block["count"], block["tags"],
                [i["ph"] for i in block["inputs"]]))

        print()
        print("往颜色块输入 {!r} 并回车…".format(args.value))
        typed = client.evaluate(TYPE_JS.replace("__VALUE__", json.dumps(args.value, ensure_ascii=False)))
        print("  {}".format(json.dumps(typed, ensure_ascii=False)[:180]))
        time.sleep(args.wait)

        after = client.evaluate(STATE_JS)
        print()
        print("==== 加值后 ====")
        for block in (after or {}).get("blocks", []):
            print("  {!r} count={} tags={}".format(
                block["headerText"], block["count"], block["tags"]))

        closed = client.evaluate(CLOSE_JS)

    changed = False
    if isinstance(before, dict) and isinstance(after, dict):
        b = [(x["headerText"], x["count"]) for x in before.get("blocks", [])]
        a = [(x["headerText"], x["count"]) for x in after.get("blocks", [])]
        changed = b != a

    print()
    print("计数/标签是否变化：{}".format("是" if changed else "否"))
    print("关闭动作：{}".format(closed))

    TMP_DIR.mkdir(parents=True, exist_ok=True)
    out = TMP_DIR / "sku-add-value-{}.json".format(datetime.now().strftime("%Y%m%d%H%M%S"))
    out.write_text(json.dumps({
        "captured_at": datetime.now().isoformat(timespec="seconds"),
        "value_tried": args.value,
        "clicked_confirm": False,
        "close_action": closed,
        "changed": changed,
        "before": before,
        "after": after,
        "typed": typed,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print()
    print("产物：{}".format(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

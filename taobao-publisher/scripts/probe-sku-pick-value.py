# -*- coding: utf-8 -*-
"""交互勘察：从标准候选里给「尺码」加一个规格值。

E-085/E-086 已实证：规格值**必须从标准候选项里选**，自由文本回车无效。
本脚本验证「点开值输入 → 下拉出现 → 点中候选 → 计数 +1」这条链路。

**不点「确认创建」**，结束前点「取消」丢弃。

用法::

    python taobao-publisher/scripts/probe-sku-pick-value.py --address 127.0.0.1:9502 --value "M(37-41)"
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

#: 读每个属性块的 header 计数。
STATE_JS = r"""
(() => {
  const drawer = document.querySelector('.sku-decouple-drawer-container');
  if (!drawer) return { found: false };
  return {
    found: true,
    blocks: Array.from(drawer.querySelectorAll('.common-wrap')).map(w => {
      const h = w.querySelector('.header');
      const text = h ? (h.textContent || '').trim() : '';
      const m = text.match(/\((\d+)\)/);
      return { header: text.slice(0, 30), count: m ? Number(m[1]) : null };
    }),
  };
})()
"""

#: 点开指定属性块的值输入框。
OPEN_VALUE_INPUT_JS = r"""
(() => {
  const WHICH = __WHICH__;
  const drawer = document.querySelector('.sku-decouple-drawer-container');
  if (!drawer) return { ok: false, reason: 'no_drawer' };
  const block = Array.from(drawer.querySelectorAll('.common-wrap')).find(w => {
    const h = w.querySelector('.header');
    return h && (h.textContent || '').includes(WHICH);
  });
  if (!block) return { ok: false, reason: 'no_block' };
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
  return { ok: true, placeholder: el.getAttribute('placeholder') || '',
           role: el.getAttribute('role') || '' };
})()
"""

#: 读下拉候选并点中文本精确相等的那一个。
#:
#: ⚠️ **两种「标准选择」下拉共用一套候选结构，但和运费模板下拉不同**（实测）：
#:
#: * 品牌下拉 / 规格值下拉：``.options-item`` + ``.info-content``（``.next-select-popup-wrap``）
#: * 运费模板下拉：``li.next-menu-item`` + ``.next-menu-item-text``（``.next-select-single-menu``）
#:
#: 上一版这里用 ``.next-menu-item`` / ``[role=option]`` / ``li`` 找规格候选，
#: 结果 ``hitCount: 0`` —— 而弹层其实开着、14 个候选就在眼前。
PICK_JS = r"""
(() => {
  const WANT = __WANT__;
  const OPTION = '.options-item';
  const TEXT = '.info-content';
  const roots = Array.from(document.querySelectorAll('.next-select-popup-wrap'))
    .filter(e => e.getBoundingClientRect().height > 0);
  const options = [];
  for (const root of roots) {
    for (const el of Array.from(root.querySelectorAll(OPTION))) {
      const t = el.querySelector(TEXT);
      const text = t ? (t.textContent || '').trim() : '';
      if (text) options.push({ el, text });
    }
  }
  const hits = options.filter(o => o.text === WANT);
  if (hits.length !== 1) {
    return { ok: false, reason: hits.length === 0 ? 'no_match' : 'ambiguous',
             hitCount: hits.length,
             shown: [...new Set(options.map(o => o.text))].slice(0, 20) };
  }
  hits[0].el.click();
  return { ok: true, picked: WANT };
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
    parser.add_argument("--which", default="尺码")
    parser.add_argument("--value", default="M(37-41)")
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
        print("加值前：{}".format(json.dumps((before or {}).get("blocks"), ensure_ascii=False)))

        opened_input = client.evaluate(
            OPEN_VALUE_INPUT_JS.replace("__WHICH__", json.dumps(args.which, ensure_ascii=False)))
        print("点开 {!r} 的值输入：{}".format(args.which, json.dumps(opened_input, ensure_ascii=False)[:160]))
        if not isinstance(opened_input, dict) or not opened_input.get("ok"):
            client.evaluate(CLOSE_JS)
            return 1

        time.sleep(args.wait)
        picked = client.evaluate(PICK_JS.replace("__WANT__", json.dumps(args.value, ensure_ascii=False)))
        print("选候选项 {!r}：{}".format(args.value, json.dumps(picked, ensure_ascii=False)[:280]))
        time.sleep(args.wait)

        after = client.evaluate(STATE_JS)
        print("加值后：{}".format(json.dumps((after or {}).get("blocks"), ensure_ascii=False)))

        closed = client.evaluate(CLOSE_JS)

    print()
    print("关闭动作：{}".format(closed))

    changed = (before or {}).get("blocks") != (after or {}).get("blocks")
    print("计数是否变化：{}".format("是" if changed else "否"))

    TMP_DIR.mkdir(parents=True, exist_ok=True)
    out = TMP_DIR / "sku-pick-value-{}.json".format(datetime.now().strftime("%Y%m%d%H%M%S"))
    out.write_text(json.dumps({
        "captured_at": datetime.now().isoformat(timespec="seconds"),
        "clicked_confirm": False,
        "close_action": closed,
        "which": args.which,
        "value": args.value,
        "changed": changed,
        "before": before,
        "after": after,
        "opened_input": opened_input,
        "picked": picked,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print()
    print("产物：{}".format(out))
    return 0 if changed else 1


if __name__ == "__main__":
    raise SystemExit(main())

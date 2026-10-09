# -*- coding: utf-8 -*-
"""实验：先点「+」加一行，再在新行里选值。

E-095 找到了 ``button.add``（``i.next-icon-add``）——「尺码」块里加值行的按钮。
E-094 的现象（第一个值能提交、后续不行）由此可以解释：
之前一直在**重新编辑第 1 行**，而不是新增一行。

本脚本验证完整链路：点 + → 新行出现 → 点新行输入 → 选候选 → 计数 +1。
**不点「确认创建」**。

用法::

    python taobao-publisher/scripts/experiment-sku-add-row.py --address 127.0.0.1:9502 --allow-write --value "M(37-41)"
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

#: 读计数 + 尺码块里的**行数**。
STATE_JS = r"""
(() => {
  const drawer = document.querySelector('.sku-decouple-drawer-container');
  if (!drawer) return { found: false };
  const block = Array.from(drawer.querySelectorAll('.common-wrap')).find(w => {
    const h = w.querySelector('.header');
    return h && (h.textContent || '').includes('尺码');
  });
  if (!block) return { found: false, reason: 'no_block' };
  const h = block.querySelector('.header');
  const text = h ? (h.textContent || '').trim() : '';
  const m = text.match(/\((\d+)\)/);
  const rows = Array.from(block.querySelectorAll('li'));
  return {
    found: true,
    header: text.slice(0, 30),
    count: m ? Number(m[1]) : null,
    rowCount: rows.length,
    rowInputs: rows.map(li => {
      const inp = li.querySelector('input,[role="combobox"]');
      return inp ? { value: String(inp.value || '').slice(0, 20),
                     ph: inp.getAttribute('placeholder') || '' } : null;
    }),
  };
})()
"""

#: 点尺码块里的「+」按钮。
ADD_ROW_JS = r"""
(() => {
  const drawer = document.querySelector('.sku-decouple-drawer-container');
  if (!drawer) return { ok: false, reason: 'no_drawer' };
  const block = Array.from(drawer.querySelectorAll('.common-wrap')).find(w => {
    const h = w.querySelector('.header');
    return h && (h.textContent || '').includes('尺码');
  });
  if (!block) return { ok: false, reason: 'no_block' };
  const btns = Array.from(block.querySelectorAll('button.add'));
  if (btns.length !== 1) return { ok: false, reason: 'not_unique_add', hitCount: btns.length };
  const r = btns[0].getBoundingClientRect();
  if (r.width === 0 && r.height === 0) return { ok: false, reason: 'not_visible' };
  btns[0].click();
  return { ok: true };
})()
"""

#: 点**最后一行**的值输入（新加的那行）。
OPEN_LAST_ROW_INPUT_JS = r"""
(() => {
  const drawer = document.querySelector('.sku-decouple-drawer-container');
  if (!drawer) return { ok: false, reason: 'no_drawer' };
  const block = Array.from(drawer.querySelectorAll('.common-wrap')).find(w => {
    const h = w.querySelector('.header');
    return h && (h.textContent || '').includes('尺码');
  });
  if (!block) return { ok: false, reason: 'no_block' };
  const rows = Array.from(block.querySelectorAll('li'));
  if (!rows.length) return { ok: false, reason: 'no_rows' };

  const before = document.querySelectorAll('.next-select-popup-wrap').length;
  // 从最后一行往前找，取第一个可用的值输入
  let target = null;
  for (let i = rows.length - 1; i >= 0 && !target; i--) {
    const inputs = Array.from(rows[i].querySelectorAll('input,[role="combobox"]')).filter(el => {
      const r = el.getBoundingClientRect();
      if (r.height === 0) return false;
      const cls = typeof el.className === 'string' ? el.className : '';
      return !cls.includes('checkbox') && !cls.includes('radio');
    });
    if (inputs.length) target = inputs[inputs.length - 1];
  }
  if (!target) return { ok: false, reason: 'no_input' };
  target.click();
  target.focus();
  return { ok: true, popupsBeforeClick: before,
           placeholder: target.getAttribute('placeholder') || '' };
})()
"""

PICK_LATEST_JS = r"""
(() => {
  const WANT = __WANT__;
  const pops = Array.from(document.querySelectorAll('.next-select-popup-wrap'))
    .filter(e => e.getBoundingClientRect().height > 0);
  if (!pops.length) return { ok: false, reason: 'no_popup' };
  const pop = pops[pops.length - 1];
  const options = Array.from(pop.querySelectorAll('.options-item')).map(el => {
    const t = el.querySelector('.info-content');
    return { el, text: t ? (t.textContent || '').trim() : '' };
  }).filter(o => o.text);
  const hits = options.filter(o => o.text === WANT);
  if (hits.length !== 1) {
    return { ok: false, reason: hits.length === 0 ? 'no_match' : 'ambiguous',
             hitCount: hits.length, popupCount: pops.length,
             shown: [...new Set(options.map(o => o.text))].slice(0, 20) };
  }
  hits[0].el.click();
  return { ok: true, popupCount: pops.length, picked: WANT };
})()
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--address", default="127.0.0.1:9502")
    parser.add_argument("--allow-write", action="store_true")
    parser.add_argument("--value", default="M(37-41)")
    parser.add_argument("--wait", type=float, default=2.0)
    args = parser.parse_args()

    if not args.allow_write:
        print("这会往未保存的表单里加规格值，必须显式加 --allow-write。")
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

    steps = []
    with page.PageClient.connect(target["webSocketDebuggerUrl"]) as client:
        print("页面：{}".format(str(client.evaluate("location.href.split('?')[0]"))[:90]))
        if not (client.evaluate(OPEN_DRAWER_JS) or {}).get("ok"):
            print("开抽屉失败")
            return 1
        time.sleep(max(3.0, args.wait))

        baseline = client.evaluate(STATE_JS)
        print("基线：{}".format(json.dumps(baseline, ensure_ascii=False)))
        steps.append({"step": "baseline", "state": baseline})

        print()
        print("── 步骤 1：点「+」加一行 ──")
        added = client.evaluate(ADD_ROW_JS)
        print("  {}".format(json.dumps(added, ensure_ascii=False)))
        time.sleep(args.wait)
        after_add = client.evaluate(STATE_JS)
        print("  行数/计数：{}".format(json.dumps(after_add, ensure_ascii=False)))
        steps.append({"step": "add_row", "result": added, "state": after_add})

        row_added = (after_add or {}).get("rowCount", 0) > (baseline or {}).get("rowCount", 0)

        print()
        print("── 步骤 2：点新行的值输入 ──")
        opened = client.evaluate(OPEN_LAST_ROW_INPUT_JS)
        print("  {}".format(json.dumps(opened, ensure_ascii=False)))
        time.sleep(args.wait)

        print()
        print("── 步骤 3：选候选 {!r} ──".format(args.value))
        picked = client.evaluate(PICK_LATEST_JS.replace("__WANT__", json.dumps(args.value, ensure_ascii=False)))
        print("  {}".format(json.dumps(picked, ensure_ascii=False)[:260]))
        time.sleep(args.wait)
        final = client.evaluate(STATE_JS)
        print("  计数：{}".format(json.dumps(final, ensure_ascii=False)))
        steps.append({"step": "pick", "result": picked, "state": final})

    print()
    print("==== 结论 ====")
    print("  点「+」是否加了行：{}".format("是" if row_added else "否"))
    print("  基线计数 {} → 最终计数 {}".format(
        (baseline or {}).get("count"), (final or {}).get("count")))
    committed = (final or {}).get("count") != (baseline or {}).get("count")
    print("  值是否提交：{}".format("是" if committed else "否"))

    TMP_DIR.mkdir(parents=True, exist_ok=True)
    out = TMP_DIR / "sku-add-row-{}.json".format(datetime.now().strftime("%Y%m%d%H%M%S"))
    out.write_text(json.dumps({
        "captured_at": datetime.now().isoformat(timespec="seconds"),
        "clicked_confirm_create": False,
        "never_did": ["确认创建", "保存草稿", "提交宝贝信息"],
        "value": args.value,
        "row_added": row_added,
        "committed": committed,
        "steps": steps,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print()
    print("产物：{}".format(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

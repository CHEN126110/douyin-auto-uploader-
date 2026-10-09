# -*- coding: utf-8 -*-
"""创建销售规格并读出的 SKU 表格结构。

机制（E-095/E-096 已实证）：

  1. 点属性块里的 ``button.add`` 加**一个值行**；
  2. 点**最后一行**的值输入 → 弹出 ``.next-select-popup-wrap``；
  3. 在**最后一个**可见弹层里，点中文本精确相等的 ``.options-item``
     → **立即提交**，header 计数 +1。

⚠️ 关键：**必须每加一个值就点一次「+」**。同一行的输入框是那一行的编辑器，
反复用它只会改掉第一行的值（这正是 E-094 那次失败的原因）。

**这会改变未保存表单的状态**，但：不保存草稿、不上架、不提交、不上传图片；
导航离开页面即丢弃。

用法::

    python taobao-publisher/scripts/create-sku-specs.py --address 127.0.0.1:9502 --allow-create --values "L（45-47）,M(37-41)"
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

#: 读某个属性块的计数与行数。用 __WHICH__ 参数化。
STATE_JS = r"""
(() => {
  const WHICH = __WHICH__;
  const drawer = document.querySelector('.sku-decouple-drawer-container');
  if (!drawer) return { found: false, reason: 'no_drawer' };
  const block = Array.from(drawer.querySelectorAll('.common-wrap')).find(w => {
    const h = w.querySelector('.header');
    return h && (h.textContent || '').includes(WHICH);
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
    rowValues: rows.map(li => {
      const inp = li.querySelector('input,[role="combobox"]');
      return inp ? String(inp.value || '').slice(0, 20) : '';
    }),
  };
})()
"""

ADD_ROW_JS = r"""
(() => {
  const WHICH = __WHICH__;
  const drawer = document.querySelector('.sku-decouple-drawer-container');
  if (!drawer) return { ok: false, reason: 'no_drawer' };
  const block = Array.from(drawer.querySelectorAll('.common-wrap')).find(w => {
    const h = w.querySelector('.header');
    return h && (h.textContent || '').includes(WHICH);
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

OPEN_LAST_ROW_JS = r"""
(() => {
  const WHICH = __WHICH__;
  const drawer = document.querySelector('.sku-decouple-drawer-container');
  if (!drawer) return { ok: false, reason: 'no_drawer' };
  const block = Array.from(drawer.querySelectorAll('.common-wrap')).find(w => {
    const h = w.querySelector('.header');
    return h && (h.textContent || '').includes(WHICH);
  });
  if (!block) return { ok: false, reason: 'no_block' };
  const rows = Array.from(block.querySelectorAll('li'));
  if (!rows.length) return { ok: false, reason: 'no_rows' };

  const before = document.querySelectorAll('.next-select-popup-wrap').length;
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
  return { ok: true, popupsBeforeClick: before };
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
             hitCount: hits.length,
             shown: [...new Set(options.map(o => o.text))].slice(0, 20) };
  }
  hits[0].el.click();
  return { ok: true, picked: WANT };
})()
"""

CONFIRM_JS = r"""
(() => {
  const footer = document.querySelector('.sku-decouple-drawer-footer');
  if (!footer) return { ok: false, reason: 'no_footer' };
  const btns = Array.from(footer.querySelectorAll('button'))
    .filter(b => (b.textContent || '').trim() === '确认创建');
  if (btns.length !== 1) return { ok: false, reason: 'not_unique', hitCount: btns.length };
  if (btns[0].disabled) return { ok: false, reason: 'disabled' };
  btns[0].click();
  return { ok: true };
})()
"""

TABLE_JS = r"""
(() => {
  const root = document.querySelector('.sell-sku-table-wrapper-new');
  if (!root) return { found: false, reason: 'no_wrapper' };
  const drawer = document.querySelector('.sku-decouple-drawer-container');
  const tables = Array.from(root.querySelectorAll('table'));
  if (!tables.length) {
    return { found: true, tableCount: 0, drawerOpen: Boolean(drawer),
             wrapperText: (root.textContent || '').trim().slice(0, 160) };
  }
  const table = tables[0];
  const thead = Array.from(table.querySelectorAll('thead th')).map(th => (th.textContent || '').trim());
  const rows = Array.from(table.querySelectorAll('tbody tr')).slice(0, 8).map(tr => ({
    className: typeof tr.className === 'string' ? tr.className.slice(0, 90) : '',
    cellCount: tr.querySelectorAll('td').length,
    cells: Array.from(tr.querySelectorAll('td')).slice(0, 8).map(td => ({
      text: (td.textContent || '').trim().slice(0, 24),
      inputCount: td.querySelectorAll('input,textarea').length,
      placeholders: Array.from(td.querySelectorAll('input,textarea'))
        .map(i => i.getAttribute('placeholder') || '').filter(Boolean).slice(0, 3),
    })),
  }));
  return {
    found: true,
    tableCount: tables.length,
    drawerOpen: Boolean(drawer),
    tableClass: typeof table.className === 'string' ? table.className.slice(0, 90) : '',
    thead,
    rowCount: rows.length,
    rows,
    rowSelectorHint: rows.length ? rows[0].className : '',
    wrapperClass: String(root.className).slice(0, 110),
  };
})()
"""

CLOSE_JS = """
(() => {
  const btns = Array.from(document.querySelectorAll('button'));
  const cancel = btns.find(b => ['取消', '关闭'].includes((b.textContent || '').trim()));
  if (cancel) { cancel.click(); return 'clicked_cancel'; }
  return 'no_cancel';
})()
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--address", default="127.0.0.1:9502")
    parser.add_argument("--allow-create", action="store_true")
    parser.add_argument("--which", default="尺码")
    parser.add_argument("--values", default="L（45-47）,M(37-41)")
    parser.add_argument("--wait", type=float, default=1.8)
    args = parser.parse_args()

    if not args.allow_create:
        print("这会创建销售规格（不保存草稿、不上架），必须显式加 --allow-create。")
        return 2

    wanted = [v.strip() for v in args.values.split(",") if v.strip()]
    which_literal = json.dumps(args.which, ensure_ascii=False)
    state_js = STATE_JS.replace("__WHICH__", which_literal)
    add_js = ADD_ROW_JS.replace("__WHICH__", which_literal)
    open_js = OPEN_LAST_ROW_JS.replace("__WHICH__", which_literal)

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

    log = []
    with page.PageClient.connect(target["webSocketDebuggerUrl"]) as client:
        print("页面：{}".format(str(client.evaluate("location.href.split('?')[0]"))[:90]))
        if not (client.evaluate(OPEN_DRAWER_JS) or {}).get("ok"):
            print("开抽屉失败")
            return 1
        time.sleep(max(3.0, args.wait))
        print("打开抽屉后：{}".format(json.dumps(client.evaluate(state_js), ensure_ascii=False)))

        for value in wanted:
            print()
            print("── 加值 {!r} ──".format(value))
            added = client.evaluate(add_js)
            time.sleep(args.wait)
            if not (isinstance(added, dict) and added.get("ok")):
                print("   加行失败：{}".format(json.dumps(added, ensure_ascii=False)[:160]))
                log.append({"value": value, "stage": "add_row", "result": added})
                continue
            after_add = client.evaluate(state_js)
            print("   加行后 行数={} 计数={}".format(
                (after_add or {}).get("rowCount"), (after_add or {}).get("count")))

            opened = client.evaluate(open_js)
            time.sleep(args.wait)
            if not (isinstance(opened, dict) and opened.get("ok")):
                print("   点输入失败：{}".format(json.dumps(opened, ensure_ascii=False)[:160]))
                log.append({"value": value, "stage": "open", "result": opened})
                continue

            picked = client.evaluate(
                PICK_LATEST_JS.replace("__WANT__", json.dumps(value, ensure_ascii=False)))
            time.sleep(args.wait)
            after_pick = client.evaluate(state_js)
            ok = isinstance(picked, dict) and picked.get("ok")
            print("   选候选：{}  → 计数={} 值={}".format(
                "成功" if ok else json.dumps(picked, ensure_ascii=False)[:120],
                (after_pick or {}).get("count"),
                json.dumps((after_pick or {}).get("rowValues"), ensure_ascii=False)))
            log.append({"value": value, "stage": "pick", "result": picked, "state": after_pick})

        before_confirm = client.evaluate(state_js)
        print()
        print("确认创建前：{}".format(json.dumps(before_confirm, ensure_ascii=False)))

        confirmed = client.evaluate(CONFIRM_JS)
        print()
        print("点「确认创建」：{}".format(json.dumps(confirmed, ensure_ascii=False)))
        time.sleep(max(5.0, args.wait * 3))

        table = client.evaluate(TABLE_JS)

    print()
    print("==== SKU 表格 ====")
    if not isinstance(table, dict) or not table.get("found"):
        print("  没找到容器：{}".format(json.dumps(table, ensure_ascii=False)[:160]))
    elif not table.get("tableCount"):
        print("  **没有表格**；抽屉还开着={}".format(table.get("drawerOpen")))
        print("  容器文本：{!r}".format((table.get("wrapperText") or "")[:140]))
    else:
        print("  表格数：{}   行数：{}   抽屉还开着={}".format(
            table["tableCount"], table["rowCount"], table.get("drawerOpen")))
        print("  表格 class：{}".format(table.get("tableClass")))
        print("  表头：{}".format(json.dumps(table.get("thead"), ensure_ascii=False)))
        print("  行 class 提示：{}".format(table.get("rowSelectorHint")))
        for row in table["rows"]:
            print("    tr cells={} class={}".format(row["cellCount"], row["className"][:60]))
            for cell in row["cells"]:
                extra = " inputs={} ph={}".format(cell["inputCount"], cell["placeholders"]) if cell["inputCount"] else ""
                print("        {!r}{}".format(cell["text"][:22], extra))

    TMP_DIR.mkdir(parents=True, exist_ok=True)
    out = TMP_DIR / "sku-created-{}.json".format(datetime.now().strftime("%Y%m%d%H%M%S"))
    out.write_text(json.dumps({
        "captured_at": datetime.now().isoformat(timespec="seconds"),
        "created_specs": True,
        "never_did": ["保存草稿", "提交宝贝信息", "上传图片"],
        "which": args.which,
        "values": wanted,
        "steps": log,
        "before_confirm": before_confirm,
        "confirmed": confirmed,
        "table": table,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print()
    print("产物：{}".format(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

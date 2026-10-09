# -*- coding: utf-8 -*-
"""读创建出来的 SKU 表格结构 —— ``skus.sku_row`` 的取证。

前置：先跑 ``create-sku-specs.py`` 加值，再跑
``experiment-sku-deselect-prop.py`` 触发成功创建。
**纯只读。不点任何写按钮。**

用法::

    python taobao-publisher/scripts/read-sku-table.py --address 127.0.0.1:9502
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SUBPROJECT = SCRIPT_DIR.parent
if str(SUBPROJECT) not in sys.path:
    sys.path.insert(0, str(SUBPROJECT))

from taobao_publish import page  # noqa: E402

TMP_DIR = SUBPROJECT / "tmp"

DUMP_JS = r"""
(() => {
  const WRAPPERS = ['.sell-sku-table-wrapper-new', '.sell-new-sku-table-content', '.sell-sku-table-wrapper'];
  let root = null, usedSelector = '';
  for (const sel of WRAPPERS) {
    const found = Array.from(document.querySelectorAll(sel))
      .filter(e => e.getBoundingClientRect().height > 0);
    if (found.length) { root = found[0]; usedSelector = sel; break; }
  }
  if (!root) return { found: false };

  const tables = Array.from(root.querySelectorAll('table'));
  const table = tables[0];
  if (!table) {
    return { found: true, usedSelector, tableCount: 0,
             rootClass: String(root.className).slice(0, 110),
             text: (root.textContent || '').trim().slice(0, 200) };
  }

  const thead = Array.from(table.querySelectorAll('thead th')).map(th => ({
    text: (th.textContent || '').trim().slice(0, 20),
    rowSpan: th.rowSpan, colSpan: th.colSpan,
    className: String(th.className).slice(0, 60),
  }));

  const rows = Array.from(table.querySelectorAll('tbody tr'));
  const describe = (tr) => ({
    className: typeof tr.className === 'string' ? tr.className.slice(0, 100) : '',
    cellCount: tr.querySelectorAll('td').length,
    cells: Array.from(tr.querySelectorAll('td')).slice(0, 8).map(td => ({
      text: (td.textContent || '').trim().slice(0, 22),
      inputs: Array.from(td.querySelectorAll('input,textarea')).slice(0, 4).map(i => ({
        ph: i.getAttribute('placeholder') || '',
        value: String(i.value || '').slice(0, 14),
        cls: typeof i.className === 'string' ? i.className.slice(0, 40) : '',
      })),
      comboboxes: td.querySelectorAll('[role="combobox"]').length,
    })),
  });

  // 可能的「SKU 行」类名：统计 tbody 里各类名出现次数
  const classCount = {};
  for (const tr of rows) {
    const cls = typeof tr.className === 'string' ? tr.className.trim() : '';
    if (cls) classCount[cls] = (classCount[cls] || 0) + 1;
  }

  return {
    found: true,
    usedSelector,
    rootClass: String(root.className).slice(0, 110),
    tableCount: tables.length,
    tableClass: String(table.className).slice(0, 100),
    thead,
    rowCount: rows.length,
    rowClassCount: classCount,
    rows: rows.slice(0, 5).map(describe),
  };
})()
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--address", default="127.0.0.1:9502")
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
        data = client.evaluate(DUMP_JS)

    if not isinstance(data, dict) or not data.get("found"):
        print("没找到 SKU 容器")
        return 1

    print("容器选择器：{}".format(data["usedSelector"]))
    print("容器 class：{}".format(data["rootClass"]))
    print("表格数：{}".format(data["tableCount"]))
    if not data["tableCount"]:
        print("容器文本：{!r}".format((data.get("text") or "")[:160]))
        print()
        print("**没有表格** —— 需要先成功创建规格")
        return 1

    print("表格 class：{}".format(data["tableClass"]))
    print()
    print("==== 表头 {} 列 ====".format(len(data["thead"])))
    for th in data["thead"]:
        print("  span={}x{}  {!r}".format(th["rowSpan"], th["colSpan"], th["text"]))
    print()
    print("==== 行 {} 条 ====".format(data["rowCount"]))
    print("  行类名分布：{}".format(json.dumps(data["rowClassCount"], ensure_ascii=False)))
    for index, row in enumerate(data["rows"]):
        print("  tr[{}] cells={} class={}".format(index, row["cellCount"], row["className"][:70]))
        for cell in row["cells"]:
            print("      text={!r} comboboxes={}".format(cell["text"][:20], cell["comboboxes"]))
            for inp in cell["inputs"]:
                print("         <input> ph={!r} value={!r} class={}".format(
                    inp["ph"][:18], inp["value"][:12], inp["cls"][:38]))

    TMP_DIR.mkdir(parents=True, exist_ok=True)
    out = TMP_DIR / "sku-table-{}.json".format(datetime.now().strftime("%Y%m%d%H%M%S"))
    out.write_text(json.dumps({
        "captured_at": datetime.now().isoformat(timespec="seconds"),
        "clicked_nothing": True,
        **data,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print()
    print("产物：{}".format(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

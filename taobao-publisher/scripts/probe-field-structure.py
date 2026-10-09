# -*- coding: utf-8 -*-
"""勘察：按**字段名**反查 DOM 结构，找出「行」到底长什么样。

上一轮结论：``.next-form-item`` 在这个页面 **不存在**（0 个），所以不能套 Fusion
的标准表单结构。既然不知道行容器是什么，就反过来做——从已知的字段名出发，
找到它在 DOM 里的位置，再描述它的祖先与兄弟。

这样得到的「行模式」是从真实结构里读出来的，不是照搬别处的假设。

**纯只读**：不点击、不输入、不保存、不提交。

用法::

    python taobao-publisher/scripts/probe-field-structure.py --address 127.0.0.1:9502
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.request
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
TMP_DIR = SCRIPT_DIR.parent / "tmp"

#: docs/08 里实拍记录的这个类目下的字段名。用来反查结构。
DEFAULT_FIELDS = [
    "材质成分", "面料", "上市年份季节", "编织工艺", "吊牌价", "防滑设计",
    "风格", "缝头工艺", "厚薄", "抗菌处理", "款式细节", "里料",
    "是否商场同款", "图案", "袜口弹性材质", "款号",
    "宝贝标题", "导购标题", "一口价", "总库存", "购买须知", "商家编码",
]

EXPRESSION = r"""
(() => {
  const FIELDS = __FIELDS__;
  const describe = (el) => ({
    tag: el.tagName.toLowerCase(),
    cls: typeof el.className === 'string' ? el.className.slice(0, 90) : '',
    id: el.id || '',
  });

  const out = [];
  for (const name of FIELDS) {
    // 找「文本恰好等于字段名」的最深元素——那就是标签本身
    const all = Array.from(document.querySelectorAll('span,div,label,dt,th,p'));
    const exact = all.filter(el => (el.textContent || '').trim() === name);
    if (!exact.length) {
      out.push({ field: name, found: false });
      continue;
    }
    // 取最深的一个（最贴近标签本身），避免拿到包住整块的外层容器
    const labelEl = exact[exact.length - 1];

    // 往上走 5 层，记录每一层的结构与「同级兄弟里有多少个也长得像标签」
    const ancestry = [];
    let node = labelEl;
    for (let depth = 0; depth < 5 && node && node.parentElement; depth++) {
      const parent = node.parentElement;
      const siblings = Array.from(parent.children);
      // 这个父节点下有多少个「叶子文本块」——多的话说明它是一个行容器
      const leafTexts = siblings
        .map(s => (s.textContent || '').trim())
        .filter(t => t && t.length <= 14);
      const controls = parent.querySelectorAll('input,textarea,select,[role="combobox"]').length;
      ancestry.push({
        depth,
        parent: describe(parent),
        childCount: siblings.length,
        leafTexts: leafTexts.slice(0, 10),
        controlsInside: controls,
      });
      node = parent;
    }

    // 标签之后最近的、含控件的兄弟
    let container = labelEl.parentElement;
    let controlInfo = null;
    for (let hop = 0; hop < 4 && container; hop++) {
      const controls = Array.from(container.querySelectorAll('input,textarea,select,[role="combobox"]'))
        .filter(el => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; });
      if (controls.length) {
        controlInfo = {
          hops: hop,
          containerClass: typeof container.className === 'string' ? container.className.slice(0, 90) : '',
          count: controls.length,
          sample: controls.slice(0, 4).map(el => ({
            tag: el.tagName.toLowerCase(),
            type: el.getAttribute('type') || '',
            role: el.getAttribute('role') || '',
            placeholder: el.getAttribute('placeholder') || '',
            cls: typeof el.className === 'string' ? el.className.slice(0, 60) : '',
          })),
        };
        break;
      }
      container = container.parentElement;
    }

    out.push({
      field: name,
      found: true,
      labelEl: describe(labelEl),
      labelTextLength: (labelEl.textContent || '').trim().length,
      ancestry,
      controlInfo,
    });
  }
  return out;
})()
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--address", default="127.0.0.1:9502")
    parser.add_argument("--fields", default="", help="逗号分隔；默认用 docs/08 的字段表")
    args = parser.parse_args()

    fields = [f.strip() for f in args.fields.split(",") if f.strip()] or DEFAULT_FIELDS

    with urllib.request.urlopen("http://{}/json/list".format(args.address), timeout=5) as response:
        targets = json.loads(response.read().decode("utf-8"))
    pages = [
        t for t in targets
        if t.get("type") == "page" and "item.upload.taobao.com" in str(t.get("url") or "")
    ]
    if not pages:
        print("没有发布工作台页面")
        return 1
    page = pages[0]

    import websocket

    ws = websocket.create_connection(page["webSocketDebuggerUrl"], timeout=10, suppress_origin=True)
    ws.settimeout(3)
    ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate", "params": {
        "expression": EXPRESSION.replace("__FIELDS__", json.dumps(fields, ensure_ascii=False)),
        "returnByValue": True, "awaitPromise": True,
    }}))

    rows = None
    deadline = time.time() + 30
    while time.time() < deadline:
        try:
            message = json.loads(ws.recv())
        except Exception:
            continue
        if message.get("id") != 1:
            continue
        payload = message.get("result") or {}
        if payload.get("exceptionDetails"):
            print("页面内报错：{}".format(str(payload["exceptionDetails"])[:300]))
            ws.close()
            return 1
        rows = (payload.get("result") or {}).get("value")
        break
    ws.close()

    if not isinstance(rows, list):
        print("没取到结果")
        return 1

    found = [r for r in rows if r.get("found")]
    print("字段 {} 个，命中 {} 个".format(len(rows), len(found)))
    print()
    for row in rows:
        if not row.get("found"):
            print("  [缺失] {}".format(row["field"]))
            continue
        info = row.get("controlInfo") or {}
        sample = (info.get("sample") or [{}])[0]
        print("  [命中] {:<10} 标签<{}{}> 向上{}跳找到控件×{}  ph={!r:<16} role={}".format(
            row["field"], row["labelEl"]["tag"],
            ("." + row["labelEl"]["cls"].split()[0]) if row["labelEl"]["cls"] else "",
            info.get("hops", "-"), info.get("count", 0),
            (sample.get("placeholder") or "")[:16], sample.get("role") or "-"))
        for level in row["ancestry"][:2]:
            print("           ↑ {} childs={} controls={} 叶子文本={}".format(
                level["parent"]["tag"] + ("." + level["parent"]["cls"].split()[0] if level["parent"]["cls"] else ""),
                level["childCount"], level["controlsInside"], level["leafTexts"][:6]))

    TMP_DIR.mkdir(parents=True, exist_ok=True)
    out = TMP_DIR / "field-structure-{}.json".format(datetime.now().strftime("%Y%m%d%H%M%S"))
    out.write_text(json.dumps({
        "captured_at": datetime.now().isoformat(timespec="seconds"),
        "page_url": page.get("url"),
        "read_only": True,
        "fields": rows,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print()
    print("产物：{}".format(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

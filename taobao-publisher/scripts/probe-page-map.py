# -*- coding: utf-8 -*-
"""勘察：把填写页的**全部行标签与按钮**列出来，判断剩余阶段的结构在哪。

前几轮只针对已知字段做定点勘察，导致 `fill_skus` / `fill_freight` / `submit`
这些还没有落点的阶段看不到全貌。本脚本改成「先把地图画出来」：
62 个行标签 + 全部可见按钮 + 表格 + 弹层，一次性列全。

**纯只读**：不点击、不输入、不保存、不提交。

用法::

    python taobao-publisher/scripts/probe-page-map.py --address 127.0.0.1:9502
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.request
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SUBPROJECT = SCRIPT_DIR.parent
TMP_DIR = SUBPROJECT / "tmp"

MAP_EXPRESSION = r"""
(() => {
  const ROW = '.sell-component-info-wrapper-wrap';
  const LABEL = '.sell-component-info-wrapper-label';

  const rows = Array.from(document.querySelectorAll(ROW));
  const labels = [];
  for (const row of rows) {
    const el = row.querySelector(LABEL);
    const text = el ? (el.textContent || '').trim() : '';
    const rect = row.getBoundingClientRect();
    const controls = Array.from(row.querySelectorAll('input,textarea,select,[role="combobox"]'))
      .filter(e => { const b = e.getBoundingClientRect(); return b.width > 0 && b.height > 0; });
    const labelWrap = row.querySelector('.sell-component-info-wrapper-label-wrap');
    const wrapText = labelWrap ? (labelWrap.textContent || '').trim() : '';
    labels.push({
      text,
      unlabeled: !text,
      required: wrapText.includes('*'),
      important: wrapText.includes('重要'),
      visible: rect.height > 0,
      controlCount: controls.length,
      controlKinds: [...new Set(controls.map(e => e.tagName.toLowerCase() + (e.getAttribute('role') ? '[role=' + e.getAttribute('role') + ']' : '')))],
    });
  }

  const buttons = Array.from(document.querySelectorAll('button'))
    .map(b => {
      const r = b.getBoundingClientRect();
      return {
        text: (b.textContent || '').trim().slice(0, 24),
        visible: r.width > 0 && r.height > 0,
        disabled: b.disabled === true,
        cls: typeof b.className === 'string' ? b.className.slice(0, 80) : '',
        title: b.getAttribute('title') || '',
      };
    })
    .filter(b => b.text);

  const tables = Array.from(document.querySelectorAll('table')).map(t => {
    const r = t.getBoundingClientRect();
    return {
      rows: t.querySelectorAll('tr').length,
      visible: r.width > 0 && r.height > 0,
      cls: typeof t.className === 'string' ? t.className.slice(0, 80) : '',
      headers: Array.from(t.querySelectorAll('th')).slice(0, 8).map(h => (h.textContent || '').trim().slice(0, 14)),
    };
  });

  // 页面上出现的关键词，用来判断某个区块是否已渲染
  const bodyText = document.body ? (document.body.innerText || '') : '';
  const KEYWORDS = ['销售规格', '创建规格', '运费模板', '物流服务', '图文描述',
                    '销售信息', '基础信息', '提交宝贝', '保存草稿', '发布', '上下架',
                    'SKU', '批量导入', '图片空间', '主图', '详情描述'];
  const keywordHits = {};
  for (const k of KEYWORDS) keywordHits[k] = bodyText.includes(k);

  const tabs = Array.from(document.querySelectorAll('[role="tab"], [class*="tab"]'))
    .map(t => (t.textContent || '').trim().slice(0, 16))
    .filter(t => t && t.length <= 16);

  return {
    rowCount: rows.length,
    labels,
    buttons,
    tables,
    keywordHits,
    tabs: [...new Set(tabs)].slice(0, 30),
    url: location.href.split('?')[0],
  };
})()
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--address", default="127.0.0.1:9502")
    args = parser.parse_args()

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
        "expression": MAP_EXPRESSION, "returnByValue": True, "awaitPromise": True,
    }}))

    data = None
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
        data = (payload.get("result") or {}).get("value")
        break
    ws.close()

    if not isinstance(data, dict):
        print("没取到结果")
        return 1

    print("页面：{}   行总数 {}".format(data["url"], data["rowCount"]))
    print()

    print("==== 关键词是否出现（判断区块有没有渲染）====")
    for key, hit in data["keywordHits"].items():
        print("  {:<12} {}".format(key, "有" if hit else "—"))
    print()

    print("==== 行标签（按出现顺序）====")
    for i, item in enumerate(data["labels"]):
        if item["unlabeled"]:
            print("  {:>3}. （无标签）{} 控件{}个 {}".format(
                i, "" if item["visible"] else "[不可见]", item["controlCount"],
                ",".join(item["controlKinds"])[:40]))
            continue
        flags = "".join([
            "*" if item["required"] else " ",
            "!" if item["important"] else " ",
            " " if item["visible"] else "隐",
        ])
        print("  {:>3}. [{}] {:<16} 控件{}个 {}".format(
            i, flags, item["text"][:16], item["controlCount"], ",".join(item["controlKinds"])[:34]))
    print()

    print("==== 可见按钮 ====")
    for b in data["buttons"]:
        if not b["visible"]:
            continue
        print("  {:<20} disabled={:<6} {}".format(
            repr(b["text"])[:20], str(b["disabled"]), b["cls"][:56]))
    print()

    print("==== 隐藏按钮（可能在别的 tab 或折叠区）====")
    for b in data["buttons"]:
        if b["visible"]:
            continue
        print("  {:<20} {}".format(repr(b["text"])[:20], b["cls"][:56]))
    print()

    if data["tables"]:
        print("==== 表格 ====")
        for t in data["tables"]:
            print("  {}行 visible={} 表头={} cls={}".format(
                t["rows"], t["visible"], t["headers"], t["cls"][:50]))
    print()

    print("==== tab 文本 ====")
    print("  {}".format(data["tabs"]))

    TMP_DIR.mkdir(parents=True, exist_ok=True)
    out = TMP_DIR / "page-map-{}.json".format(datetime.now().strftime("%Y%m%d%H%M%S"))
    out.write_text(json.dumps({
        "captured_at": datetime.now().isoformat(timespec="seconds"),
        "page_url": page.get("url"),
        "read_only": True,
        **data,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print()
    print("产物：{}".format(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# -*- coding: utf-8 -*-
"""勘察：把发布填写页的「标签 → 控件」索引读出来。

为什么需要它（这是 9 个阶段共同的基础）：

表单里大量控件的 ``placeholder`` 都是「请选择」「请输入」，完全重复；按钮也没有
唯一属性。**CSS 选择器无法按文本匹配**，所以不能用占位符或「第 N 个 input」定位——
后者一旦页面增删字段就会整体错位，而且每一步都会「成功」。

正确的定位是两段式：先按**行的标签文本**找到所在行，再在行内定位控件。
本脚本就是去确认「行」在 DOM 里长什么样、标签和控件分别怎么取。

**纯只读**：不点击、不输入、不上传、不保存、不提交。

用法::

    python taobao-publisher/scripts/probe-form-labels.py --address 127.0.0.1:9502
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

# 在页面里跑：统计候选「行」容器的结构，并对每个行提取标签与控件。
#
# 只看结构、不读 value（``value`` 一个字都不取），避免把用户已填内容带出来。
INDEX_EXPRESSION = r"""
(() => {
  const ROW_CANDIDATES = [
    '.next-form-item',
    '[class*="formItem"]',
    '[class*="form-item"]',
    '[class*="fieldItem"]',
    'tr',
  ];

  const summary = {};
  for (const sel of ROW_CANDIDATES) {
    summary[sel] = document.querySelectorAll(sel).length;
  }

  const text = (el) => (el ? (el.textContent || '').trim() : '');

  // 对每个候选行，找出「标签」与「控件」分别是什么元素。
  const rows = Array.from(document.querySelectorAll('.next-form-item'));
  const items = [];
  for (let i = 0; i < rows.length && items.length < 120; i++) {
    const row = rows[i];
    const rect = row.getBoundingClientRect();
    if (rect.width === 0 && rect.height === 0) continue;   // 不可见

    // 标签：Fusion 用 .next-form-item-label；退化时取行内第一个 label 或带 * 的短文本节点
    let labelEl = row.querySelector('.next-form-item-label, label');
    let label = text(labelEl);
    let required = false;
    if (labelEl) {
      const raw = labelEl.textContent || '';
      required = raw.includes('*') || Boolean(row.querySelector('.next-form-item-label .next-form-item-required, [class*="required"]'));
    }
    if (!label) {
      // 退化：取行内第一个短文本块
      const blocks = Array.from(row.querySelectorAll('span,div')).filter(e => {
        const t = (e.textContent || '').trim();
        return t && t.length <= 12 && e.children.length === 0;
      });
      label = blocks.length ? text(blocks[0]) : '';
    }

    const controls = Array.from(row.querySelectorAll('input, textarea, select, [role="combobox"]'))
      .filter(el => {
        const r = el.getBoundingClientRect();
        return r.width > 0 && r.height > 0;
      });

    items.push({
      index: i,
      label: label.slice(0, 30),
      required,
      labelClass: labelEl && typeof labelEl.className === 'string' ? labelEl.className.slice(0, 70) : '',
      rowClass: typeof row.className === 'string' ? row.className.slice(0, 90) : '',
      controlCount: controls.length,
      controls: controls.slice(0, 3).map(el => ({
        tag: el.tagName.toLowerCase(),
        type: el.getAttribute('type') || '',
        role: el.getAttribute('role') || '',
        placeholder: el.getAttribute('placeholder') || '',
        className: typeof el.className === 'string' ? el.className.slice(0, 70) : '',
      })),
    });
  }

  // 页面里所有 label 元素（Fusion 用 label 包住输入）
  const labelTags = Array.from(document.querySelectorAll('label')).slice(0, 25).map(el => ({
    text: text(el).slice(0, 26),
    cls: typeof el.className === 'string' ? el.className.slice(0, 70) : '',
    forAttr: el.getAttribute('for') || '',
    hasInput: Boolean(el.querySelector('input,textarea,select')),
  }));

  return {
    rowCandidateCounts: summary,
    items,
    labelTags,
    totals: {
      formItems: document.querySelectorAll('.next-form-item').length,
      labels: document.querySelectorAll('label').length,
      comboboxes: document.querySelectorAll('[role="combobox"]').length,
    },
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
    print("页面：{}".format(str(page.get("url"))[:110]))

    import websocket

    ws = websocket.create_connection(page["webSocketDebuggerUrl"], timeout=10, suppress_origin=True)
    ws.settimeout(3)
    ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate", "params": {
        "expression": INDEX_EXPRESSION, "returnByValue": True, "awaitPromise": True,
    }}))

    result = None
    deadline = time.time() + 25
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
        result = (payload.get("result") or {}).get("value")
        break
    ws.close()

    if not isinstance(result, dict):
        print("没取到结果")
        return 1

    print()
    print("==== 候选行容器的命中数量 ====")
    for sel, count in result["rowCandidateCounts"].items():
        print("  {:<24} {}".format(sel, count))
    print("  合计: {}".format(json.dumps(result["totals"], ensure_ascii=False)))
    print()

    print("==== .next-form-item 行（标签 → 控件）====")
    for item in result["items"]:
        mark = "*" if item["required"] else " "
        ctrl = item["controls"][0] if item["controls"] else {}
        print("  [{}] {:<16} 控件{}个 {:<7} ph={!r:<20} role={}".format(
            mark, item["label"][:14], item["controlCount"],
            ctrl.get("tag", "-"), (ctrl.get("placeholder") or "")[:18], ctrl.get("role") or "-"))
    print()

    print("==== <label> 元素（前 25）====")
    for lab in result["labelTags"]:
        print("  {!r:<28} hasInput={:<6} for={!r:<14} cls={}".format(
            lab["text"][:26], str(lab["hasInput"]), lab["forAttr"][:12], lab["cls"][:52]))
    print()

    TMP_DIR.mkdir(parents=True, exist_ok=True)
    out = TMP_DIR / "form-label-index-{}.json".format(datetime.now().strftime("%Y%m%d%H%M%S"))
    out.write_text(json.dumps({
        "captured_at": datetime.now().isoformat(timespec="seconds"),
        "page_url": page.get("url"),
        "read_only": True,
        "not_done": ["点击", "输入", "上传", "保存草稿", "提交"],
        **result,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print("产物：{}".format(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

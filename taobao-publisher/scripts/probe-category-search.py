# -*- coding: utf-8 -*-
"""交互勘察：走一遍「搜索发品 → 读下拉类目」，只读结果。

**这是交互探针，不是纯只读探针**，所以边界写清楚：

  做：在「搜索发品」输入框里填一个关键词、点「搜索」、读出现的候选类目。
  不做：点「确认，下一步」、填任何商品字段、上传图片、保存草稿、提交。

输入关键词并点搜索**不会改变平台上的任何商品状态**——它只是让页面去查类目建议。
产物只保留**选择器与结构**，不保留用户输入以外的任何内容。

用法::

    python taobao-publisher/scripts/probe-category-search.py --address 127.0.0.1:9502 --keyword 袜子
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
TMP_DIR = SCRIPT_DIR.parent / "tmp"

# 在页面里执行：填入关键词 → 触发 React 的受控输入 → 点搜索 → 等结果。
#
# 关键点：React 受控组件直接改 input.value 不会触发 onChange，
# 必须走原生 setter 再派发 input 事件。
SEARCH_EXPRESSION = r"""
(() => {
  const KEYWORD = __KEYWORD__;
  const inputs = Array.from(document.querySelectorAll('input'))
    .filter(el => (el.placeholder || '').includes('可输入产品名称'));
  if (!inputs.length) return { ok: false, step: 'find-input', error: '没找到搜索发品输入框', inputs: Array.from(document.querySelectorAll('input')).map(e => e.placeholder) };
  const input = inputs[0];

  const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
  setter.call(input, KEYWORD);
  input.dispatchEvent(new Event('input', { bubbles: true }));
  input.dispatchEvent(new Event('change', { bubbles: true }));

  const buttons = Array.from(document.querySelectorAll('button'));
  const searchBtn = buttons.find(b => (b.textContent || '').trim() === '搜索');
  if (!searchBtn) return { ok: false, step: 'find-button', error: '没找到「搜索」按钮', buttons: buttons.map(b => (b.textContent || '').trim()).filter(Boolean) };
  searchBtn.click();

  return { ok: true, typed: KEYWORD };
})()
"""

# 等结果渲染后再读。读的是「搜索之前不存在、之后出现」的元素。
READ_EXPRESSION = r"""
(() => {
  const before = new Set(__BEFORE__);
  const describe = (el) => {
    const text = (el.textContent || '').trim();
    return text.length > 0 && text.length <= 40 ? text : null;
  };
  const nodes = Array.from(document.querySelectorAll('li, [role=option], [class*=option], [class*=Option], [class*=item], [class*=Item], [class*=card], [class*=Card]'));
  const found = [];
  const seen = new Set();
  for (const el of nodes) {
    if (el.children.length > 3) continue;      // 只看叶子，避免把整页容器收进来
    const text = describe(el);
    if (!text || seen.has(text)) continue;
    seen.add(text);
    found.push({
      text,
      tag: el.tagName.toLowerCase(),
      role: el.getAttribute('role') || '',
      className: el.className && typeof el.className === 'string' ? el.className.slice(0, 120) : '',
      dataAttrs: Array.from(el.attributes).filter(a => a.name.startsWith('data-')).map(a => a.name).slice(0, 6),
    });
  }
  return { candidates: found.slice(0, 80) };
})()
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--address", default="127.0.0.1:9502")
    parser.add_argument("--keyword", default="袜子")
    parser.add_argument("--wait", type=float, default=6.0, help="点搜索后等结果渲染的秒数")
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
    message_id = [0]

    def evaluate(expression: str):
        message_id[0] += 1
        current = message_id[0]
        ws.send(json.dumps({
            "id": current,
            "method": "Runtime.evaluate",
            "params": {"expression": expression, "returnByValue": True, "awaitPromise": True},
        }))
        deadline = time.time() + 20
        while time.time() < deadline:
            try:
                message = json.loads(ws.recv())
            except Exception:
                continue
            if message.get("id") != current:
                continue
            result = message.get("result") or {}
            if result.get("exceptionDetails"):
                return {"__error__": str(result["exceptionDetails"])[:400]}
            return (result.get("result") or {}).get("value")
        return {"__error__": "evaluate 超时"}

    # 先记录搜索前的候选文本，用于对比「新增了什么」。
    baseline = evaluate(
        "JSON.stringify(Array.from(document.querySelectorAll('li, [role=option]'))"
        ".map(e => (e.textContent || '').trim()).filter(t => t && t.length <= 40))"
    )
    before = json.loads(baseline) if isinstance(baseline, str) else []
    print("搜索前已有候选 {} 个".format(len(before)))

    print("输入 {!r} 并点击「搜索」…".format(args.keyword))
    typed = evaluate(SEARCH_EXPRESSION.replace("__KEYWORD__", json.dumps(args.keyword, ensure_ascii=False)))
    if not isinstance(typed, dict) or not typed.get("ok"):
        print("交互失败：{}".format(json.dumps(typed, ensure_ascii=False)[:500]))
        ws.close()
        return 1

    time.sleep(args.wait)
    read = evaluate(READ_EXPRESSION.replace("__BEFORE__", json.dumps(before, ensure_ascii=False)))
    ws.close()

    candidates = (read or {}).get("candidates") or []
    print("读回候选 {} 个".format(len(candidates)))
    print()
    for item in candidates:
        mark = "新增" if item["text"] not in before else "原有"
        print("  [{}] {:<24} <{}> role={} class={} {}".format(
            mark, item["text"][:24], item["tag"], item["role"] or "-",
            (item["className"] or "-")[:50], ",".join(item["dataAttrs"]) or "",
        ))

    TMP_DIR.mkdir(parents=True, exist_ok=True)
    out = TMP_DIR / "category-search-probe-{}.json".format(datetime.now().strftime("%Y%m%d%H%M%S"))
    out.write_text(json.dumps({
        "captured_at": datetime.now().isoformat(timespec="seconds"),
        "page_url": page.get("url"),
        "keyword": args.keyword,
        "baseline_count": len(before),
        "candidates": candidates,
        "not_done": ["点击下一步", "填写商品字段", "上传图片", "保存草稿", "提交"],
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print()
    print("产物：{}".format(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# -*- coding: utf-8 -*-
"""勘察：点击一个类目候选之后，**类目 ID 从哪里来**。

背景：DOM 里查不到类目 ID —— ``.sell-component-general-category-result-cate-path``
及其祖先 ``wrap`` / ``result-item`` 都没有 ``data-*`` 属性，也没有 ``id``。
而 ``CategoryRef`` 明确要求 ``category_id`` 必须来自类目接口、``path`` 不做程序判定。
所以必须先弄清「点下去之后 ID 出现在哪」。

做法：打开 Network 域 → 点**一个**候选 → 收集请求里出现的 catId 类参数 →
读取点击后的页面状态（URL、下一步按钮是否可用）。

**这是交互动作**（选中一个类目），但：

  * 选中类目**不创建草稿、不上架、不提交**；
  * 页面上随时可以「切换类目」改回来。

用法::

    python taobao-publisher/scripts/probe-category-click.py --address 127.0.0.1:9502 --match 长筒袜
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SUBPROJECT = SCRIPT_DIR.parent
if str(SUBPROJECT) not in sys.path:
    sys.path.insert(0, str(SUBPROJECT))

from taobao_publish import page  # noqa: E402

TMP_DIR = SUBPROJECT / "tmp"

#: 类目候选的文本容器。实测 9 个候选共用这个类名（语义类名，非哈希）。
CATE_PATH_SELECTOR = ".sell-component-general-category-result-cate-path"

LIST_JS = """
(() => {
  const els = Array.from(document.querySelectorAll({selector}));
  return els.map((el, i) => ({ index: i, text: (el.textContent || '').trim() }));
})()
""".replace("{selector}", json.dumps(CATE_PATH_SELECTOR))

CLICK_JS = """
(() => {
  const MATCH = __MATCH__;
  // 事件处理器在**文本元素自己**身上，不在祖先卡片上。
  // 上一版「往上找 result-item 再点」方向反了：那里没有 handler，点了不生效。
  // 实测带 onClick 的是 .sell-rich-text.path-text（还带 onMouseEnter/Leave，
  // 是真正的交互元素）与 .sell-component-general-category-result-cate-path。
  const CLICKABLE = '.sell-rich-text.path-text, .sell-component-general-category-result-cate-path';
  const els = Array.from(document.querySelectorAll(CLICKABLE));
  const hits = els.filter(el => (el.textContent || '').trim().includes(MATCH));
  // 同一个候选可能同时命中 path-text 与外层 cate-path（两者文本相同）——
  // 去重：保留带 onClick 的最内层。
  const unique = [];
  for (const el of hits) {
    if (!unique.some(other => other.contains(el) || el.contains(other))) unique.push(el);
  }
  if (unique.length !== 1) {
    return { ok: false, reason: unique.length === 0 ? 'no_match' : 'ambiguous',
             hitCount: unique.length,
             matched: unique.map(e => (e.textContent || '').trim()) };
  }
  const target = unique[0];
  target.click();
  return {
    ok: true,
    clickedText: (target.textContent || '').trim(),
    clickedClass: typeof target.className === 'string' ? target.className.slice(0, 100) : '',
  };
})()
"""

STATE_JS = """
(() => {
  const next = Array.from(document.querySelectorAll('button'))
    .find(b => (b.textContent || '').trim().includes('确认，下一步'));
  return {
    href: location.href,
    nextDisabled: next ? next.disabled === true : null,
    nextClass: next ? String(next.className).slice(0, 90) : null,
  };
})()
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--address", default="127.0.0.1:9502")
    parser.add_argument("--match", default="长筒袜", help="要点击的候选里包含的文字")
    parser.add_argument("--seconds", type=float, default=6.0)
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

    import websocket

    ws = websocket.create_connection(target["webSocketDebuggerUrl"], timeout=10, suppress_origin=True)
    ws.settimeout(2)
    counter = [0]
    captured = []

    def send(method, params=None):
        counter[0] += 1
        ws.send(json.dumps({"id": counter[0], "method": method, "params": params or {}}))
        return counter[0]

    def wait_for(message_id, timeout=20):
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                message = json.loads(ws.recv())
            except Exception:
                continue
            if message.get("method") == "Network.requestWillBeSent":
                url = str(((message.get("params") or {}).get("request") or {}).get("url") or "")
                if url.startswith("http") and ("taobao.com" in url or "tmall.com" in url):
                    query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
                    captured.append({
                        "host": urllib.parse.urlsplit(url).netloc,
                        "path": urllib.parse.urlsplit(url).path,
                        "param_names": sorted(query.keys()),
                        "cat_params": {k: v for k, v in query.items() if "cat" in k.lower() or "cid" in k.lower()},
                    })
                continue
            if message.get("id") == message_id:
                return (message.get("result") or {}).get("result", {}).get("value")
        return None

    send("Network.enable")
    send("Runtime.enable")

    client_expr = LIST_JS
    candidates = wait_for(send("Runtime.evaluate", {
        "expression": client_expr, "returnByValue": True, "awaitPromise": True}))
    print("当前类目候选 {} 个：".format(len(candidates or [])))
    for item in candidates or []:
        print("  {:>2}. {}".format(item["index"], item["text"]))

    before = wait_for(send("Runtime.evaluate", {
        "expression": STATE_JS, "returnByValue": True, "awaitPromise": True}))
    print()
    print("点击前：下一步 disabled={}  url={}".format(
        (before or {}).get("nextDisabled"), str((before or {}).get("href"))[:90]))

    print()
    print("点击包含 {!r} 的候选…".format(args.match))
    clicked = wait_for(send("Runtime.evaluate", {
        "expression": CLICK_JS.replace("__MATCH__", json.dumps(args.match, ensure_ascii=False)),
        "returnByValue": True, "awaitPromise": True}))
    if not isinstance(clicked, dict) or not clicked.get("ok"):
        print("点击失败：{}".format(json.dumps(clicked, ensure_ascii=False)[:300]))
        ws.close()
        return 1
    print("  已点击：{!r}（卡片 class={}）".format(clicked.get("clickedText", "")[:44], clicked.get("cardClass", "")[:60]))

    time.sleep(args.seconds)
    after = wait_for(send("Runtime.evaluate", {
        "expression": STATE_JS, "returnByValue": True, "awaitPromise": True}))
    ws.close()

    print()
    print("点击后：下一步 disabled={}  url={}".format(
        (after or {}).get("nextDisabled"), str((after or {}).get("href"))[:110]))

    print()
    print("==== 期间观察到的请求（{} 个）====".format(len(captured)))
    for item in captured[:25]:
        extra = "  cat参数={}".format(json.dumps(item["cat_params"], ensure_ascii=False)) if item["cat_params"] else ""
        print("  {:<26} {:<56}{}".format(item["host"][:24], item["path"][:54], extra))

    TMP_DIR.mkdir(parents=True, exist_ok=True)
    out = TMP_DIR / "category-click-{}.json".format(datetime.now().strftime("%Y%m%d%H%M%S"))
    out.write_text(json.dumps({
        "captured_at": datetime.now().isoformat(timespec="seconds"),
        "note": "选中类目属于表单状态变更，不创建草稿、不上架、不提交",
        "candidates": candidates,
        "clicked": clicked,
        "state_before": before,
        "state_after": after,
        "requests": captured,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print()
    print("产物：{}".format(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

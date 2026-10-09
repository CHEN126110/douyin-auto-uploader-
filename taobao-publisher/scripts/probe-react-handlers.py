# -*- coding: utf-8 -*-
"""勘察：找出类目候选上**真正带 React 事件处理器**的元素。

上一轮 ``card.click()`` 没有生效（下一步仍 disabled、无网络请求、URL 未变），
说明处理器不在卡片本身。React 把 props 挂在 DOM 节点的 ``__reactProps$<random>``
属性上，里面能直接看到 ``onClick`` / ``onMouseDown`` —— 比猜「哪一层可点」可靠得多。

**纯只读**：只读属性，不点击任何东西。

用法::

    python taobao-publisher/scripts/probe-react-handlers.py --address 127.0.0.1:9502
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

HANDLERS_JS = r"""
(() => {
  const CATE_PATH = '.sell-component-general-category-result-cate-path';

  // 取出一个元素上所有 React 注入的 key 与其中的事件处理器名
  const reactInfo = (el) => {
    const keys = Object.keys(el).filter(k => k.startsWith('__react'));
    const out = { keys: keys.map(k => k.split('$')[0]), handlers: [] };
    for (const k of keys) {
      const props = el[k];
      if (!props || typeof props !== 'object') continue;
      for (const name of Object.keys(props)) {
        if (/^on[A-Z]/.test(name)) out.handlers.push(name);
      }
    }
    out.handlers = [...new Set(out.handlers)];
    return out;
  };

  const first = document.querySelector(CATE_PATH);
  if (!first) return { found: false };

  const chain = [];
  let node = first;
  for (let hop = 0; hop <= 8 && node; hop++) {
    const info = reactInfo(node);
    chain.push({
      hop,
      tag: node.tagName.toLowerCase(),
      className: typeof node.className === 'string' ? node.className.slice(0, 110) : '',
      reactKeys: info.keys,
      handlers: info.handlers,
      childCount: node.children.length,
    });
    node = node.parentElement;
  }

  // 全页扫一遍：哪些元素在候选卡片区域内带 onClick
  const cards = Array.from(document.querySelectorAll('[class*="category-result-cate"]'));
  const withHandler = [];
  for (const card of cards) {
    let sub = card;
    const walk = [card, ...Array.from(card.querySelectorAll('*'))];
    for (const el of walk) {
      const info = reactInfo(el);
      if (info.handlers.length) {
        withHandler.push({
          tag: el.tagName.toLowerCase(),
          className: typeof el.className === 'string' ? el.className.slice(0, 100) : '',
          handlers: info.handlers,
          isCardRoot: el === card,
        });
      }
    }
  }

  return {
    found: true,
    cardCount: cards.length,
    chainFromFirstPath: chain,
    elementsWithHandlers: withHandler.slice(0, 20),
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
        print("页面：{}".format(str(client.evaluate("location.href.split('?')[0]"))[:90]))
        data = client.evaluate(HANDLERS_JS)

    if not isinstance(data, dict) or not data.get("found"):
        print("页面上没有类目候选（.sell-component-general-category-result-cate-path）")
        print("请先跑 probe-category-results.py 搜索，并切到「类目」tab")
        return 1

    print("候选卡片数：{}".format(data["cardCount"]))
    print()
    print("==== 从 cate-path 往上的祖先链（React 注入情况）====")
    print("  {:>3} {:<6} {:<5} {:<40} {}".format("hop", "tag", "childs", "className", "React props 里的事件"))
    for level in data["chainFromFirstPath"]:
        handlers = ",".join(level["handlers"]) or "—"
        print("  {:>3} {:<6} {:<5} {:<40} {}".format(
            level["hop"], level["tag"], level["childCount"], level["className"][:38], handlers))
    print()

    print("==== 候选卡片区域内**带事件处理器**的元素 ====")
    if not data["elementsWithHandlers"]:
        print("  （一个都没有 —— 说明事件靠更外层的委托处理，需要另找入口）")
    for item in data["elementsWithHandlers"]:
        print("  <{}> {:<52} handlers={} {}".format(
            item["tag"], item["className"][:50], ",".join(item["handlers"]),
            "[卡片根]" if item["isCardRoot"] else ""))

    TMP_DIR.mkdir(parents=True, exist_ok=True)
    out = TMP_DIR / "react-handlers-{}.json".format(datetime.now().strftime("%Y%m%d%H%M%S"))
    out.write_text(json.dumps({
        "captured_at": datetime.now().isoformat(timespec="seconds"),
        "read_only": True,
        "clicked_anything": False,
        **data,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print()
    print("产物：{}".format(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

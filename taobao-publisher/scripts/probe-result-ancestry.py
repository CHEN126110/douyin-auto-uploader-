# -*- coding: utf-8 -*-
"""勘察：转储结果标题的**完整祖先链**，找出真正的可点击容器。

上一轮的探测失败在方法上：React 用**事件委托**，元素的 ``onclick`` 属性永远是 ``null``，
所以靠 ``typeof node.onclick === 'function'`` 找不到任何东西。cursor 也未必是 pointer。

本脚本改成不猜——把祖先链逐层列出来（标签、类名、cursor、尺寸、子节点数），
由结构本身告诉我哪一层是卡片。

**纯只读**：不点击、不输入（搜索由调用方在此之前完成）、不保存、不提交。

用法::

    python taobao-publisher/scripts/probe-result-ancestry.py --address 127.0.0.1:9502
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

ANCESTRY_JS = r"""
(() => {
  const titles = Array.from(document.querySelectorAll('.card-title'));
  if (!titles.length) return { found: false, titleCount: 0 };

  const describe = (el) => {
    const r = el.getBoundingClientRect();
    const style = window.getComputedStyle(el);
    return {
      tag: el.tagName.toLowerCase(),
      className: typeof el.className === 'string' ? el.className.slice(0, 130) : '',
      id: el.id || '',
      cursor: style.cursor,
      pointerEvents: style.pointerEvents,
      width: Math.round(r.width),
      height: Math.round(r.height),
      childCount: el.children.length,
      hasOnclick: typeof el.onclick === 'function',
      // React 会把 props 挂在 fiber 上；有 fiber 说明它是 React 管理、可能带合成事件
      hasReactFiber: Boolean(Object.keys(el).find(k => k.startsWith('__react'))),
      role: el.getAttribute('role') || '',
      tabIndex: el.getAttribute('tabindex'),
    };
  };

  const chains = titles.slice(0, 2).map(titleEl => {
    const chain = [];
    let node = titleEl;
    for (let hop = 0; hop <= 10 && node; hop++) {
      chain.push({ hop, ...describe(node) });
      node = node.parentElement;
    }
    return { title: (titleEl.textContent || '').trim().slice(0, 34), chain };
  });

  // 全页里 cursor:pointer 且尺寸像卡片的元素——候选卡片
  const clickableCandidates = Array.from(document.querySelectorAll('div,li,a,button'))
    .map(el => ({ el, style: window.getComputedStyle(el) }))
    .filter(({ el, style }) => {
      if (style.cursor !== 'pointer') return false;
      const r = el.getBoundingClientRect();
      return r.width > 80 && r.height > 60 && r.width < 900;
    })
    .slice(0, 15)
    .map(({ el }) => ({ ...describe(el), textStart: (el.textContent || '').trim().slice(0, 20) }));

  return {
    found: true,
    titleCount: titles.length,
    chains,
    clickableCandidates,
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
        data = client.evaluate(ANCESTRY_JS)

    if not isinstance(data, dict) or not data.get("found"):
        print("页面上没有 .card-title —— 请先跑一次搜索（probe-category-results.py）")
        return 1

    print("结果标题数：{}".format(data["titleCount"]))

    print()
    print("==== 祖先链（前 2 条）====")
    for entry in data["chains"]:
        print("  ── {!r}".format(entry["title"]))
        print("     {:>3} {:<6} {:<7} {:>9} {:<7} {:<6} {:<6} {}".format(
            "hop", "tag", "cursor", "尺寸", "childs", "fiber", "onclick", "className"))
        for level in entry["chain"]:
            print("     {:>3} {:<6} {:<7} {:>4}x{:<4} {:<7} {:<6} {:<6} {}{}".format(
                level["hop"], level["tag"], level["cursor"][:7],
                level["width"], level["height"], level["childCount"],
                str(level["hasReactFiber"])[:5],
                str(level["hasOnclick"])[:5],
                level["className"][:52],
                (" id=" + level["id"]) if level["id"] else ""))
        print()

    print("==== 全页 cursor:pointer 且尺寸像卡片的元素 ====")
    for item in data["clickableCandidates"]:
        print("  <{}> {}x{} childs={} class={} text={!r}".format(
            item["tag"], item["width"], item["height"], item["childCount"],
            item["className"][:56], item["textStart"][:18]))

    TMP_DIR.mkdir(parents=True, exist_ok=True)
    out = TMP_DIR / "result-ancestry-{}.json".format(datetime.now().strftime("%Y%m%d%H%M%S"))
    out.write_text(json.dumps({
        "captured_at": datetime.now().isoformat(timespec="seconds"),
        "read_only": True,
        "not_done": ["点击结果条目", "确认下一步", "保存草稿", "提交"],
        **data,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print()
    print("产物：{}".format(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

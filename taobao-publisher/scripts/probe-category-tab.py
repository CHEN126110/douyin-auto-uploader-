# -*- coding: utf-8 -*-
"""勘察：类目页「类目」tab 的内容。

「全部」tab 返回的是**相似商品**（要借它的类目，属于启发式）。
「类目」tab 如果直接给出匹配的**类目**，`select_category` 就应该走这条——
按类目选是按事实选，按相似商品选是猜。

边界：只点 tab（纯前端切换，不改变任何平台状态），**不点任何结果条目**。

用法::

    python taobao-publisher/scripts/probe-category-tab.py --address 127.0.0.1:9502
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

CLICK_TAB_JS = r"""
(() => {
  const TARGET = __TAB__;
  const tabs = Array.from(document.querySelectorAll('[role="tab"], li.next-tabs-tab'));
  const tab = tabs.find(t => (t.textContent || '').trim() === TARGET);
  if (!tab) return { ok: false, tabs: tabs.map(t => (t.textContent || '').trim()).filter(Boolean) };
  tab.click();
  return { ok: true, clicked: TARGET };
})()
"""

READ_PANEL_JS = r"""
(() => {
  const active = Array.from(document.querySelectorAll('[role="tabpanel"], .next-tabs-content'));
  const panel = active.find(p => {
    const r = p.getBoundingClientRect();
    return r.height > 0;
  }) || document.body;

  const cards = Array.from(panel.querySelectorAll('[class*="product-card"], [class*="category"], .card-title'));
  const seen = new Set();
  const items = [];
  for (const el of panel.querySelectorAll('div,li,a,span')) {
    if (el.children.length > 2) continue;
    const text = (el.textContent || '').trim();
    // 类目名通常较短且带斜杠或多级分隔
    if (!text || text.length > 40 || seen.has(text)) continue;
    const cls = typeof el.className === 'string' ? el.className : '';
    if (!cls) continue;
    seen.add(text);
    items.push({
      text,
      tag: el.tagName.toLowerCase(),
      className: cls.slice(0, 110),
      hasSlash: text.includes('/') || text.includes('>'),
    });
    if (items.length >= 60) break;
  }

  const nextBtn = Array.from(document.querySelectorAll('button'))
    .find(b => (b.textContent || '').trim().includes('确认，下一步'));

  return {
    activePanelClass: typeof panel.className === 'string' ? panel.className.slice(0, 100) : '',
    itemCount: items.length,
    items,
    nextButton: nextBtn ? { disabled: nextBtn.disabled === true } : null,
    cardSelectorCounts: {
      'product-card': panel.querySelectorAll('[class*="product-card"]').length,
      'card-title': panel.querySelectorAll('.card-title').length,
      'category-ish': panel.querySelectorAll('[class*="category"]').length,
    },
  };
})()
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--address", default="127.0.0.1:9502")
    parser.add_argument("--tabs", default="类目,我的商品")
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

    report = {}
    with page.PageClient.connect(target["webSocketDebuggerUrl"]) as client:
        print("页面：{}".format(str(client.evaluate("location.href.split('?')[0]"))[:90]))
        for tab_name in [t.strip() for t in args.tabs.split(",") if t.strip()]:
            print()
            print("=" * 70)
            print("切到 tab：{}".format(tab_name))
            print("=" * 70)
            clicked = client.evaluate(CLICK_TAB_JS.replace("__TAB__", json.dumps(tab_name, ensure_ascii=False)))
            if not isinstance(clicked, dict) or not clicked.get("ok"):
                print("  没找到该 tab；现有 tab：{}".format(
                    json.dumps((clicked or {}).get("tabs"), ensure_ascii=False)))
                report[tab_name] = {"clicked": False, "tabs": (clicked or {}).get("tabs")}
                continue
            time.sleep(4)
            data = client.evaluate(READ_PANEL_JS)
            report[tab_name] = data
            if not isinstance(data, dict):
                print("  没读到面板")
                continue
            print("  选中面板 class：{}".format(data["activePanelClass"]))
            print("  元素计数：{}".format(json.dumps(data["cardSelectorCounts"], ensure_ascii=False)))
            print("  「确认，下一步」：{}".format(json.dumps(data["nextButton"], ensure_ascii=False)))
            print("  候选文本 {} 条（前 25）：".format(data["itemCount"]))
            for item in data["items"][:25]:
                mark = "‹类目›" if item["hasSlash"] else "      "
                print("    {} {!r:<34} <{}> {}".format(
                    mark, item["text"][:32], item["tag"], item["className"][:56]))

    TMP_DIR.mkdir(parents=True, exist_ok=True)
    out = TMP_DIR / "category-tabs-{}.json".format(datetime.now().strftime("%Y%m%d%H%M%S"))
    out.write_text(json.dumps({
        "captured_at": datetime.now().isoformat(timespec="seconds"),
        "clicked_results": False,
        "not_done": ["点击结果条目", "确认下一步", "保存草稿", "提交"],
        "tabs": report,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print()
    print("产物：{}".format(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

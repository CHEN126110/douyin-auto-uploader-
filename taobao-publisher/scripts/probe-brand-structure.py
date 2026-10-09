# -*- coding: utf-8 -*-
"""勘察：品牌下拉容器 `.next-select-popup-wrap` 的内部结构。

上一轮：下拉确实展开了（能看到品牌名文本），但 ``li`` 与 ``[role=option]`` 都是 0 个——
说明选项元素既不是 ``li`` 也不是 ``option``。本脚本逐层转储容器结构，找出真正的选项元素。

边界：只展开下拉、读结构，**不选任何值**，结束前按 Esc 收起。

用法::

    python taobao-publisher/scripts/probe-brand-structure.py --address 127.0.0.1:9502
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

OPEN_JS = """
(() => {
  const items = Array.from(document.querySelectorAll('.sell-catProp-item-common'));
  const hit = items.filter(i => {
    const l = i.querySelector('label');
    return l && (l.textContent || '').trim() === '品牌';
  });
  if (hit.length !== 1) return { ok: false, hitCount: hit.length };
  const c = hit[0].querySelector('input[role="combobox"], input');
  if (!c) return { ok: false, reason: 'no_control' };
  c.click();
  c.focus();
  return { ok: true };
})()
"""

STRUCT_JS = r"""
(() => {
  const wraps = Array.from(document.querySelectorAll('.next-select-popup-wrap, .next-overlay-inner'))
    .filter(e => e.getBoundingClientRect().height > 0);
  if (!wraps.length) return { found: false };

  const root = wraps[0];
  const rows = [];
  const walk = (el, depth) => {
    if (depth > 5 || rows.length > 45) return;
    for (const kid of Array.from(el.children).slice(0, 8)) {
      const cls = typeof kid.className === 'string' ? kid.className : '';
      const ownText = kid.children.length === 0 ? (kid.textContent || '').trim().slice(0, 22) : '';
      rows.push({
        depth,
        tag: kid.tagName.toLowerCase(),
        className: cls.slice(0, 88),
        childCount: kid.children.length,
        ownText,
        react: Object.keys(kid).some(k => k.startsWith('__react')),
      });
      walk(kid, depth + 1);
    }
  };
  walk(root, 0);

  // 直接找「文本短、children 为 0、带 React」的候选选项
  const all = Array.from(root.querySelectorAll('*'));
  const optionLike = all.filter(el => {
    const t = (el.textContent || '').trim();
    return el.children.length === 0 && t.length > 0 && t.length <= 30
      && Object.keys(el).some(k => k.startsWith('__react'));
  }).slice(0, 14).map(el => ({
    tag: el.tagName.toLowerCase(),
    className: typeof el.className === 'string' ? el.className.slice(0, 90) : '',
    text: (el.textContent || '').trim().slice(0, 26),
  }));

  return {
    found: true,
    rootClass: String(root.className).slice(0, 110),
    rootChildCount: root.children.length,
    structure: rows,
    optionLike,
  };
})()
"""

CLOSE_JS = """
(() => {
  document.body.click();
  document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', keyCode: 27, bubbles: true }));
  return 'closed';
})()
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--address", default="127.0.0.1:9502")
    parser.add_argument("--wait", type=float, default=2.5)
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
        opened = client.evaluate(OPEN_JS)
        if not isinstance(opened, dict) or not opened.get("ok"):
            print("展开失败：{}".format(json.dumps(opened, ensure_ascii=False)))
            return 1
        time.sleep(args.wait)
        data = client.evaluate(STRUCT_JS)
        client.evaluate(CLOSE_JS)

    if not isinstance(data, dict) or not data.get("found"):
        print("没有可见的下拉容器")
        return 1

    print("容器 class：{}  （直接子节点 {} 个）".format(data["rootClass"], data["rootChildCount"]))
    print()
    print("==== 结构（前 45 层节点）====")
    print("  {:>3} {:<6} {:<6} {:<40} {}".format("depth", "tag", "childs", "className", "ownText"))
    for row in data["structure"]:
        print("  {:>3} {:<6} {:<6} {:<40} {!r}".format(
            row["depth"], row["tag"], row["childCount"], row["className"][:38], row["ownText"][:20]))
    print()
    print("==== 「像选项」的叶子元素（文本短、无子节点、带 React）====")
    for item in data["optionLike"]:
        print("  <{}> {:<50} {!r}".format(item["tag"], item["className"][:48], item["text"]))

    TMP_DIR.mkdir(parents=True, exist_ok=True)
    out = TMP_DIR / "brand-structure-{}.json".format(datetime.now().strftime("%Y%m%d%H%M%S"))
    out.write_text(json.dumps({
        "captured_at": datetime.now().isoformat(timespec="seconds"),
        "selected_nothing": True,
        "not_done": ["选择品牌值", "确认下一步", "保存草稿", "提交"],
        **data,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print()
    print("产物：{}".format(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

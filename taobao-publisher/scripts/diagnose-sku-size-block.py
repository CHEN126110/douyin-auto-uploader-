# -*- coding: utf-8 -*-
"""诊断：「尺码」块的**新增值入口**在哪。

实验结论（E-094）：第一个值能提交（计数 0→1），后续值**不提交**——
只把文本填进输入框，回车与失焦都无效。
假设：那个输入框是**第一个值的编辑器**，新增值要靠一个「+」按钮加行。

本脚本把「尺码」块连同它内部的**全部按钮** dump 出来。**纯只读**。

用法::

    python taobao-publisher/scripts/diagnose-sku-size-block.py --address 127.0.0.1:9502
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

OPEN_DRAWER_JS = """
(() => {
  const btns = Array.from(document.querySelectorAll('button'))
    .filter(b => (b.textContent || '').trim() === '+ 创建规格');
  if (btns.length !== 1) return { ok: false, hitCount: btns.length };
  btns[0].click();
  return { ok: true };
})()
"""

DUMP_JS = r"""
(() => {
  const drawer = document.querySelector('.sku-decouple-drawer-container');
  if (!drawer) return { found: false };
  const block = Array.from(drawer.querySelectorAll('.common-wrap')).find(w => {
    const h = w.querySelector('.header');
    return h && (h.textContent || '').includes('尺码');
  });
  if (!block) return { found: false, reason: 'no_block' };

  const describe = (el) => ({
    tag: el.tagName.toLowerCase(),
    className: typeof el.className === 'string' ? el.className.slice(0, 90) : '',
    childCount: el.children.length,
    ownText: el.children.length === 0 ? (el.textContent || '').trim().slice(0, 26) : '',
    visible: el.getBoundingClientRect().height > 0,
    w: Math.round(el.getBoundingClientRect().width),
    h: Math.round(el.getBoundingClientRect().height),
  });

  // 逐层结构
  const rows = [];
  const walk = (el, depth) => {
    if (depth > 4 || rows.length > 50) return;
    for (const kid of Array.from(el.children)) {
      rows.push({ depth, ...describe(kid) });
      walk(kid, depth + 1);
    }
  };
  walk(block, 0);

  // 块内全部按钮
  const buttons = Array.from(block.querySelectorAll('button')).map(b => ({
    text: (b.textContent || '').trim().slice(0, 20),
    className: String(b.className).slice(0, 90),
    disabled: b.disabled === true,
    visible: b.getBoundingClientRect().height > 0,
    title: b.getAttribute('title') || '',
    ariaLabel: b.getAttribute('aria-label') || '',
  }));

  // 块内可能是「加一行」的图标
  const icons = Array.from(block.querySelectorAll('i, svg, [class*="add"], [class*="plus"]'))
    .map(describe).filter(i => i.visible).slice(0, 14);

  return {
    found: true,
    blockClass: String(block.className).slice(0, 90),
    headerText: (block.querySelector('.header') || {}).textContent || '',
    rows,
    buttons,
    icons,
    blockHtmlSample: block.innerHTML.slice(0, 1200),
  };
})()
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--address", default="127.0.0.1:9502")
    parser.add_argument("--wait", type=float, default=3.0)
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
        if not (client.evaluate(OPEN_DRAWER_JS) or {}).get("ok"):
            print("开抽屉失败")
            return 1
        time.sleep(args.wait)
        data = client.evaluate(DUMP_JS)

    if not isinstance(data, dict) or not data.get("found"):
        print("没找到尺码块")
        return 1

    print("块 class：{}".format(data["blockClass"]))
    print("header：{!r}".format((data.get("headerText") or "").strip()[:40]))
    print()
    print("==== 逐层结构 ====")
    print("  {:>2} {:<6} {:<6} {:<40} {:<6} {}".format("d", "tag", "childs", "className", "size", "ownText"))
    for row in data["rows"]:
        print("  {:>2} {:<6} {:<6} {:<40} {}x{:<4} {!r}".format(
            row["depth"], row["tag"], row["childCount"], row["className"][:38],
            row["w"], row["h"], row["ownText"][:22]))
    print()
    print("==== 块内按钮 {} 个 ====".format(len(data["buttons"])))
    for item in data["buttons"]:
        print("  {!r:<22} disabled={:<6} visible={:<6} title={!r}".format(
            item["text"][:20], item["disabled"], item["visible"], item["title"][:16]))
        print("      class={}".format(item["className"][:88]))
    print()
    print("==== 可能的「加一行」图标 {} 个 ====".format(len(data["icons"])))
    for item in data["icons"]:
        print("  <{}> {:<44} {}x{}".format(item["tag"], item["className"][:42], item["w"], item["h"]))
    print()
    print("==== innerHTML 片段 ====")
    print(data.get("blockHtmlSample") or "")

    TMP_DIR.mkdir(parents=True, exist_ok=True)
    out = TMP_DIR / "sku-size-block-{}.json".format(datetime.now().strftime("%Y%m%d%H%M%S"))
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

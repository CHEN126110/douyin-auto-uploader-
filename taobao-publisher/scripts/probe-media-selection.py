# -*- coding: utf-8 -*-
"""勘察：素材中心里一张图的**选中机制**，以及确认按钮在哪。

E-108：每张缩略图外面套着 ``<label>``（``img < .PicList_pic_imgBox < label < ...``），
说明有勾选框。但按钮列表里**没有**「确定 / 完成」——它可能在别处，
也可能选中之后才出现。

本脚本读三处：**只读**，不点任何东西。
  1. ``<label>`` 的内部结构（有没有 checkbox / radio）；
  2. 素材中心 iframe 里所有含「确定 / 完成 / 确认 / 下一步」的元素；
  3. 弹层**外层**（iframe 之外）的按钮——确认按钮可能在外层。

用法::

    python taobao-publisher/scripts/probe-media-selection.py --address 127.0.0.1:9502
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

OPEN_JS = r"""
(() => {
  const POPUP = '.sell-component-image-v2-media-popup';
  if (document.querySelector(POPUP)) return { ok: true, already: true };
  const area = Array.from(document.querySelectorAll('.sell-component-info-wrapper-wrap'))
    .find(el => (el.textContent || '').includes('1:1主图'));
  if (!area) return { ok: false, reason: 'no_area' };
  const slot = area.querySelector('.image-empty');
  if (!slot) return { ok: false, reason: 'no_slot' };
  slot.click();
  return { ok: true, already: false };
})()
"""

#: 弹层外层（iframe 之外）的结构与按钮。
OUTER_JS = r"""
(() => {
  const pop = document.querySelector('.sell-component-image-v2-media-popup');
  if (!pop) return { found: false };
  const buttons = Array.from(pop.querySelectorAll('button, [role="button"], .next-btn'))
    .map(b => ({ text: (b.textContent || '').trim().slice(0, 18),
                 className: String(b.className).slice(0, 70),
                 disabled: b.disabled === true }))
    .filter(b => b.text);
  const allText = (pop.textContent || '').trim();
  return {
    found: true,
    buttons,
    // 弹层整体文本（含 iframe 之外的页脚区）
    text: allText.slice(0, 260),
    // 弹层里的所有直接子结构
    children: Array.from(pop.querySelectorAll('.media-wrap > *')).map(el => ({
      tag: el.tagName.toLowerCase(),
      className: String(el.className).slice(0, 70),
      childCount: el.children.length,
    })),
  };
})()
"""

#: 素材中心 iframe 里的 label 结构与确认类元素。
INNER_JS = r"""
(() => {
  // 1) 一张缩略图的完整结构
  const label = document.querySelector('label');
  let labelInfo = null;
  if (label) {
    const outer = label.outerHTML;
    labelInfo = {
      html: outer.slice(0, 900),
      childTags: Array.from(label.querySelectorAll('*')).slice(0, 10).map(el => ({
        tag: el.tagName.toLowerCase(),
        className: typeof el.className === 'string' ? el.className.slice(0, 70) : '',
        type: el.getAttribute('type') || '',
        checked: el.checked === true || undefined,
      })),
    };
  }

  // 2) 全页找确认类文案
  const KEYWORDS = ['确定', '完成', '确认', '下一步', '保存', '使用'];
  const found = [];
  for (const el of Array.from(document.querySelectorAll('button, [role="button"], .next-btn, div, span'))) {
    const t = (el.textContent || '').trim();
    if (!t || t.length > 8) continue;
    if (!KEYWORDS.includes(t)) continue;
    const r = el.getBoundingClientRect();
    found.push({
      tag: el.tagName.toLowerCase(),
      text: t,
      className: typeof el.className === 'string' ? el.className.slice(0, 70) : '',
      visible: r.height > 0,
      disabled: el.disabled === true,
    });
  }
  // 去重
  const seen = new Set();
  const uniq = found.filter(f => {
    const k = f.tag + f.text + f.className;
    if (seen.has(k)) return false;
    seen.add(k);
    return true;
  });

  // 3) 输入控件（checkbox / radio）
  const inputs = Array.from(document.querySelectorAll('input[type="checkbox"], input[type="radio"]'))
    .slice(0, 6).map(el => ({
      type: el.getAttribute('type'),
      checked: el.checked === true,
      className: typeof el.className === 'string' ? el.className.slice(0, 60) : '',
    }));

  return { labelInfo, confirmLike: uniq.slice(0, 12), selectionInputs: inputs };
})()
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--address", default="127.0.0.1:9502")
    parser.add_argument("--wait", type=float, default=4.0)
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
        print("打开弹层：{}".format(json.dumps(opened, ensure_ascii=False)))
        time.sleep(args.wait)

        outer = client.evaluate(OUTER_JS)
        context_id = page.media_iframe_context(client)
        inner = client.evaluate(INNER_JS, context_id=context_id)

    print()
    print("==== 弹层外层 ====")
    if isinstance(outer, dict) and outer.get("found"):
        print("  子结构：{}".format(json.dumps(outer.get("children"), ensure_ascii=False)))
        print("  按钮 {} 个：".format(len(outer.get("buttons") or [])))
        for item in outer.get("buttons") or []:
            print("      {!r:<20} disabled={} class={}".format(
                item["text"][:18], item["disabled"], item["className"][:56]))
        print("  文本：{!r}".format((outer.get("text") or "")[:200]))

    print()
    print("==== 缩略图 label ====")
    info = (inner or {}).get("labelInfo")
    if info:
        print("  内部标签：")
        for item in info["childTags"]:
            mark = ""
            if item.get("type"):
                mark = " type={} checked={}".format(item["type"], item.get("checked"))
            print("      <{}> {}{}".format(item["tag"], item["className"][:60], mark))
        print()
        print("  HTML 片段：")
        print("  {}".format(info["html"][:600]))
    else:
        print("  iframe 里没有 label")

    print()
    print("==== 确认类文案（iframe 内）====")
    for item in (inner or {}).get("confirmLike") or []:
        print("  <{}> {!r:<8} visible={:<6} disabled={:<6} class={}".format(
            item["tag"], item["text"], item["visible"], item["disabled"],
            item["className"][:56]))
    if not (inner or {}).get("confirmLike"):
        print("  **没有找到**")

    print()
    print("==== 选择用输入控件 ====")
    print("  {}".format(json.dumps((inner or {}).get("selectionInputs"), ensure_ascii=False)))

    TMP_DIR.mkdir(parents=True, exist_ok=True)
    out = TMP_DIR / "media-selection-{}.json".format(datetime.now().strftime("%Y%m%d%H%M%S"))
    out.write_text(json.dumps({
        "captured_at": datetime.now().isoformat(timespec="seconds"),
        "selected_nothing": True,
        "clicked_nothing": True,
        "outer": outer,
        "inner": inner,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print()
    print("产物：{}".format(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

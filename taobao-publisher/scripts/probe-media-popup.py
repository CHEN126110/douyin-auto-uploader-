# -*- coding: utf-8 -*-
"""勘察：图片选择弹层（``sell-component-image-v2-media-popup``）的内部结构。

E-101：点击「上传图片」不会弹出原生文件框，而是打开这个弹层
（走素材中心 / 图片空间）。本脚本把它内部结构 dump 出来，
重点找：有没有 ``input[type=file]``、上传入口是什么。

**只读**：只打开弹层读结构，结束前关闭。**不选图、不上传。**

用法::

    python taobao-publisher/scripts/probe-media-popup.py --address 127.0.0.1:9502
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
  const area = Array.from(document.querySelectorAll('.sell-component-info-wrapper-wrap'))
    .find(el => (el.textContent || '').includes('1:1主图'));
  if (!area) return { ok: false, reason: 'no_1to1_area' };
  const slot = area.querySelector('.image-empty, .upload-text');
  if (!slot) return { ok: false, reason: 'no_slot' };
  slot.click();
  return { ok: true };
})()
"""

DUMP_JS = r"""
(() => {
  const pop = document.querySelector('.sell-component-image-v2-media-popup');
  if (!pop) return { found: false };
  const r = pop.getBoundingClientRect();

  const describe = (el) => ({
    tag: el.tagName.toLowerCase(),
    className: typeof el.className === 'string' ? el.className.slice(0, 90) : '',
    childCount: el.children.length,
    ownText: el.children.length === 0 ? (el.textContent || '').trim().slice(0, 30) : '',
    size: Math.round(el.getBoundingClientRect().width) + 'x' +
          Math.round(el.getBoundingClientRect().height),
  });

  const rows = [];
  const walk = (el, depth) => {
    if (depth > 4 || rows.length > 60) return;
    for (const kid of Array.from(el.children)) {
      rows.push({ depth, ...describe(kid) });
      walk(kid, depth + 1);
    }
  };
  walk(pop, 0);

  return {
    found: true,
    popupClass: String(pop.className).slice(0, 110),
    size: Math.round(r.width) + 'x' + Math.round(r.height),
    structure: rows,
    fileInputs: Array.from(pop.querySelectorAll('input[type="file"]')).map(el => ({
      accept: el.getAttribute('accept') || '',
      multiple: el.multiple === true,
      className: typeof el.className === 'string' ? el.className.slice(0, 60) : '',
    })),
    buttons: Array.from(pop.querySelectorAll('button'))
      .map(b => ({ text: (b.textContent || '').trim().slice(0, 18),
                   className: String(b.className).slice(0, 70) }))
      .filter(b => b.text),
    tabs: Array.from(pop.querySelectorAll('.next-tabs-tab-inner, [class*="tab"]'))
      .map(el => (el.textContent || '').trim()).filter(t => t && t.length <= 12).slice(0, 10),
    iframes: Array.from(pop.querySelectorAll('iframe')).map(f => String(f.src).slice(0, 100)),
    text: (pop.textContent || '').trim().slice(0, 220),
  };
})()
"""

CLOSE_JS = r"""
(() => {
  const pop = document.querySelector('.sell-component-image-v2-media-popup');
  if (!pop) return 'no_popup';
  const btns = Array.from(pop.querySelectorAll('button'));
  const cancel = btns.find(b => ['取消', '关闭'].includes((b.textContent || '').trim()));
  if (cancel) { cancel.click(); return 'clicked_cancel'; }
  const closer = pop.querySelector('.next-dialog-close, [aria-label="close"], .next-overlay-close');
  if (closer) { closer.click(); return 'clicked_close'; }
  document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', keyCode: 27, bubbles: true }));
  return 'escape';
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
        # 弹层可能已经开着（上一个脚本点过）
        already = client.evaluate("Boolean(document.querySelector('.sell-component-image-v2-media-popup'))")
        if not already:
            opened = client.evaluate(OPEN_JS)
            print("打开弹层：{}".format(json.dumps(opened, ensure_ascii=False)))
            time.sleep(args.wait)
        else:
            print("弹层已经开着，直接读")

        data = client.evaluate(DUMP_JS)
        closed = client.evaluate(CLOSE_JS)

    if not isinstance(data, dict) or not data.get("found"):
        print("没找到弹层")
        return 1

    print()
    print("弹层 class：{}".format(data["popupClass"]))
    print("尺寸：{}".format(data["size"]))
    print("文本：{!r}".format(data["text"][:180]))
    print()
    print("==== input[type=file]：{} 个 ====".format(len(data["fileInputs"])))
    for item in data["fileInputs"]:
        print("  accept={!r} multiple={} class={}".format(
            item["accept"][:50], item["multiple"], item["className"][:50]))
    print()
    print("==== 按钮 {} 个 ====".format(len(data["buttons"])))
    for item in data["buttons"][:14]:
        print("  {!r:<20} class={}".format(item["text"][:18], item["className"][:66]))
    if data["tabs"]:
        print()
        print("==== tab ====")
        print("  {}".format(json.dumps(data["tabs"], ensure_ascii=False)))
    if data["iframes"]:
        print()
        print("==== iframe ====")
        for src in data["iframes"]:
            print("  {}".format(src))
    print()
    print("==== 逐层结构（前 40 个）====")
    print("  {:>2} {:<6} {:<6} {:<40} {:<9} {}".format("d", "tag", "childs", "className", "size", "ownText"))
    for row in data["structure"][:40]:
        print("  {:>2} {:<6} {:<6} {:<40} {:<9} {!r}".format(
            row["depth"], row["tag"], row["childCount"], row["className"][:38],
            row["size"], row["ownText"][:24]))
    print()
    print("关闭动作：{}".format(closed))

    TMP_DIR.mkdir(parents=True, exist_ok=True)
    out = TMP_DIR / "media-popup-{}.json".format(datetime.now().strftime("%Y%m%d%H%M%S"))
    out.write_text(json.dumps({
        "captured_at": datetime.now().isoformat(timespec="seconds"),
        "selected_nothing": True,
        "uploaded_nothing": True,
        **data,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print("产物：{}".format(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

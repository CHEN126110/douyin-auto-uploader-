# -*- coding: utf-8 -*-
"""勘察：素材中心里「图片空间」的项目结构与确认入口。

E-106 已实证空间里有历史素材，所以**不需要新上传**就能实证「选图入位」——
选一张已有的图，看它怎么被选中、怎么确认、主图位怎么回填。

本脚本在素材中心 iframe 的上下文里跑，**只读**：不选图、不点确认。

用法::

    python taobao-publisher/scripts/probe-media-space-items.py --address 127.0.0.1:9502
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

#: 在素材中心 iframe 里跑的探测。
SPACE_JS = r"""
(() => {
  const describe = (el) => ({
    tag: el.tagName.toLowerCase(),
    className: typeof el.className === 'string' ? el.className.slice(0, 80) : '',
    childCount: el.children.length,
    text: (el.textContent || '').trim().slice(0, 30),
    size: Math.round(el.getBoundingClientRect().width) + 'x' +
          Math.round(el.getBoundingClientRect().height),
  });

  // 图片缩略图：找 img 元素
  const imgs = Array.from(document.querySelectorAll('img')).filter(i => {
    const r = i.getBoundingClientRect();
    return r.width > 20 && r.height > 20;
  });
  const thumbs = imgs.slice(0, 8).map(i => ({
    src: String(i.src || '').slice(0, 80),
    alt: i.getAttribute('alt') || '',
    size: Math.round(i.getBoundingClientRect().width) + 'x' +
          Math.round(i.getBoundingClientRect().height),
    // 缩略图的祖先链，用于判断「卡片」的类名
    chain: (() => {
      const parts = []; let n = i;
      for (let k = 0; k < 5 && n; k++) {
        const c = typeof n.className === 'string' ? n.className.trim().split(/\s+/)[0] : '';
        parts.push(n.tagName.toLowerCase() + (c ? '.' + c : ''));
        n = n.parentElement;
      }
      return parts.join(' < ');
    })(),
  }));

  // 可能的卡片容器
  const CARD_GUESS = ['[class*="card"]', '[class*="item"]', '[class*="thumb"]', '[class*="pic"]'];
  const cards = {};
  for (const sel of CARD_GUESS) {
    cards[sel] = document.querySelectorAll(sel).length;
  }

  // 全部可见按钮（找「确定 / 确认 / 完成」）
  const buttons = Array.from(document.querySelectorAll('button, [role="button"], .next-btn'))
    .filter(b => b.getBoundingClientRect().height > 0)
    .map(b => ({
      text: (b.textContent || '').trim().slice(0, 16),
      className: String(b.className).slice(0, 70),
      disabled: b.disabled === true,
    }))
    .filter(b => b.text);

  // 可见 tab / 分类
  const tabs = Array.from(document.querySelectorAll('[class*="tab"], [class*="menu-item"], [class*="category"]'))
    .filter(e => e.getBoundingClientRect().height > 0)
    .map(e => (e.textContent || '').trim())
    .filter(t => t && t.length <= 14);

  return {
    href: location.href.slice(0, 120),
    thumbCount: thumbs.length,
    thumbs,
    cardCounts: cards,
    buttons: buttons.slice(0, 20),
    tabs: [...new Set(tabs)].slice(0, 16),
    bodyText: (document.body ? document.body.innerText : '').replace(/\s+/g, ' ').trim().slice(0, 350),
  };
})()
"""

CLOSE_JS = r"""
(() => {
  const pop = document.querySelector('.sell-component-image-v2-media-popup');
  if (!pop) return 'no_popup';
  document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', keyCode: 27, bubbles: true }));
  return 'escape';
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

        context_id = page.media_iframe_context(client)
        print("素材中心上下文 id = {}".format(context_id))
        time.sleep(2.0)

        data = client.evaluate(SPACE_JS, context_id=context_id)
        client.evaluate(CLOSE_JS)

    if not isinstance(data, dict):
        print("没读到素材中心内容")
        return 1

    print()
    print("href: {}".format(data.get("href")))
    print()
    print("==== 缩略图 {} 张 ====".format(data.get("thumbCount")))
    for item in (data.get("thumbs") or [])[:6]:
        print("  alt={!r} size={}".format(item["alt"][:40], item["size"]))
        print("      chain={}".format(item["chain"][:110]))
    print()
    print("==== 候选卡片容器计数 ====")
    print("  {}".format(json.dumps(data.get("cardCounts"), ensure_ascii=False)))
    print()
    print("==== 按钮 ====")
    for item in (data.get("buttons") or [])[:14]:
        print("  {!r:<20} disabled={:<6} class={}".format(
            item["text"][:16], item["disabled"], item["className"][:60]))
    print()
    print("==== tab / 分类 ====")
    print("  {}".format(json.dumps(data.get("tabs"), ensure_ascii=False)))
    print()
    print("==== 页面文本 ====")
    print("  {!r}".format((data.get("bodyText") or "")[:300]))

    TMP_DIR.mkdir(parents=True, exist_ok=True)
    out = TMP_DIR / "media-space-items-{}.json".format(datetime.now().strftime("%Y%m%d%H%M%S"))
    out.write_text(json.dumps({
        "captured_at": datetime.now().isoformat(timespec="seconds"),
        "selected_nothing": True,
        "clicked_confirm": False,
        **data,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print()
    print("产物：{}".format(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

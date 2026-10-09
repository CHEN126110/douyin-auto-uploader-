# -*- coding: utf-8 -*-
"""实验：在图片空间里**选一张已有的图**，看主图位怎么回填。

E-109：弹层外层 0 个按钮、iframe 里找不到「确定/完成」文案，
但存在 6 个 ``input[type=checkbox].next-checkbox-input``（全未选中）。
URL 带 ``max=1`` 与 ``realTimeSel...``，猜测是**实时选择**（点即生效）。

**本实验不使用任何上传**——选的是图片空间里已有的历史素材（E-106）。

**这会改变未保存表单的状态**（把一张已有图设为 1:1 主图），
但不保存草稿、不上架、不提交。

用法::

    python taobao-publisher/scripts/experiment-media-select.py --address 127.0.0.1:9502 --allow-write
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

#: 列出可选的图卡片（按 checkbox 定位到卡片）。
LIST_JS = r"""
(() => {
  const boxes = Array.from(document.querySelectorAll('input[type="checkbox"].next-checkbox-input'));
  const cards = boxes.map((box, i) => {
    // 往上找到卡片容器
    let node = box, chain = [];
    for (let k = 0; k < 6 && node; k++) {
      const c = typeof node.className === 'string' ? node.className.trim().split(/\s+/)[0] : '';
      chain.push(node.tagName.toLowerCase() + (c ? '.' + c : ''));
      node = node.parentElement;
    }
    const card = box.closest('div[class*="PicList_pic_background"], div[class*="pic_background"]')
      || box.parentElement;
    const name = card ? (card.textContent || '').trim().slice(0, 50) : '';
    return {
      index: i,
      checked: box.checked === true,
      chain: chain.join(' < '),
      cardText: name,
      cardClass: card && typeof card.className === 'string' ? card.className.slice(0, 80) : '',
    };
  });
  return { count: cards.length, cards };
})()
"""

#: 点**第一张**图的卡片（真实点击 img 或它的祖先，模拟人工）。
CLICK_FIRST_JS = r"""
(() => {
  const img = Array.from(document.querySelectorAll('img')).find(i => {
    const r = i.getBoundingClientRect();
    return r.width > 20 && r.height > 20;
  });
  if (!img) return { ok: false, reason: 'no_thumb' };

  // 往上找到一个带 label 或 checkbox 的可点祖先
  let target = img;
  let node = img;
  for (let k = 0; k < 6 && node; k++) {
    if (node.tagName.toLowerCase() === 'label' || node.querySelector('input[type="checkbox"]')) {
      target = node;
      break;
    }
    node = node.parentElement;
  }
  const r = target.getBoundingClientRect();
  target.click();
  return {
    ok: true,
    clickedTag: target.tagName.toLowerCase(),
    clickedClass: typeof target.className === 'string' ? target.className.slice(0, 70) : '',
    size: Math.round(r.width) + 'x' + Math.round(r.height),
  };
})()
"""

#: 读主图位状态（弹层外的主 frame）。
SLOT_JS = r"""
(() => {
  const POPUP = '.sell-component-image-v2-media-popup';
  const popup = document.querySelector(POPUP);
  const area = Array.from(document.querySelectorAll('.sell-component-info-wrapper-wrap'))
    .find(el => (el.textContent || '').includes('1:1主图'));
  if (!area) return { found: false, reason: 'no_area' };
  // 已填的图位：有 img 或不再是 image-empty
  const filled = Array.from(area.querySelectorAll('.sell-component-material-item-view'))
    .filter(el => !el.querySelector('.image-empty'));
  const imgs = Array.from(area.querySelectorAll('img'))
    .map(i => String(i.src || '').slice(0, 100));
  return {
    found: true,
    popupOpen: Boolean(popup && popup.getBoundingClientRect().height > 0),
    slotCount: area.querySelectorAll('.sell-component-material-item-view').length,
    emptyCount: area.querySelectorAll('.image-empty').length,
    filledCount: filled.length,
    images: imgs.slice(0, 4),
    text: (area.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 120),
  };
})()
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--address", default="127.0.0.1:9502")
    parser.add_argument("--allow-write", action="store_true")
    parser.add_argument("--wait", type=float, default=4.0)
    args = parser.parse_args()

    if not args.allow_write:
        print("这会把图片空间里的一张已有图设为 1:1 主图（改未保存表单状态），"
              "必须显式加 --allow-write。")
        return 2

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

    steps = []
    with page.PageClient.connect(target["webSocketDebuggerUrl"]) as client:
        before = client.evaluate(SLOT_JS)
        print("点击前主图位：{}".format(json.dumps(before, ensure_ascii=False)[:200]))
        steps.append({"step": "before", "state": before})

        opened = client.evaluate(OPEN_JS)
        if not (isinstance(opened, dict) and opened.get("ok")):
            print("打开弹层失败：{}".format(json.dumps(opened, ensure_ascii=False)))
            return 1
        time.sleep(args.wait)

        context_id = page.media_iframe_context(client)
        print("素材中心上下文 id = {}".format(context_id))
        time.sleep(2.0)

        listing = client.evaluate(LIST_JS, context_id=context_id)
        print()
        print("可选的图卡片：{} 张".format((listing or {}).get("count")))
        for card in ((listing or {}).get("cards") or [])[:5]:
            print("  [{}] checked={} text={!r}".format(
                card["index"], card["checked"], card["cardText"][:36]))
            print("      chain={}".format(card["chain"][:100]))
        steps.append({"step": "list", "listing": listing})

        print()
        print("── 点第一张图的卡片 ──")
        clicked = client.evaluate(CLICK_FIRST_JS, context_id=context_id)
        print("  {}".format(json.dumps(clicked, ensure_ascii=False)))
        steps.append({"step": "click", "result": clicked})
        time.sleep(args.wait + 2)

        after_selection = client.evaluate(LIST_JS, context_id=context_id)
        checked = [c for c in ((after_selection or {}).get("cards") or []) if c["checked"]]
        print("  选中数：{}".format(len(checked)))
        steps.append({"step": "after_click", "listing": after_selection})

        after = client.evaluate(SLOT_JS)
        print()
        print("点击后主图位：{}".format(json.dumps(after, ensure_ascii=False)[:240]))
        steps.append({"step": "after", "state": after})

    print()
    print("==== 结论 ====")
    b, a = before or {}, after or {}
    print("  弹层是否关闭：{} → {}".format(b.get("popupOpen"), a.get("popupOpen")))
    print("  空位数：{} → {}".format(b.get("emptyCount"), a.get("emptyCount")))
    print("  已填数：{} → {}".format(b.get("filledCount"), a.get("filledCount")))
    if a.get("filledCount", 0) > b.get("filledCount", 0):
        print("  → **选图入位成功**：点图即生效，弹层自动关闭")
    elif not a.get("popupOpen") and b.get("popupOpen"):
        print("  → 弹层关了但主图位没变，需要进一步观察")
    else:
        print("  → 无变化：选中可能还需要点确认，或点击目标不对")

    TMP_DIR.mkdir(parents=True, exist_ok=True)
    out = TMP_DIR / "media-select-{}.json".format(datetime.now().strftime("%Y%m%d%H%M%S"))
    out.write_text(json.dumps({
        "captured_at": datetime.now().isoformat(timespec="seconds"),
        "uploaded_nothing": True,
        "used_existing_space_image": True,
        "never_did": ["上传任何文件", "保存草稿", "提交宝贝信息"],
        "steps": steps,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print()
    print("产物：{}".format(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

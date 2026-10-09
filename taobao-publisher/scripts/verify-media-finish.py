# -*- coding: utf-8 -*-
"""验证：点上传面板的「完成」之后，图是否真的进了图片空间。

E-123 的验证脚本。面板里已经排着 5 个带成功图标的文件，
所以直接点「完成」，然后看空间里有没有它们。

**这会真的把文件落库到店铺图片空间**（如果有落点的话）。

用法::

    python taobao-publisher/scripts/verify-media-finish.py --address 127.0.0.1:9502 --allow-write
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

NAMES = ["主图_01_1x1.jpg", "主图_02_1x1.jpg", "主图_03_1x1.jpg",
         "主图_04_1x1.jpg", "主图_05_1x1.jpg"]

STATE_JS = r"""
(() => {
  const cards = Array.from(document.querySelectorAll('[class*="PicList_pic_background"]'));
  const texts = cards.map(el => (el.textContent || '').trim());
  const panelItems = document.querySelectorAll('[class*="UploadPanel_fileItem"]').length;
  return {
    cardCount: cards.length,
    x1x1Cards: texts.filter(t => /1x1/.test(t)).slice(0, 8),
    panelItems,
    popupOpen: Boolean(document.querySelector('.sell-component-image-v2-media-popup')),
  };
})()
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--address", default="127.0.0.1:9502")
    parser.add_argument("--allow-write", action="store_true")
    args = parser.parse_args()

    if not args.allow_write:
        print("这会点「完成」把文件落库到店铺图片空间，必须显式加 --allow-write。")
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

    with page.PageClient.connect(target["webSocketDebuggerUrl"]) as client:
        if not client.evaluate(
                "Boolean(document.querySelector('.sell-component-image-v2-media-popup'))"):
            print("弹层没开——先打开它")
            return 1
        context_id = page.media_iframe_context(client)

        before = client.evaluate(STATE_JS, context_id=context_id)
        print("点「完成」之前：{}".format(json.dumps(before, ensure_ascii=False)))
        print("  空间里已有的 1x1 卡片：{}".format(before.get("x1x1Cards") or "（无）"))
        print("  面板队列项：{}".format(before.get("panelItems")))

        if not before.get("panelItems"):
            print()
            print("上传面板里没有排队的文件——先跑一次上传")
            return 1

        print()
        print("── 点「完成」 ──")
        try:
            clicked = page.click_media_finish(client, context_id=context_id, wait=5.0)
            print("  {}".format(json.dumps(clicked, ensure_ascii=False)))
        except Exception as exc:  # noqa: BLE001
            print("  失败：{}".format(exc))
            return 1

        # 等落库
        print()
        print("轮询空间…")
        deadline = time.time() + 90
        last = {}
        while time.time() < deadline:
            time.sleep(5)
            last = client.evaluate(STATE_JS, context_id=context_id)
            hits = [n for n in NAMES
                    if page.media_image_exists(client, n, context_id=context_id)]
            in_cards = last.get("x1x1Cards") or []
            print("  卡片={} 面板项={} 1x1卡片={} 按名找到={}".format(
                last.get("cardCount"), last.get("panelItems"),
                len(in_cards), len(hits)))
            if len(in_cards) >= len(NAMES):
                break

        final_hits = [n for n in NAMES
                      if page.media_image_exists(client, n, context_id=context_id)]
        final_cards = last.get("x1x1Cards") or []

    print()
    print("==== 结论 ====")
    print("  空间里的 1x1 卡片：{}".format(final_cards or "（无）"))
    print("  按文件名找到：{}".format(final_hits or "（无）"))
    ok = len(final_cards) >= 1
    print("  → {}".format("**上传落库成功**" if ok else "仍未落库"))

    TMP_DIR.mkdir(parents=True, exist_ok=True)
    out = TMP_DIR / "media-finish-{}.json".format(datetime.now().strftime("%Y%m%d%H%M%S"))
    out.write_text(json.dumps({
        "captured_at": datetime.now().isoformat(timespec="seconds"),
        "clicked_finish": True,
        "before": before,
        "after": last,
        "final_cards": final_cards,
        "final_hits": final_hits,
        "landed": ok,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print()
    print("产物：{}".format(out))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

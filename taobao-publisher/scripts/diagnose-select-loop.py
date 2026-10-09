# -*- coding: utf-8 -*-
"""逐步诊断：逐张选图时每一步的状态。

E-124：阶段报告 5 张都「选中成功」，但主图位只填上 1 个。
`select_media_image` 返回 ok 却不见效，说明**点击落空了**——
要么弹层没真的打开，要么点到的卡片不是目标。

本脚本把每一步都打出来：弹层开关、卡片数、目标是否命中、主图位数变化。

**会真的选图**（改未保存表单状态），不保存草稿、不提交。

用法::

    python taobao-publisher/scripts/diagnose-select-loop.py --address 127.0.0.1:9502 --allow-write
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--address", default="127.0.0.1:9502")
    parser.add_argument("--allow-write", action="store_true")
    args = parser.parse_args()

    if not args.allow_write:
        print("这会真的选图（改未保存表单状态），必须显式加 --allow-write。")
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
        page.close_media_popup(client, wait=2)
        before = page.read_main_image_slots(client)
        print("起始主图位：已填 {} / {}".format(before.get("filled"), before.get("total")))
        print()

        context_id = None
        for index, name in enumerate(NAMES):
            print("── [{}] {} ──".format(index, name))
            record = {"index": index, "name": name}

            popup_before = page.read_media_popup(client)
            record["popupBeforeOpen"] = bool(popup_before.get("open"))
            print("  打开前弹层: {}".format(record["popupBeforeOpen"]))

            opened = page.open_media_popup(client, wait=2.5)
            record["opened"] = opened
            print("  open_media_popup -> {}".format(json.dumps(opened, ensure_ascii=False)[:90]))

            popup_after = page.read_media_popup(client)
            record["popupAfterOpen"] = bool(popup_after.get("open"))
            print("  打开后弹层: {}".format(record["popupAfterOpen"]))
            if not popup_after.get("open"):
                print("  **弹层没打开，跳过**")
                steps.append(record)
                continue

            try:
                context_id = page.media_iframe_context(client)
            except Exception as exc:  # noqa: BLE001
                print("  找上下文失败: {}".format(exc))
                record["contextError"] = str(exc)
                steps.append(record)
                continue
            record["contextId"] = context_id

            cards = page.wait_for_media_cards(client, context_id=context_id)
            record["cards"] = cards
            print("  可见卡片: {}".format(cards))

            slots_before = page.read_main_image_slots(client)
            record["filledBefore"] = slots_before.get("filled")
            print("  选择前已填: {}".format(record["filledBefore"]))

            try:
                picked = page.select_media_image(client, name, context_id=context_id)
                record["picked"] = picked
                print("  选中 -> {}".format(json.dumps(picked, ensure_ascii=False)[:110]))
            except Exception as exc:  # noqa: BLE001
                record["pickError"] = "{}: {}".format(type(exc).__name__, exc)
                print("  选中失败: {}".format(exc))
                steps.append(record)
                continue

            time.sleep(2.5)
            slots_after = page.read_main_image_slots(client)
            record["filledAfter"] = slots_after.get("filled")
            record["popupAfterPick"] = bool(page.read_media_popup(client).get("open"))
            print("  选择后已填: {}（弹层还开着: {}）".format(
                record["filledAfter"], record["popupAfterPick"]))
            print()
            steps.append(record)

        final = page.read_main_image_slots(client)
        page.close_media_popup(client, wait=2)

    print("=" * 60)
    print("起始已填 {} → 最终已填 {}".format(before.get("filled"), final.get("filled")))
    print()
    print("逐次明细：")
    for item in steps:
        print("  [{}] {:<22} 弹层={} 卡片={} 已填 {}→{} {}".format(
            item["index"], item["name"],
            item.get("popupAfterOpen"),
            item.get("cards"),
            item.get("filledBefore"), item.get("filledAfter"),
            item.get("pickError") or item.get("contextError") or ""))

    TMP_DIR.mkdir(parents=True, exist_ok=True)
    out = TMP_DIR / "select-loop-{}.json".format(datetime.now().strftime("%Y%m%d%H%M%S"))
    out.write_text(json.dumps({
        "captured_at": datetime.now().isoformat(timespec="seconds"),
        "before": before,
        "final": final,
        "steps": steps,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print()
    print("产物：{}".format(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

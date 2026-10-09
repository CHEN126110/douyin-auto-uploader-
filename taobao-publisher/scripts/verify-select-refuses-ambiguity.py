# -*- coding: utf-8 -*-
"""只读实机验证：`select_media_image` 在**命中多张时必须拒绝**。

第 31 轮发现：选图在命中多张时**静默挑了第一张**（实测见过 `matched=3`），
于是可能点中**别人的图**。改法是「命中不是恰好 1 张就拒绝，不许猜」。

这项改动一直没实机跑过——因为它看起来要靠上传（上传正被平台限流）。
**但其实不用**：图片空间里**本来就有同名多份的图**，直接拿它们验证即可。

而且这个行为**在点击之前就拒绝**，所以整个验证**等于只读**——
主图位不会被填、页面不会被改。

用法::

    python taobao-publisher/scripts/verify-select-refuses-ambiguity.py --address 127.0.0.1:9502
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


def popup_open(client) -> bool:
    return bool(client.evaluate(
        "Boolean(document.querySelector('.sell-component-image-v2-media-popup')"
        " && document.querySelector('.sell-component-image-v2-media-popup')"
        ".getBoundingClientRect().height > 0)"))


def duplicate_names(client, context_id):
    """渲染窗口里出现多次的图片名。"""

    payload = client.evaluate("""
(() => {
  const cards = Array.from(document.querySelectorAll('[class*="PicList_pic_background"]'));
  const counts = {};
  for (const el of cards) {
    const text = (el.textContent || '').trim();
    const match = text.match(/^([^ ]+\\.(?:jpg|jpeg|png|webp))/i);
    const name = match ? match[1] : text.slice(0, 30);
    counts[name] = (counts[name] || 0) + 1;
  }
  return counts;
})()
""", context_id=context_id)
    if not isinstance(payload, dict):
        return []
    return sorted(((name, n) for name, n in payload.items() if n > 1),
                  key=lambda item: -item[1])


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

    steps = []
    with page.PageClient.connect(target["webSocketDebuggerUrl"]) as client:
        if not popup_open(client):
            page.open_media_popup(client)
            time.sleep(4)
        if not popup_open(client):
            print("弹层没打开")
            return 1

        context_id = page.media_iframe_context(client)
        page.wait_for_media_cards(client, context_id=context_id)

        duplicates = duplicate_names(client, context_id)
        print("渲染窗口里的同名多份：")
        for name, count in duplicates[:8]:
            print("  {:<26} {} 张".format(name, count))
        if not duplicates:
            print("  （没有）——这项验证需要至少一个同名多份的图")
            return 1

        before = page.read_main_image_slots(client)
        print()
        print("验证前主图位：已填 {} / {}".format(before.get("filled"), before.get("total")))

        print()
        print("==== 逐个试「命中多张」的名字，看是否拒绝 ====")
        results = []
        for name, count in duplicates[:3]:
            record = {"name": name, "cardsInWindow": count}
            try:
                picked = page.select_media_image(client, name, context_id=context_id)
                record["refused"] = False
                record["returned"] = picked
                print("  {:<24} **没有拒绝**（matched={}）".format(name, picked.get("matched")))
            except Exception as exc:  # noqa: BLE001
                record["refused"] = True
                record["error"] = "{}: {}".format(type(exc).__name__, str(exc)[:120])
                print("  {:<24} 已拒绝 ✓".format(name))
                print("      {}".format(str(exc)[:110]))
            results.append(record)

        # 反向对照：一个**绝不存在**的名字也该拒绝（但原因是「没有」而不是「多张」）
        print()
        print("==== 对照：不存在的名字 ====")
        try:
            page.select_media_image(client, "绝不存在的图_ZZ.jpg", context_id=context_id)
            print("  **没有拒绝**（不对）")
            control = {"refused": False}
        except Exception as exc:  # noqa: BLE001
            print("  已拒绝 ✓ {}".format(str(exc)[:100]))
            control = {"refused": True, "error": str(exc)[:120]}

        after = page.read_main_image_slots(client)
        print()
        print("验证后主图位：已填 {} / {}".format(after.get("filled"), after.get("total")))

    print()
    print("=" * 66)
    all_refused = all(r.get("refused") for r in results) and control.get("refused")
    untouched = before.get("filled") == after.get("filled")
    print("  命中多张的全部被拒：{}".format(all_refused))
    print("  主图位未被改动：    {}".format(untouched))
    print("  → {}".format(
        "**「命中多张即拒绝」在实机上生效**" if all_refused and untouched
        else "**不符合预期，见上**"))

    TMP_DIR.mkdir(parents=True, exist_ok=True)
    out = TMP_DIR / "select-ambiguity-{}.json".format(datetime.now().strftime("%Y%m%d%H%M%S"))
    out.write_text(json.dumps({
        "captured_at": datetime.now().isoformat(timespec="seconds"),
        "read_only": True,
        "never_did": ["上传", "保存草稿", "提交宝贝信息"],
        "slots_before": before,
        "slots_after": after,
        "results": results,
        "control": control,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print()
    print("产物：{}".format(out))
    return 0 if (all_refused and untouched) else 1


if __name__ == "__main__":
    raise SystemExit(main())

# -*- coding: utf-8 -*-
"""盯住一次上传的完整生命周期，找出**图到底有没有落库**。

上一轮 A/B 实测：改名与不改名都不落库，而 E-123 那轮同一个「完成」按钮是能落库的。
本脚本用一个**绝不重名的文件名**上传，然后每 2 秒采样一次：

* 上传面板里的项数（队列有没有被消费掉）
* 空间卡片数与总数
* 「上传至」当前显示的目标
* 页面上的 toast / 错误提示

**会真的往店铺图片空间传一张图**，必须显式加 ``--allow-write``。

用法::

    python taobao-publisher/scripts/probe-upload-lifecycle.py --address 127.0.0.1:9502 --allow-write
"""

from __future__ import annotations

import argparse
import json
import os
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


def state_js(name: str) -> str:
    return """
(() => {{
  const NAME = {name};
  const cards = Array.from(document.querySelectorAll('[class*="PicList_pic_background"]'));
  const texts = cards.map(el => (el.textContent || '').trim());
  const body = document.body ? document.body.innerText : '';

  // 「上传至」当前的目标
  const dirEl = document.querySelector('[class*="UploadPanel_uploadDir"], [class*="uploadDir"]');
  const dir = dirEl ? (dirEl.textContent || '').trim().slice(0, 24) : '';

  // toast / 提示（next-message / next-toast）
  const toasts = Array.from(document.querySelectorAll(
    '[class*="next-message"], [class*="next-toast"], [class*="Message"]'))
    .map(e => (e.textContent || '').trim()).filter(Boolean).slice(0, 4);

  return {{
    panelItems: document.querySelectorAll('[class*="UploadPanel_fileItem"]').length,
    panelNames: Array.from(document.querySelectorAll('[class*="UploadPanel_fileName"]'))
      .map(e => (e.textContent || '').trim()).slice(0, 4),
    panelStates: Array.from(document.querySelectorAll('[class*="UploadPanel_fileState"]'))
      .map(e => (e.textContent || '').trim() || String((e.querySelector('i') || {{}}).className || '').slice(0, 46))
      .slice(0, 4),
    cardCount: cards.length,
    // 卡片文本里有没有这个名字（去掉扩展名匹配，避免平台改名）
    cardsMatching: texts.filter(t => t.includes(NAME.replace('.jpg', ''))).length,
    dir: dir,
    toasts: toasts,
    bodyHasUploadError: /上传失败|格式不|过大|超出|不允许/.test(body),
  }};
}})()
""".format(name=json.dumps(name, ensure_ascii=False))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--address", default="127.0.0.1:9502")
    parser.add_argument("--allow-write", action="store_true")
    parser.add_argument("--watch", type=int, default=40)
    args = parser.parse_args()

    if not args.allow_write:
        print("这会真的往店铺图片空间传一张图，必须显式加 --allow-write。")
        return 2

    base = Path(os.environ["LOCALAPPDATA"]) / "com.dyin.sock-publisher" / "uploads" / "products"
    product_dirs = [d for d in base.iterdir() if d.is_dir()]
    main_dir = product_dirs[0] / "主图"
    source = sorted(p for p in main_dir.iterdir() if p.name.endswith("_1x1.jpg"))[0]

    stamp = datetime.now().strftime("%H%M%S")
    target_name = "ZZ探针_{}_1x1.jpg".format(stamp)
    print("源文件: {}".format(source.name))
    print("目标名: {}".format(target_name))

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

    samples = []
    with page.PageClient.connect(target["webSocketDebuggerUrl"]) as client:
        if not client.evaluate(
                "Boolean(document.querySelector('.sell-component-image-v2-media-popup'))"):
            page.open_media_popup(client)
            time.sleep(3)
        context_id = page.media_iframe_context(client)
        js = state_js(target_name)

        before = client.evaluate(js, context_id=context_id)
        print()
        print("上传前：{}".format(json.dumps(before, ensure_ascii=False)))

        print()
        print("── 1) 只设 file input，**不点完成**，观察 {} 秒 ──".format(8))
        page.click_media_entry(client, page.MEDIA_LOCAL_UPLOAD_TEXT,
                               context_id=context_id, wait=2)
        probe = client.evaluate(page.build_read_media_file_input_expression(),
                                context_id=context_id)
        print("  file input 数: {}".format((probe or {}).get("count")))
        client.set_file_input_files([str(source)], page.MEDIA_FILE_INPUT, context_id=context_id)

        for second in range(4):
            time.sleep(2)
            snap = client.evaluate(js, context_id=context_id)
            samples.append({"phase": "queued", "t": (second + 1) * 2, "state": snap})
            print("  t={:>2}s 面板项={} 卡片={} 目标={!r} 状态={}".format(
                (second + 1) * 2, snap.get("panelItems"), snap.get("cardCount"),
                snap.get("dir"), snap.get("panelStates")))

        print()
        print("── 2) 点「完成」，再观察 {} 秒 ──".format(args.watch))
        try:
            finish = page.click_media_finish(client, context_id=context_id, wait=2.0)
            print("  finish -> {}".format(json.dumps(finish, ensure_ascii=False)))
        except Exception as exc:  # noqa: BLE001
            print("  点完成失败：{}".format(exc))
            finish = {"ok": False, "error": str(exc)}

        for second in range(args.watch // 2):
            time.sleep(2)
            snap = client.evaluate(js, context_id=context_id)
            samples.append({"phase": "after_finish", "t": (second + 1) * 2, "state": snap})
            print("  t={:>2}s 面板项={} 卡片={} 命中={} toast={} 错误页={}".format(
                (second + 1) * 2, snap.get("panelItems"), snap.get("cardCount"),
                snap.get("cardsMatching"), snap.get("toasts"), snap.get("bodyHasUploadError")))
            if snap.get("cardsMatching"):
                print("      ↑ **找到目标图了**")
                break

        final = client.evaluate(js, context_id=context_id)
        exists = page.media_image_exists(client, target_name, context_id=context_id)

    print()
    print("=" * 62)
    print("最终：")
    print("  卡片数 {}（上传前 {}）".format(final.get("cardCount"), before.get("cardCount")))
    print("  卡片里命中目标名: {}".format(final.get("cardsMatching")))
    print("  按 innerHTML 判定（已摘掉上传面板）: {}".format(exists))
    print("  → {}".format("**落库成功**" if exists else "**没有落库**"))

    TMP_DIR.mkdir(parents=True, exist_ok=True)
    out = TMP_DIR / "upload-lifecycle-{}.json".format(datetime.now().strftime("%Y%m%d%H%M%S"))
    out.write_text(json.dumps({
        "captured_at": datetime.now().isoformat(timespec="seconds"),
        "uploaded_one_file": True,
        "never_did": ["保存草稿", "提交宝贝信息"],
        "target_name": target_name,
        "before": before,
        "finish": finish,
        "final": final,
        "exists": exists,
        "samples": samples,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print()
    print("产物：{}".format(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

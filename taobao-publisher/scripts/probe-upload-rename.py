# -*- coding: utf-8 -*-
"""聚焦验证：带 `rename_to` 上传时，**平台上的文件名到底是哪个**。

背景：`upload_images` 现在给上传文件加商品级前缀
（``主图_01_1x1.jpg`` → ``ID-xxx_主图_01_1x1.jpg``），以避免两个商品的主图同名。
但实机跑下来，图片空间里的卡片仍然只有旧名字。

本脚本只做一件事：传**一个**文件（带改名），然后逐步打印
上传面板里的名字、空间卡片里的名字，判断改名有没有生效。

**会真的往店铺图片空间传一张图**，必须显式加 ``--allow-write``。

用法::

    python taobao-publisher/scripts/probe-upload-rename.py --address 127.0.0.1:9502 --allow-write
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

STATE_JS = r"""
(() => {
  const cards = Array.from(document.querySelectorAll('[class*="PicList_pic_background"]'));
  const texts = cards.map(el => (el.textContent || '').trim());
  const html = document.body ? document.body.innerHTML : '';
  return {
    panelItems: document.querySelectorAll('[class*="UploadPanel_fileItem"]').length,
    panelNames: Array.from(document.querySelectorAll('[class*="UploadPanel_fileName"]'))
      .map(e => (e.textContent || '').trim()).slice(0, 6),
    cardCount: cards.length,
    cardsWithId: texts.filter(t => t.includes('ID-')).slice(0, 5),
    cardsWith1x1: texts.filter(t => t.includes('_1x1')).slice(0, 5),
    htmlHasRenamed: html.includes('ID-1083867541795_'),
  };
})()
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--address", default="127.0.0.1:9502")
    parser.add_argument("--allow-write", action="store_true")
    parser.add_argument("--source", default=None)
    parser.add_argument("--target-name", default="ID-1083867541795_改名验证.jpg")
    args = parser.parse_args()

    if not args.allow_write:
        print("这会真的往店铺图片空间传一张图，必须显式加 --allow-write。")
        return 2

    source = args.source
    if not source:
        base = Path(os.environ["LOCALAPPDATA"]) / "com.dyin.sock-publisher" / "uploads" / "products"
        product_dirs = [d for d in base.iterdir() if d.is_dir()]
        main_dir = product_dirs[0] / "主图"
        candidates = sorted(p for p in main_dir.iterdir() if p.name.endswith("_1x1.jpg"))
        source = str(candidates[0])
    print("源文件: {}".format(source))
    print("目标名: {}".format(args.target_name))

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
        if not client.evaluate(
                "Boolean(document.querySelector('.sell-component-image-v2-media-popup'))"):
            page.open_media_popup(client)
            time.sleep(3)
        context_id = page.media_iframe_context(client)

        before = client.evaluate(STATE_JS, context_id=context_id)
        print()
        print("上传前：{}".format(json.dumps(before, ensure_ascii=False)))
        steps.append({"step": "before", "state": before})

        print()
        print("── 带改名上传 ──")
        result = page.upload_files_to_media(
            client, [source], context_id=context_id, rename_to=[args.target_name])
        print("  ok={} confirmed={} failed={}".format(
            result.get("ok"), result.get("confirmed"), result.get("failed")))
        print("  attempts={}".format(json.dumps(result.get("attempts"), ensure_ascii=False)[:260]))
        print("  finish={}".format(json.dumps(result.get("finish"), ensure_ascii=False)[:160]))
        steps.append({"step": "upload", "result": {
            k: v for k, v in result.items() if k != "attempts"}})

        time.sleep(3)
        after = client.evaluate(STATE_JS, context_id=context_id)
        print()
        print("上传后：{}".format(json.dumps(after, ensure_ascii=False, indent=1)))
        steps.append({"step": "after", "state": after})

    print()
    print("==== 结论 ====")
    print("  上传面板里的名字: {}".format(after.get("panelNames") or "（空）"))
    print("  空间卡片里的 ID 名: {}".format(after.get("cardsWithId") or "（无）"))
    print("  innerHTML 含改名后的名字: {}".format(after.get("htmlHasRenamed")))

    TMP_DIR.mkdir(parents=True, exist_ok=True)
    out = TMP_DIR / "upload-rename-{}.json".format(datetime.now().strftime("%Y%m%d%H%M%S"))
    out.write_text(json.dumps({
        "captured_at": datetime.now().isoformat(timespec="seconds"),
        "uploaded_one_file": True,
        "never_did": ["保存草稿", "提交宝贝信息"],
        "steps": steps,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print()
    print("产物：{}".format(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

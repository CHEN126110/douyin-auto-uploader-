# -*- coding: utf-8 -*-
"""实机复核第 34 轮修的「平台拒绝了却报成功」。

第 34 轮发现：平台把文件放进**上传队列**时 `innerHTML` 里就有名字了，
于是「进了队列」被当成了「进了空间」——**平台拒绝也报 `arrived: true`**。
修法是点「完成」**之前先读队列状态**，有失败项就原样带出平台给的原因。

当时把它标注为「需要实机复核」，但随后平台开始限流（要求滑动验证码），
就一直没复核。

本脚本**只传一个文件**，走的是修好的 `upload_files_to_media`：

* 若限流仍在 → 应当报出平台的原文（「操作过于频繁，请滑动验证码之后，重新上传。」）
  —— 那就**正是要复核的行为**；
* 若限流已解 → 图会真的落库。

**会真的往店铺图片空间传一张图**，必须显式加 ``--allow-write``。

用法::

    python taobao-publisher/scripts/verify-upload-rejection-report.py --address 127.0.0.1:9502 --allow-write
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--address", default="127.0.0.1:9502")
    parser.add_argument("--allow-write", action="store_true")
    args = parser.parse_args()

    if not args.allow_write:
        print("这会真的往店铺图片空间传一张图，必须显式加 --allow-write。")
        return 2

    base = Path(os.environ["LOCALAPPDATA"]) / "com.dyin.sock-publisher" / "uploads" / "products"
    product_dirs = [d for d in base.iterdir() if d.is_dir()]
    main_dir = product_dirs[0] / "主图"
    source = sorted(p for p in main_dir.iterdir() if p.name.endswith("_1x1.jpg"))[0]

    stamp = datetime.now().strftime("%H%M%S")
    target_name = "ID-探针_{}_1x1.jpg".format(stamp)
    print("源文件: {}".format(source.name))
    print("上传名: {}".format(target_name))
    print()

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
            page.open_media_popup(client)
            time.sleep(3)
        context_id = page.media_iframe_context(client)

        print("── 走修好的 upload_files_to_media（会先读队列状态）──")
        result = page.upload_files_to_media(
            client, [str(source)], context_id=context_id, rename_to=[target_name])

        print()
        print("  ok                  = {}".format(result.get("ok")))
        print("  rejectedByPlatform  = {}".format(result.get("rejectedByPlatform")))
        print("  confirmed           = {}".format(result.get("confirmed")))
        print("  failed              = {}".format(result.get("failed")))
        if result.get("reason"):
            print("  平台给的原因          = {}".format(result.get("reason")))
        queue = result.get("queue") or {}
        if queue.get("items"):
            print("  队列明细：")
            for item in queue["items"]:
                print("     {:<32} state={:<8} desc={}".format(
                    item.get("name", "")[:30], item.get("state"), item.get("desc", "")[:60]))

    print()
    print("=" * 68)
    if result.get("rejectedByPlatform"):
        print("结论：**平台拒绝了，而且如实报了出来** —— 第 34 轮的修复在实机上生效。")
        print("      平台原文：{}".format(result.get("reason")))
        print()
        print("      ⚠️ 这是风控 / 验证码，属**人工处理**范畴。**不绕过**。")
        print("      请在浏览器里手动完成验证后再跑一次。")
        outcome = "rejected_reported"
    elif result.get("ok"):
        print("结论：**上传成功并落库** —— 限流已解除。")
        outcome = "succeeded"
    else:
        print("结论：上传没成功，且**不是**平台明确拒绝（看上面的明细）。")
        outcome = "failed_other"

    TMP_DIR.mkdir(parents=True, exist_ok=True)
    out = TMP_DIR / "upload-rejection-{}.json".format(stamp)
    out.write_text(json.dumps({
        "captured_at": datetime.now().isoformat(timespec="seconds"),
        "uploaded_one_file": True,
        "never_did": ["保存草稿", "提交宝贝信息"],
        "outcome": outcome,
        "result": {k: v for k, v in result.items() if k != "attempts"},
        "attempts": result.get("attempts"),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print()
    print("产物：{}".format(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

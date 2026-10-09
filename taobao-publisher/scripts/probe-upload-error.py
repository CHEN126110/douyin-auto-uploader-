# -*- coding: utf-8 -*-
"""抓上传失败的**具体原因**。

上一轮定位到：上传面板里的队列项状态是 ``next-icon-error``（E-123 那轮是
``next-icon-success``），而 ``click_media_finish`` 照样返回 ``ok``。
本脚本把那个队列项**整棵子树**dump 出来，找错误文案 / tooltip / title。

**会真的往店铺图片空间传一张图**（预期会被平台拒绝），必须显式加 ``--allow-write``。

用法::

    python taobao-publisher/scripts/probe-upload-error.py --address 127.0.0.1:9502 --allow-write
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

DUMP_JS = r"""
(() => {
  const items = Array.from(document.querySelectorAll('[class*="UploadPanel_fileItem"]'));
  const describe = (el) => ({
    tag: el.tagName.toLowerCase(),
    className: typeof el.className === 'string' ? el.className.slice(0, 90) : '',
    text: (el.textContent || '').trim().slice(0, 80),
    title: el.getAttribute ? (el.getAttribute('title') || '') : '',
    ariaLabel: el.getAttribute ? (el.getAttribute('aria-label') || '') : '',
    outer: (el.outerHTML || '').slice(0, 260),
  });

  const rows = items.map(item => {
    const kids = [];
    const walk = (el, depth) => {
      if (depth > 3) return;
      for (const kid of Array.from(el.children)) {
        kids.push({ depth, ...describe(kid) });
        walk(kid, depth + 1);
      }
    };
    walk(item, 0);
    return { item: describe(item), kids };
  });

  // 找 tooltip / popup 里的错误文案
  const errHints = Array.from(document.querySelectorAll('*'))
    .filter(el => el.children.length === 0 && el.textContent)
    .map(el => (el.textContent || '').trim())
    .filter(t => t && t.length < 90 &&
      /失败|错误|不支持|不符合|超过|过大|格式|尺寸|比例|重试/.test(t));

  return {
    itemCount: items.length,
    rows,
    errHints: Array.from(new Set(errHints)).slice(0, 12),
    fileInputCount: document.querySelectorAll('input[type="file"]').length,
  };
})()
"""


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
    print("源文件: {}（{} 字节）".format(source.name, source.stat().st_size))

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

        page.click_media_entry(client, page.MEDIA_LOCAL_UPLOAD_TEXT,
                               context_id=context_id, wait=2)
        client.set_file_input_files([str(source)], page.MEDIA_FILE_INPUT, context_id=context_id)

        print()
        print("等 8 秒让平台处理…")
        time.sleep(8)
        dump = client.evaluate(DUMP_JS, context_id=context_id)

    print()
    print("队列项数: {}".format(dump.get("itemCount")))
    print()
    for index, row in enumerate(dump.get("rows") or []):
        print("── 项 [{}] {} ──".format(index, row["item"]["className"][:70]))
        print("   text={!r}".format(row["item"]["text"][:60]))
        for kid in row["kids"]:
            extra = ""
            if kid.get("title"):
                extra += " title={!r}".format(kid["title"][:40])
            if kid.get("ariaLabel"):
                extra += " aria={!r}".format(kid["ariaLabel"][:30])
            print("   {}<{}> {:<44} {!r}{}".format(
                "  " * kid["depth"], kid["tag"], kid["className"][:42],
                kid["text"][:34], extra))

    print()
    print("==== 页面上的错误类文案 ====")
    for hint in (dump.get("errHints") or []):
        print("  {!r}".format(hint))

    TMP_DIR.mkdir(parents=True, exist_ok=True)
    out = TMP_DIR / "upload-error-{}.json".format(datetime.now().strftime("%Y%m%d%H%M%S"))
    out.write_text(json.dumps({
        "captured_at": datetime.now().isoformat(timespec="seconds"),
        "uploaded_one_file": True,
        "never_did": ["保存草稿", "提交宝贝信息"],
        "source": str(source),
        "dump": dump,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print()
    print("产物：{}".format(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

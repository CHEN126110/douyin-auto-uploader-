# -*- coding: utf-8 -*-
"""诊断：上传的图到底有没有进素材中心，还是只是**我的读取看不见**。

E-119：三次尝试（5 张一次 / 2 张一次 / 2 张逐个）都报「没进空间」，
而空间里始终 80 张、1x1 只有第一批的 01/02/03。

两种可能必须分清：
  A. 文件根本没上传成功；
  B. 上传成功了，但 `read_media_space_images` 读的是**虚拟化/分页后的可见窗口**，
     新图在窗口之外。

本脚本把 iframe 的 DOM 直接翻一遍，找 `04_1x1` 字样，并看文件输入的当前状态。
**纯只读。**

用法::

    python taobao-publisher/scripts/diagnose-media-upload.py --address 127.0.0.1:9502
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SUBPROJECT = SCRIPT_DIR.parent
if str(SUBPROJECT) not in sys.path:
    sys.path.insert(0, str(SUBPROJECT))

from taobao_publish import page  # noqa: E402

TMP_DIR = SUBPROJECT / "tmp"

PROBE_JS = r"""
(() => {
  const text = document.body ? document.body.innerText : '';
  const html = document.body ? document.body.innerHTML : '';

  // 1) 直接搜文件名
  const needles = ['04_1x1', '05_1x1', '01_1x1', '02_1x1', '03_1x1'];
  const textHits = {};
  const htmlHits = {};
  for (const n of needles) {
    textHits[n] = text.includes(n);
    htmlHits[n] = html.includes(n);
  }

  // 2) 图片元素与它们的 src/alt
  const imgs = Array.from(document.querySelectorAll('img'));
  const imgNames = imgs.map(i => ({
    alt: i.getAttribute('alt') || '',
    srcTail: String(i.src || '').split('/').pop().slice(0, 60),
  })).slice(0, 12);

  // 3) 分页 / 加载更多 / 滚动容器
  const PAGER = ['[class*="pag"]', '[class*="Pag"]', '[class*="loadMore"]',
                 '[class*="LoadMore"]', '[class*="scroll"]', '[class*="Scroll"]'];
  const pager = {};
  for (const sel of PAGER) pager[sel] = document.querySelectorAll(sel).length;

  // 4) 滚动容器的高度与滚动位置
  const scrollers = Array.from(document.querySelectorAll('div'))
    .filter(el => el.scrollHeight > el.clientHeight + 20 && el.clientHeight > 100)
    .slice(0, 5)
    .map(el => ({
      className: String(el.className).slice(0, 60),
      scrollHeight: el.scrollHeight,
      clientHeight: el.clientHeight,
      scrollTop: el.scrollTop,
    }));

  // 5) 文件输入的当前状态
  const fileInputs = Array.from(document.querySelectorAll('input[type="file"]')).map(i => ({
    files: i.files ? i.files.length : -1,
    names: i.files ? Array.from(i.files).map(f => f.name).slice(0, 5) : [],
  }));

  // 6) 上传相关的提示文案
  const hints = (text.match(/上传[^\n]{0,50}/g) || []).slice(0, 10);

  return {
    textHits, htmlHits,
    imgCount: imgs.length,
    imgNames,
    pager,
    scrollers,
    fileInputs,
    hints,
    textHead: text.replace(/\s+/g, ' ').slice(0, 260),
  };
})()
"""


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

    with page.PageClient.connect(target["webSocketDebuggerUrl"]) as client:
        popup = client.evaluate(
            "Boolean(document.querySelector('.sell-component-image-v2-media-popup'))")
        print("弹层开着：{}".format(popup))
        if not popup:
            print("弹层没开——先跑 scripts/probe-media-space-items.py 打开它")
            return 1
        context_id = page.media_iframe_context(client)
        print("素材中心上下文：{}".format(context_id))
        data = client.evaluate(PROBE_JS, context_id=context_id)
        listed = page.read_media_space_images(client, context_id=context_id)

    if not isinstance(data, dict):
        print("探测没返回可解析结果")
        return 1

    print()
    print("==== 文件名搜索 ====")
    print("  文本里: {}".format(json.dumps(data["textHits"], ensure_ascii=False)))
    print("  HTML里: {}".format(json.dumps(data["htmlHits"], ensure_ascii=False)))
    print()
    print("==== 图片元素 {} 个（前 12）====".format(data["imgCount"]))
    for item in data["imgNames"]:
        print("  alt={!r:<22} src尾={}".format(item["alt"][:20], item["srcTail"]))
    print()
    print("==== 分页/滚动相关类名计数 ====")
    print("  {}".format(json.dumps(data["pager"], ensure_ascii=False)))
    print()
    print("==== 可滚动容器 ====")
    for item in data["scrollers"]:
        print("  h={} client={} top={} class={}".format(
            item["scrollHeight"], item["clientHeight"], item["scrollTop"],
            item["className"]))
    print()
    print("==== file input 当前状态 ====")
    print("  {}".format(json.dumps(data["fileInputs"], ensure_ascii=False)))
    print()
    print("==== 上传相关提示 ====")
    print("  {}".format(json.dumps(data["hints"], ensure_ascii=False)))
    print()
    print("==== read_media_space_images 读到的 ====")
    print("  共 {} 个；1x1 的：{}".format(
        len(listed), sorted(n for n in listed if "1x1" in n)))
    print()
    print("==== 文本开头 ====")
    print("  {!r}".format(data["textHead"][:200]))

    TMP_DIR.mkdir(parents=True, exist_ok=True)
    out = TMP_DIR / "media-upload-diagnose-{}.json".format(datetime.now().strftime("%Y%m%d%H%M%S"))
    out.write_text(json.dumps({
        "captured_at": datetime.now().isoformat(timespec="seconds"),
        "clicked_nothing": True,
        "probe": data,
        "listed": listed,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print()
    print("产物：{}".format(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

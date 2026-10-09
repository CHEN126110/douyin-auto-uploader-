# -*- coding: utf-8 -*-
"""诊断：`主图_01_1x1.jpg` 这个名字**到底在哪个元素里**。

E-120：`media_image_exists` 说它在（`innerHTML.includes` 为真），
但遍历 `[class*="PicList_pic_background"]` 卡片时**没有一张**包含它，
滚动 18 次也不变（cardCount 恒为 144）。

所以要么它不在卡片里（在文件夹名 / 面包屑 / 隐藏模板里），
要么卡片文本的渲染形态和我以为的不一样。

本脚本把包含该名字的**所有元素**连同祖先链 dump 出来。**纯只读。**

用法::

    python taobao-publisher/scripts/diagnose-media-name-location.py --address 127.0.0.1:9502 --name 主图_01_1x1.jpg
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

LOCATE_JS = r"""
(() => {
  const NAME = __NAME__;
  const hits = [];
  for (const el of Array.from(document.querySelectorAll('*'))) {
    const own = Array.from(el.childNodes)
      .filter(n => n.nodeType === 3)
      .map(n => n.textContent || '')
      .join('');
    const inOwnText = own.includes(NAME);
    const inAttrs = ['title', 'alt', 'data-name', 'aria-label']
      .some(a => (el.getAttribute && (el.getAttribute(a) || '')).includes(NAME));
    const inSrc = String(el.src || '').includes(NAME) ||
                  String(el.getAttribute && el.getAttribute('src') || '').includes(NAME);
    if (!inOwnText && !inAttrs && !inSrc) continue;

    const chain = [];
    let n = el;
    for (let i = 0; i < 6 && n; i++) {
      const c = typeof n.className === 'string'
        ? n.className.trim().split(/\s+/).slice(0, 2).join('.') : '';
      chain.push(n.tagName.toLowerCase() + (c ? '.' + c : ''));
      n = n.parentElement;
    }
    hits.push({
      tag: el.tagName.toLowerCase(),
      className: typeof el.className === 'string' ? el.className.slice(0, 100) : '',
      ownText: own.slice(0, 60),
      title: el.getAttribute && (el.getAttribute('title') || ''),
      alt: el.getAttribute && (el.getAttribute('alt') || ''),
      src: String(el.src || '').slice(0, 90),
      chain: chain.join(' < '),
      inOwnText, inAttrs, inSrc,
    });
    if (hits.length >= 12) break;
  }

  // 顺带看看候选卡片里到底显示的是什么
  const CARD = '[class*="PicList_pic_background"]';
  const cards = Array.from(document.querySelectorAll(CARD));
  return {
    hitCount: hits.length,
    hits,
    cardCount: cards.length,
    cardSamples: cards.slice(0, 5).map(el => ({
      text: (el.textContent || '').trim().slice(0, 50),
      html: el.innerHTML.slice(0, 200),
    })),
  };
})()
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--address", default="127.0.0.1:9502")
    parser.add_argument("--name", default="主图_01_1x1.jpg")
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
        if not client.evaluate(
                "Boolean(document.querySelector('.sell-component-image-v2-media-popup'))"):
            print("弹层没开——先打开它")
            return 1
        context_id = page.media_iframe_context(client)
        data = client.evaluate(
            LOCATE_JS.replace("__NAME__", json.dumps(args.name, ensure_ascii=False)),
            context_id=context_id)

    if not isinstance(data, dict):
        print("探测没返回可解析结果")
        return 1

    print("目标文件名：{}".format(args.name))
    print("包含它的元素：{} 个".format(data["hitCount"]))
    print()
    for item in data["hits"]:
        flags = []
        if item["inOwnText"]:
            flags.append("自身文本")
        if item["inAttrs"]:
            flags.append("属性")
        if item["inSrc"]:
            flags.append("src")
        print("  <{}> {:<50} [{}]".format(item["tag"], item["className"][:48], "/".join(flags)))
        print("      ownText={!r}".format(item["ownText"][:50]))
        if item["title"]:
            print("      title={!r}".format(item["title"][:50]))
        if item["alt"]:
            print("      alt={!r}".format(item["alt"][:50]))
        if item["src"]:
            print("      src={}".format(item["src"][:70]))
        print("      chain={}".format(item["chain"][:110]))
    print()
    print("==== 卡片数 {}，前 5 张的文本与 HTML ====".format(data["cardCount"]))
    for index, card in enumerate(data["cardSamples"]):
        print("  [{}] text={!r}".format(index, card["text"][:40]))
        print("      html={}".format(card["html"][:150]))

    TMP_DIR.mkdir(parents=True, exist_ok=True)
    out = TMP_DIR / "media-name-location-{}.json".format(datetime.now().strftime("%Y%m%d%H%M%S"))
    out.write_text(json.dumps({
        "captured_at": datetime.now().isoformat(timespec="seconds"),
        "clicked_nothing": True,
        "name": args.name,
        **data,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print()
    print("产物：{}".format(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

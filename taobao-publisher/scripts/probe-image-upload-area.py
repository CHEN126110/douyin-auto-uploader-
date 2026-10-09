# -*- coding: utf-8 -*-
"""勘察：填写页的图片上传控件结构。

`upload_images` 是最后一个未实现阶段。它的技术点与前几个不同：
需要往 ``<input type="file">`` 塞文件，走 CDP 的 **``DOM.setFileInputFiles``**，
绕开原生文件选择框。

本脚本**只读**：列出页面上所有 ``input[type=file]`` 与图片区容器结构，
**不设置任何文件、不触发任何上传**。

用法::

    python taobao-publisher/scripts/probe-image-upload-area.py --address 127.0.0.1:9502
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

#: 找所有 file input，并给出它们的祖先链，便于判断属于哪个区块。
FILES_JS = r"""
(() => {
  const chain = (el, depth) => {
    const parts = [];
    let node = el;
    for (let i = 0; i < depth && node; i++) {
      const cls = typeof node.className === 'string'
        ? node.className.trim().split(/\s+/).slice(0, 2).join('.') : '';
      parts.push(node.tagName.toLowerCase() + (cls ? '.' + cls : ''));
      node = node.parentElement;
    }
    return parts.join(' < ');
  };

  const inputs = Array.from(document.querySelectorAll('input[type="file"]')).map((el, i) => {
    const r = el.getBoundingClientRect();
    return {
      index: i,
      accept: el.getAttribute('accept') || '',
      multiple: el.multiple === true,
      name: el.getAttribute('name') || '',
      className: typeof el.className === 'string' ? el.className.slice(0, 70) : '',
      hidden: el.hidden === true,
      display: getComputedStyle(el).display,
      size: Math.round(r.width) + 'x' + Math.round(r.height),
      chain: chain(el, 6),
    };
  });

  return { count: inputs.length, inputs };
})()
"""

#: 图片区容器：按已知的淘宝类名找。
AREAS_JS = r"""
(() => {
  const PATTERNS = ['sell-component-info-wrapper-wrap', 'pic', 'image', 'upload'];
  const out = [];
  for (const el of Array.from(document.querySelectorAll('div'))) {
    const cls = typeof el.className === 'string' ? el.className : '';
    if (!cls) continue;
    if (!PATTERNS.some(p => cls.includes(p))) continue;
    const r = el.getBoundingClientRect();
    if (r.height === 0) continue;
    // 只看「含有 file input」或「本身就是上传区」的元素
    const hasFile = el.querySelector('input[type="file"]') !== null;
    const ownText = (el.textContent || '').trim();
    if (!hasFile && !/上传|主图|图片/.test(ownText.slice(0, 40))) continue;
    out.push({
      className: cls.slice(0, 100),
      size: Math.round(r.width) + 'x' + Math.round(r.height),
      hasFileInput: hasFile,
      fileInputs: el.querySelectorAll('input[type="file"]').length,
      text: ownText.slice(0, 90),
      chainDepth: (() => { let n = el, d = 0; while (n.parentElement && d < 20) { n = n.parentElement; d++; } return d; })(),
    });
  }
  // 去重（同一个元素可能被多个 pattern 命中）
  const seen = new Set();
  return out.filter(o => {
    const key = o.className + '|' + o.size;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  }).slice(0, 20);
})()
"""

#: 主图区附近的按钮与文案（判断上传入口的形态）。
NEARBY_JS = r"""
(() => {
  const labels = ['主图', '1:1主图', '3:4主图', '宝贝主图', '上传图片', '本地上传', '图片空间'];
  const hits = {};
  const body = document.body ? (document.body.innerText || '') : '';
  for (const l of labels) hits[l] = body.includes(l);
  const buttons = Array.from(document.querySelectorAll('button'))
    .filter(b => b.getBoundingClientRect().height > 0)
    .map(b => (b.textContent || '').trim())
    .filter(t => t && /上传|图片|主图|裁剪|空间/.test(t));
  return { labelHits: hits, imageButtons: [...new Set(buttons)].slice(0, 14) };
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
        print("页面：{}".format(str(client.evaluate("location.href.split('?')[0]"))[:90]))
        files = client.evaluate(FILES_JS)
        areas = client.evaluate(AREAS_JS)
        nearby = client.evaluate(NEARBY_JS)

    print()
    print("==== input[type=file]：{} 个 ====".format((files or {}).get("count")))
    for item in (files or {}).get("inputs", []):
        print("  [{}] accept={!r} multiple={} size={} display={} hidden={}".format(
            item["index"], item["accept"][:40], item["multiple"], item["size"],
            item["display"], item["hidden"]))
        print("      chain={}".format(item["chain"][:120]))

    print()
    print("==== 可能的图片区容器 ====")
    for item in (areas or [])[:12]:
        mark = "**有 file input**" if item["hasFileInput"] else ""
        print("  {} {}x{} {}".format(item["className"][:70], item["size"].split("x")[0],
                                      item["size"].split("x")[1], mark))
        print("      text={!r}".format(item["text"][:70]))

    print()
    print("==== 页面文案与按钮 ====")
    print("  关键词：{}".format(json.dumps((nearby or {}).get("labelHits"), ensure_ascii=False)))
    print("  图片相关按钮：{}".format(
        json.dumps((nearby or {}).get("imageButtons"), ensure_ascii=False)))

    TMP_DIR.mkdir(parents=True, exist_ok=True)
    out = TMP_DIR / "image-upload-area-{}.json".format(datetime.now().strftime("%Y%m%d%H%M%S"))
    out.write_text(json.dumps({
        "captured_at": datetime.now().isoformat(timespec="seconds"),
        "set_no_files": True,
        "triggered_no_upload": True,
        "files": files,
        "areas": areas,
        "nearby": nearby,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print()
    print("产物：{}".format(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

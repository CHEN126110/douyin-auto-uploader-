# -*- coding: utf-8 -*-
"""勘察：素材中心 iframe 里点「本地上传」，看文件输入怎么出现。

E-103：素材中心（``sucai-selector-ng``）里有三个入口
``本地上传 / 图片空间 / 生意管家``。本地上传大概率会创建 file input 并弹原生框。

开着 ``Page.setInterceptFileChooserDialog``，所以原生框不会真弹出来。
**本脚本不设置任何文件**（因此不会上传任何东西）。

用法::

    python taobao-publisher/scripts/probe-media-local-upload.py --address 127.0.0.1:9502
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

TMP_DIR = SUBPROJECT / "tmp"

OPEN_JS = r"""
(() => {
  const pop = document.querySelector('.sell-component-image-v2-media-popup');
  if (pop) return { ok: true, already: true };
  const area = Array.from(document.querySelectorAll('.sell-component-info-wrapper-wrap'))
    .find(el => (el.textContent || '').includes('1:1主图'));
  if (!area) return { ok: false, reason: 'no_1to1_area' };
  const slot = area.querySelector('.image-empty, .upload-text');
  if (!slot) return { ok: false, reason: 'no_slot' };
  slot.click();
  return { ok: true, already: false };
})()
"""

CLICK_LOCAL_JS = r"""
(() => {
  const els = Array.from(document.querySelectorAll('button, [role="button"], .next-btn, div, span'))
    .filter(e => (e.textContent || '').trim() === '本地上传'
                 && e.getBoundingClientRect().height > 0);
  if (!els.length) return { ok: false, reason: 'not_found' };
  // 取最内层的那个（最贴近真实可点元素）
  const target = els[els.length - 1];
  const before = document.querySelectorAll('input[type="file"]').length;
  target.click();
  return { ok: true, tag: target.tagName.toLowerCase(),
           className: String(target.className).slice(0, 70),
           fileInputsBefore: before };
})()
"""

FILES_JS = r"""
(() => {
  const inputs = Array.from(document.querySelectorAll('input[type="file"]'));
  return {
    count: inputs.length,
    inputs: inputs.map(el => ({
      accept: el.getAttribute('accept') || '',
      multiple: el.multiple === true,
      className: typeof el.className === 'string' ? el.className.slice(0, 70) : '',
      display: getComputedStyle(el).display,
      connected: el.isConnected,
      size: Math.round(el.getBoundingClientRect().width) + 'x' +
            Math.round(el.getBoundingClientRect().height),
    })),
  };
})()
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--address", default="127.0.0.1:9502")
    parser.add_argument("--wait", type=float, default=3.0)
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

    import websocket

    ws = websocket.create_connection(target["webSocketDebuggerUrl"], timeout=15, suppress_origin=True)
    ws.settimeout(2)
    counter = [0]
    contexts: list = []
    chooser = [None]
    events: list = []

    def send(method, params=None):
        counter[0] += 1
        ws.send(json.dumps({"id": counter[0], "method": method, "params": params or {}}))
        return counter[0]

    def pump(message_id, timeout=15.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                message = json.loads(ws.recv())
            except Exception:
                continue
            method = message.get("method")
            if method == "Runtime.executionContextCreated":
                contexts.append((message.get("params") or {}).get("context") or {})
                continue
            if method == "Page.fileChooserOpened":
                chooser[0] = message.get("params")
                events.append(method)
                continue
            if method:
                events.append(method)
                continue
            if message.get("id") == message_id:
                return message
        return {}

    def drain(seconds):
        deadline = time.time() + seconds
        while time.time() < deadline:
            try:
                message = json.loads(ws.recv())
            except Exception:
                continue
            method = message.get("method")
            if method == "Runtime.executionContextCreated":
                contexts.append((message.get("params") or {}).get("context") or {})
            elif method == "Page.fileChooserOpened":
                chooser[0] = message.get("params")
                events.append(method)
            elif method:
                events.append(method)

    pump(send("Runtime.enable"))
    pump(send("Page.enable"))
    pump(send("Page.setInterceptFileChooserDialog", {"enabled": True}))

    pumped = pump(send("Runtime.evaluate", {
        "expression": OPEN_JS, "returnByValue": True, "awaitPromise": True}))
    print("打开弹层：{}".format(json.dumps(
        (pumped.get("result") or {}).get("result", {}).get("value"), ensure_ascii=False)))
    drain(args.wait + 3)

    # 找素材中心的上下文
    pumped = pump(send("Page.getFrameTree"))
    frame_urls: dict = {}

    def collect(node):
        frame = (node or {}).get("frame") or {}
        if frame.get("id"):
            frame_urls[frame["id"]] = frame.get("url") or ""
        for child in (node or {}).get("childFrames") or []:
            collect(child)

    collect((pumped.get("result") or {}).get("frameTree"))
    ctx_id = None
    for ctx in contexts:
        fid = str((ctx.get("auxData") or {}).get("frameId") or "")
        if "sucai-selector" in frame_urls.get(fid, "") and (ctx.get("auxData") or {}).get("isDefault"):
            ctx_id = ctx.get("id")
    if ctx_id is None:
        print("没找到素材中心上下文")
        ws.close()
        return 1
    print("素材中心上下文 id = {}".format(ctx_id))

    pumped = pump(send("Runtime.evaluate", {
        "expression": FILES_JS, "returnByValue": True, "contextId": ctx_id}))
    before = (pumped.get("result") or {}).get("result", {}).get("value")
    print()
    print("点「本地上传」前，iframe 里 file input 数：{}".format((before or {}).get("count")))

    print()
    print("── 点「本地上传」 ──")
    pumped = pump(send("Runtime.evaluate", {
        "expression": CLICK_LOCAL_JS, "returnByValue": True, "contextId": ctx_id}))
    clicked = (pumped.get("result") or {}).get("result", {}).get("value")
    print("  {}".format(json.dumps(clicked, ensure_ascii=False)))

    drain(args.wait + 2)

    pumped = pump(send("Runtime.evaluate", {
        "expression": FILES_JS, "returnByValue": True, "contextId": ctx_id}))
    after = (pumped.get("result") or {}).get("result", {}).get("value")
    print()
    print("点后 iframe 里 file input 数：{}".format((after or {}).get("count")))
    for item in (after or {}).get("inputs", []):
        print("  accept={!r} multiple={} display={} size={} class={}".format(
            item["accept"][:50], item["multiple"], item["display"],
            item["size"], item["className"][:50]))

    print()
    if chooser[0]:
        print("==== 收到 Page.fileChooserOpened ====")
        print("  {}".format(json.dumps(chooser[0], ensure_ascii=False)))
    else:
        print("**没有**收到 Page.fileChooserOpened")

    # 关掉拦截
    send("Page.setInterceptFileChooserDialog", {"enabled": False})
    time.sleep(0.5)
    ws.close()

    print()
    print("事件：{}".format(json.dumps(events[-8:], ensure_ascii=False)))

    TMP_DIR.mkdir(parents=True, exist_ok=True)
    out = TMP_DIR / "media-local-upload-{}.json".format(datetime.now().strftime("%Y%m%d%H%M%S"))
    out.write_text(json.dumps({
        "captured_at": datetime.now().isoformat(timespec="seconds"),
        "set_no_files": True,
        "uploaded_nothing": True,
        "context_id": ctx_id,
        "clicked": clicked,
        "files_before": before,
        "files_after": after,
        "file_chooser_opened": chooser[0],
        "events": events[-12:],
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print("产物：{}".format(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

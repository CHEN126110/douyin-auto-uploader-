# -*- coding: utf-8 -*-
"""勘察：进入素材中心 iframe，找上传入口。

E-102：图片选择器是 iframe
``https://market.m.taobao.com/app/crs-qn/sucai-selector-ng/index?type=pic&...``
（外面套在 ``.sell-component-image-v2-media-popup`` 里）。
所以上传要在**那个 frame 的执行上下文**里做。

本脚本用 ``Runtime.evaluate`` 带 ``contextId`` 进 iframe，找：
有无 ``input[type=file]``、上传按钮叫什么、页面结构如何。

**只读**：不选图、不上传、不点任何提交按钮。

用法::

    python taobao-publisher/scripts/probe-media-iframe.py --address 127.0.0.1:9502
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

#: 在目标 frame 里跑的探测表达。
IFRAME_PROBE_JS = r"""
(() => {
  const files = Array.from(document.querySelectorAll('input[type="file"]')).map(el => ({
    accept: el.getAttribute('accept') || '',
    multiple: el.multiple === true,
    className: typeof el.className === 'string' ? el.className.slice(0, 60) : '',
    hidden: el.hidden === true,
    display: getComputedStyle(el).display,
  }));
  const buttons = Array.from(document.querySelectorAll('button, [role="button"], .next-btn'))
    .filter(b => b.getBoundingClientRect().height > 0)
    .map(b => (b.textContent || '').trim())
    .filter(t => t && t.length <= 16);
  const tabs = Array.from(document.querySelectorAll('.next-tabs-tab-inner, [class*="tab-item"]'))
    .map(el => (el.textContent || '').trim()).filter(t => t && t.length <= 14);
  return {
    href: location.href.slice(0, 110),
    title: document.title,
    fileInputs: files,
    buttons: [...new Set(buttons)].slice(0, 18),
    tabs: [...new Set(tabs)].slice(0, 12),
    text: (document.body ? document.body.innerText : '').replace(/\s+/g, ' ').trim().slice(0, 300),
  };
})()
"""

CLOSE_JS = r"""
(() => {
  const pop = document.querySelector('.sell-component-image-v2-media-popup');
  if (!pop) return 'no_popup';
  document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', keyCode: 27, bubbles: true }));
  return 'escape';
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
            if message.get("method") == "Runtime.executionContextCreated":
                contexts.append((message.get("params") or {}).get("context") or {})
                continue
            if message.get("id") == message_id:
                return message
        return {}

    pump(send("Runtime.enable"))
    pump(send("Page.enable"))

    pumped = pump(send("Runtime.evaluate", {
        "expression": OPEN_JS, "returnByValue": True, "awaitPromise": True}))
    opened = (pumped.get("result") or {}).get("result", {}).get("value")
    print("打开弹层：{}".format(json.dumps(opened, ensure_ascii=False)))
    time.sleep(args.wait + 2)

    # 再收一轮上下文（iframe 加载后会新建）
    deadline = time.time() + 4
    while time.time() < deadline:
        try:
            message = json.loads(ws.recv())
        except Exception:
            continue
        if message.get("method") == "Runtime.executionContextCreated":
            contexts.append((message.get("params") or {}).get("context") or {})

    print()
    print("==== 执行上下文 {} 个 ====".format(len(contexts)))
    # ⚠️ **必须按 frame URL 匹配**，不能按 origin：同一个 origin（market.m.taobao.com）
    # 下有多个 iframe（详情预览、素材中心…），按 origin 挑会挑到详情预览那个。
    pumped = pump(send("Page.getFrameTree"))
    frame_urls: dict = {}

    def collect(node):
        frame = (node or {}).get("frame") or {}
        if frame.get("id"):
            frame_urls[frame["id"]] = frame.get("url") or ""
        for child in (node or {}).get("childFrames") or []:
            collect(child)

    collect((pumped.get("result") or {}).get("frameTree"))

    target_ctx = None
    for ctx in contexts:
        frame_id = str((ctx.get("auxData") or {}).get("frameId") or "")
        url = frame_urls.get(frame_id, "")
        mark = "← 素材中心" if "sucai-selector" in url else ""
        print("  id={:<4} default={:<6} {:<58} {}".format(
            ctx.get("id"), (ctx.get("auxData") or {}).get("isDefault"),
            (url or str(ctx.get("origin") or ""))[:56], mark))
        if "sucai-selector" in url and (ctx.get("auxData") or {}).get("isDefault"):
            if target_ctx is None:
                target_ctx = ctx

    if target_ctx is None:
        print()
        print("**没有找到 sucai-selector 的执行上下文**；已见 frame：")
        for fid, url in frame_urls.items():
            print("    {}  {}".format(fid[:12], url[:100]))

    result = None
    if target_ctx is not None:
        print()
        print("── 在上下文 {} 里探测 ──".format(target_ctx.get("id")))
        pumped = pump(send("Runtime.evaluate", {
            "expression": IFRAME_PROBE_JS,
            "returnByValue": True,
            "contextId": target_ctx.get("id"),
        }))
        result = (pumped.get("result") or {}).get("result", {}).get("value")
        if result is None:
            print("  返回空，可能 frame 还没加载完")
            print("  raw: {}".format(json.dumps(pumped, ensure_ascii=False)[:300]))
    else:
        print()
        print("**没有找到素材中心的执行上下文**")

    pump(send("Runtime.evaluate", {"expression": CLOSE_JS, "returnByValue": True}))
    ws.close()

    if isinstance(result, dict):
        print()
        print("  href      : {}".format(result.get("href")))
        print("  title     : {}".format(result.get("title")))
        print("  file input: {} 个".format(len(result.get("fileInputs") or [])))
        for item in result.get("fileInputs") or []:
            print("      accept={!r} multiple={} display={} hidden={} class={}".format(
                item["accept"][:40], item["multiple"], item["display"],
                item["hidden"], item["className"][:50]))
        print("  tabs      : {}".format(json.dumps(result.get("tabs"), ensure_ascii=False)))
        print("  buttons   : {}".format(json.dumps(result.get("buttons"), ensure_ascii=False)))
        print("  text      : {!r}".format((result.get("text") or "")[:220]))

    TMP_DIR.mkdir(parents=True, exist_ok=True)
    out = TMP_DIR / "media-iframe-{}.json".format(datetime.now().strftime("%Y%m%d%H%M%S"))
    out.write_text(json.dumps({
        "captured_at": datetime.now().isoformat(timespec="seconds"),
        "selected_nothing": True,
        "uploaded_nothing": True,
        "opened": opened,
        "contexts": [{"id": c.get("id"), "origin": c.get("origin"), "name": c.get("name")}
                     for c in contexts],
        "target_context_id": (target_ctx or {}).get("id"),
        "probe": result,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print()
    print("产物：{}".format(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

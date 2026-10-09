# -*- coding: utf-8 -*-
"""勘察：点击「上传图片」时，浏览器到底怎么打开文件选择框。

已实证（E-101）：页面上**没有**常驻的 ``input[type=file]``（实测 0 个），
所以不能直接对它调 ``DOM.setFileInputFiles``。上传入口是**按需创建** input 再弹原生框。

CDP 的对应做法是拦截文件选择框：

  1. ``Page.setInterceptFileChooserDialog`` 打开拦截；
  2. 点「上传图片」；
  3. 收 ``Page.fileChooserOpened`` 事件，拿到 ``backendNodeId``；
  4. 再对那个 node 调 ``DOM.setFileInputFiles``。

本脚本只做 1–3 步并报告结果，**不设置任何文件**（因此不会上传任何东西）。
开启拦截后原生对话框不会真的弹出来，所以这一步是安全的。

用法::

    python taobao-publisher/scripts/probe-file-chooser.py --address 127.0.0.1:9502
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

#: 点 1:1 主图区第一个「上传图片」。
CLICK_UPLOAD_JS = r"""
(() => {
  const AREAS = ['.sell-component-info-wrapper-wrap'];
  const area = Array.from(document.querySelectorAll(AREAS)).find(el => {
    const t = (el.textContent || '');
    return t.includes('1:1主图');
  });
  if (!area) return { ok: false, reason: 'no_1to1_area' };

  // image-empty 是空位；它的文本就是「上传图片」，点它最贴近人工操作
  const empty = area.querySelector('.image-empty, .upload-text');
  if (!empty) return { ok: false, reason: 'no_upload_slot' };

  const r = empty.getBoundingClientRect();
  if (r.width === 0 && r.height === 0) return { ok: false, reason: 'slot_not_visible' };

  // 记下点击前的 file input 数量，用于判断 input 是不是按需创建的
  const before = document.querySelectorAll('input[type="file"]').length;
  empty.click();
  return { ok: true, fileInputsBefore: before,
           clickedClass: String(empty.className).slice(0, 60),
           slotSize: Math.round(r.width) + 'x' + Math.round(r.height) };
})()
"""

#: 点击后立刻查有没有新出现的 file input（原生框会挂起渲染，但 DOM 可能已经建好）。
AFTER_JS = r"""
(() => {
  const inputs = Array.from(document.querySelectorAll('input[type="file"]'));
  return {
    fileInputCount: inputs.length,
    inputs: inputs.map((el, i) => ({
      index: i,
      accept: el.getAttribute('accept') || '',
      multiple: el.multiple === true,
      className: typeof el.className === 'string' ? el.className.slice(0, 60) : '',
      connected: el.isConnected,
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
    events: list = []

    def send(method, params=None):
        counter[0] += 1
        ws.send(json.dumps({"id": counter[0], "method": method, "params": params or {}}))
        return counter[0]

    def pump(message_id, timeout=15.0):
        """读到指定 id 的响应为止，沿途收集事件。"""
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                message = json.loads(ws.recv())
            except Exception:
                continue
            if "method" in message:
                events.append(message)
                continue
            if message.get("id") == message_id:
                return message
        return {}

    # 拦截原生文件选择框 —— 开启后它不会真的弹出来
    pumped = pump(send("Page.enable"))
    print("Page.enable: {}".format("ok" if "result" in pumped else pumped))
    pumped = pump(send("Page.setInterceptFileChooserDialog", {"enabled": True}))
    print("setInterceptFileChooserDialog: {}".format("ok" if "result" in pumped else pumped))

    pumped = pump(send("Runtime.evaluate", {
        "expression": AFTER_JS, "returnByValue": True}))
    before = (pumped.get("result") or {}).get("result", {}).get("value")
    print()
    print("点击前 file input 数：{}".format((before or {}).get("fileInputCount")))

    print()
    print("── 点 1:1 主图的「上传图片」 ──")
    pumped = pump(send("Runtime.evaluate", {
        "expression": CLICK_UPLOAD_JS, "returnByValue": True, "awaitPromise": True}))
    clicked = (pumped.get("result") or {}).get("result", {}).get("value")
    print("  {}".format(json.dumps(clicked, ensure_ascii=False)))

    # 等 fileChooserOpened 事件
    deadline = time.time() + args.wait + 5
    chooser = None
    while time.time() < deadline and chooser is None:
        try:
            message = json.loads(ws.recv())
        except Exception:
            continue
        if "method" in message:
            events.append(message)
            if message.get("method") == "Page.fileChooserOpened":
                chooser = message.get("params")
        # 顺便清空响应队列

    print()
    if chooser:
        print("==== 收到了 Page.fileChooserOpened ====")
        print("  {}".format(json.dumps(chooser, ensure_ascii=False)))
    else:
        print("**没有**收到 Page.fileChooserOpened")

    pumped = pump(send("Runtime.evaluate", {"expression": AFTER_JS, "returnByValue": True}))
    after = (pumped.get("result") or {}).get("result", {}).get("value")
    print()
    print("点击后 file input 数：{}".format((after or {}).get("fileInputCount")))
    for item in (after or {}).get("inputs", []):
        print("  [{}] accept={!r} multiple={} class={}".format(
            item["index"], item["accept"][:40], item["multiple"], item["className"][:50]))

    # 关掉拦截，避免影响后续人工操作
    send("Page.setInterceptFileChooserDialog", {"enabled": False})
    time.sleep(0.5)
    ws.close()

    event_names = [e.get("method") for e in events]
    print()
    print("收到的事件：{}".format(json.dumps(event_names[:12], ensure_ascii=False)))

    out_dir = TMP_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "file-chooser-{}.json".format(datetime.now().strftime("%Y%m%d%H%M%S"))
    out.write_text(json.dumps({
        "captured_at": datetime.now().isoformat(timespec="seconds"),
        "set_no_files": True,
        "uploaded_nothing": True,
        "clicked": clicked,
        "file_inputs_before": before,
        "file_inputs_after": after,
        "file_chooser_opened": chooser,
        "events": event_names,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print("产物：{}".format(out))
    return 0 if chooser else 1


if __name__ == "__main__":
    raise SystemExit(main())

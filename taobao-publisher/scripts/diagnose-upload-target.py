# -*- coding: utf-8 -*-
"""诊断：上传面板的「上传至」是什么，以及上传要怎样才能真正落库。

E-121：5 个文件都带 `next-icon-success` 成功图标、面板里也有「上传成功」，
但图片空间 144 张卡片里**一张都没有**它们。面板文案里出现「上传至」——
怀疑上传需要一个**目标选择**，不选就没有落点。

本脚本在上传面板展开的状态下，把**面板及其周边**整个 dump 出来：
「上传至」所在的容器、附近的输入/下拉/单选、以及所有可点元素。

**纯只读。**

用法::

    python taobao-publisher/scripts/diagnose-upload-target.py --address 127.0.0.1:9502
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

OPEN_PANEL_JS = r"""
(() => {
  // 面板已展开的话不再点（点一下是切换）
  const items = document.querySelectorAll('[class*="UploadPanel_fileItem"]');
  if (items.length) return { ok: true, already: true, items: items.length };
  const els = Array.from(document.querySelectorAll('button, [role="button"], .next-btn, span'))
    .filter(e => (e.textContent || '').trim() === '本地上传'
                 && e.getBoundingClientRect().height > 0);
  if (!els.length) return { ok: false, reason: 'no_entry' };
  els[els.length - 1].click();
  return { ok: true, already: false };
})()
"""

PROBE_JS = r"""
(() => {
  const visible = (el) => {
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  };

  // 1) 找含「上传至」的元素，往上找到它所在的容器
  const all = Array.from(document.querySelectorAll('*'));
  const targetEl = all.find(el => {
    if (!visible(el)) return false;
    for (const node of Array.from(el.childNodes)) {
      if (node.nodeType === 3 && (node.textContent || '').includes('上传至')) return true;
    }
    return false;
  });

  let container = null;
  const chain = [];
  if (targetEl) {
    let node = targetEl;
    for (let i = 0; i < 7 && node; i++) {
      const c = typeof node.className === 'string' ? node.className.trim().split(/\s+/)[0] : '';
      chain.push(node.tagName.toLowerCase() + (c ? '.' + c : ''));
      node = node.parentElement;
    }
    // 容器取「带 UploadPanel 的最外层祖先」
    container = targetEl;
    let up = targetEl.parentElement;
    for (let i = 0; i < 8 && up; i++) {
      const c = typeof up.className === 'string' ? up.className : '';
      if (c.includes('UploadPanel')) container = up;
      up = up.parentElement;
    }
  }

  // 2) 容器里的输入控件与可点元素
  const describe = (el) => ({
    tag: el.tagName.toLowerCase(),
    className: typeof el.className === 'string' ? el.className.slice(0, 90) : '',
    text: (el.textContent || '').trim().slice(0, 26),
    placeholder: el.getAttribute && (el.getAttribute('placeholder') || ''),
    role: el.getAttribute && (el.getAttribute('role') || ''),
    checked: el.checked === true || undefined,
    visible: visible(el),
  });

  const scope = container || document.body;
  const controls = Array.from(scope.querySelectorAll(
    'input, select, [role="combobox"], .next-select, .next-radio-wrapper, .next-checkbox-wrapper, button, .next-btn'))
    .map(describe).slice(0, 24);

  // 3) 整个 iframe 里「上传至」附近的文本
  const bodyText = document.body ? document.body.innerText.replace(/\s+/g, ' ') : '';
  const idx = bodyText.indexOf('上传至');
  const around = idx >= 0 ? bodyText.slice(Math.max(0, idx - 60), idx + 160) : '';

  // 4) 面板容器整体的结构（两层）
  const panel = document.querySelector('[class*="UploadPanel_uploadFileList"], [class*="UploadPanel"]');
  let panelChildren = [];
  if (panel) {
    panelChildren = Array.from(panel.children).slice(0, 12).map(el => ({
      tag: el.tagName.toLowerCase(),
      className: String(el.className).slice(0, 80),
      text: (el.textContent || '').trim().slice(0, 40),
      visible: visible(el),
    }));
  }

  return {
    foundTargetEl: Boolean(targetEl),
    targetChain: chain.join(' < '),
    containerClass: container ? String(container.className).slice(0, 110) : '',
    controls,
    textAroundUploadTo: around,
    panelClass: panel ? String(panel.className).slice(0, 100) : '',
    panelChildren,
    panelParentClass: panel && panel.parentElement
      ? String(panel.parentElement.className).slice(0, 110) : '',
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
        if not client.evaluate(
                "Boolean(document.querySelector('.sell-component-image-v2-media-popup'))"):
            print("弹层没开——先跑 probe-media-space-items.py 打开它")
            return 1
        context_id = page.media_iframe_context(client)
        opened = client.evaluate(OPEN_PANEL_JS, context_id=context_id)
        print("展开上传面板：{}".format(json.dumps(opened, ensure_ascii=False)))
        time.sleep(3)
        data = client.evaluate(PROBE_JS, context_id=context_id)

    if not isinstance(data, dict):
        print("探测没返回可解析结果")
        return 1

    print()
    print("找到「上传至」元素：{}".format(data["foundTargetEl"]))
    print("祖先链：{}".format(data["targetChain"][:140]))
    print("所在容器：{}".format(data["containerClass"][:100]))
    print()
    print("==== 「上传至」附近文本 ====")
    print("  {!r}".format(data["textAroundUploadTo"][:220]))
    print()
    print("==== 容器内控件 {} 个 ====".format(len(data["controls"])))
    for item in data["controls"]:
        extra = ""
        if item.get("placeholder"):
            extra += " ph={!r}".format(item["placeholder"][:18])
        if item.get("role"):
            extra += " role={}".format(item["role"])
        if item.get("checked") is not None:
            extra += " checked={}".format(item["checked"])
        print("  <{}> {!r:<24} vis={:<6}{}".format(
            item["tag"], item["text"][:24], item["visible"], extra))
        print("      class={}".format(item["className"][:84]))
    print()
    print("==== 面板 {} ====".format(data["panelClass"][:80]))
    print("  父层：{}".format(data["panelParentClass"][:90]))
    for item in data["panelChildren"]:
        print("  <{}> {:<44} vis={} {!r}".format(
            item["tag"], item["className"][:42], item["visible"], item["text"][:34]))

    TMP_DIR.mkdir(parents=True, exist_ok=True)
    out = TMP_DIR / "upload-target-{}.json".format(datetime.now().strftime("%Y%m%d%H%M%S"))
    out.write_text(json.dumps({
        "captured_at": datetime.now().isoformat(timespec="seconds"),
        "clicked_nothing_else": True,
        "opened": opened,
        **data,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print()
    print("产物：{}".format(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

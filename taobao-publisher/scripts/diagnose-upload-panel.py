# -*- coding: utf-8 -*-
"""诊断：上传面板里那个「上传」确认按钮在哪。

E-121：`主图_01_1x1.jpg` 等 5 个文件停在 ``UploadPanel_fileItem`` 队列里
（`uploadPanelItems: 9`），**没有进图片空间**。面板文案里有「上传至」，
说明还需要选目标并**点一个确认按钮**。

本脚本把上传面板的结构与按钮 dump 出来。**只读。**

用法::

    python taobao-publisher/scripts/diagnose-upload-panel.py --address 127.0.0.1:9502
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

PANEL_JS = r"""
(() => {
  // 上传面板容器：用文件名元素往上找
  const nameEl = document.querySelector('[class*="UploadPanel_fileName"]');
  if (!nameEl) return { found: false, reason: 'no_fileName' };

  let panel = nameEl;
  for (let i = 0; i < 8 && panel; i++) {
    const c = typeof panel.className === 'string' ? panel.className : '';
    if (c.includes('UploadPanel') && c.includes('upload')) break;
    panel = panel.parentElement;
  }
  if (!panel) {
    // 退一步：找最外层带 UploadPanel 的
    panel = Array.from(document.querySelectorAll('[class*="UploadPanel"]'))
      .filter(el => el.querySelector('[class*="fileName"]'))[0] || nameEl.parentElement;
  }

  const describe = (el) => ({
    tag: el.tagName.toLowerCase(),
    className: typeof el.className === 'string' ? el.className.slice(0, 90) : '',
    text: (el.textContent || '').trim().slice(0, 30),
    visible: el.getBoundingClientRect().height > 0,
    disabled: el.disabled === true,
  });

  const rows = [];
  const walk = (el, depth) => {
    if (depth > 4 || rows.length > 40) return;
    for (const kid of Array.from(el.children)) {
      rows.push({ depth, ...describe(kid) });
      walk(kid, depth + 1);
    }
  };
  walk(panel, 0);

  const buttons = Array.from(panel.querySelectorAll('button, [role="button"], .next-btn'))
    .map(describe).filter(b => b.text || b.className);

  // 整个 iframe 里找「上传」类按钮
  const allButtons = Array.from(document.querySelectorAll('button, [role="button"], .next-btn, span'))
    .filter(el => {
      const t = (el.textContent || '').trim();
      return el.getBoundingClientRect().height > 0 && t && t.length <= 8 &&
        ['上传', '确定', '确认', '开始上传', '上传至'].some(k => t.includes(k));
    })
    .map(describe).slice(0, 14);

  return {
    found: true,
    panelClass: String(panel.className).slice(0, 110),
    panelText: (panel.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 220),
    structure: rows,
    panelButtons: buttons,
    uploadishButtons: allButtons,
    fileItems: Array.from(document.querySelectorAll('[class*="UploadPanel_fileItem"]'))
      .map(el => (el.textContent || '').trim().slice(0, 40)).slice(0, 10),
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
            print("弹层没开——先打开它")
            return 1
        context_id = page.media_iframe_context(client)
        data = client.evaluate(PANEL_JS, context_id=context_id)

    if not isinstance(data, dict) or not data.get("found"):
        print("没找到上传面板：{}".format(json.dumps(data, ensure_ascii=False)[:200] if data else "无返回"))
        return 1

    print("面板 class：{}".format(data["panelClass"]))
    print("面板文本：{!r}".format(data["panelText"][:200]))
    print()
    print("==== 面板内按钮 {} 个 ====".format(len(data["panelButtons"])))
    for item in data["panelButtons"]:
        print("  <{}> {!r:<14} visible={:<6} disabled={:<6} class={}".format(
            item["tag"], item["text"][:14], item["visible"], item["disabled"],
            item["className"][:56]))
    print()
    print("==== iframe 里所有「上传/确定/确认」类按钮 ====")
    for item in data["uploadishButtons"]:
        print("  <{}> {!r:<14} visible={:<6} disabled={:<6} class={}".format(
            item["tag"], item["text"][:14], item["visible"], item["disabled"],
            item["className"][:56]))
    print()
    print("==== 面板结构（前 30）====")
    for row in data["structure"][:30]:
        print("  {:>2} {:<6} {:<44} vis={} {!r}".format(
            row["depth"], row["tag"], row["className"][:42], row["visible"], row["text"][:20]))
    print()
    print("==== 队列里的文件 {} 个 ====".format(len(data["fileItems"])))
    for name in data["fileItems"]:
        print("  {}".format(name))

    TMP_DIR.mkdir(parents=True, exist_ok=True)
    out = TMP_DIR / "upload-panel-{}.json".format(datetime.now().strftime("%Y%m%d%H%M%S"))
    out.write_text(json.dumps({
        "captured_at": datetime.now().isoformat(timespec="seconds"),
        "clicked_nothing": True,
        **data,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print()
    print("产物：{}".format(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# -*- coding: utf-8 -*-
"""勘察：规格抽屉里「规格值」输入区的结构。

`skus.sku_row` 是表格（要「确认创建」之后才有）；本脚本先解决**值怎么填**——
`.common-wrap` 里那个属性块怎么组织输入与候选项。**不点确认创建。**

用法::

    python taobao-publisher/scripts/probe-sku-value-area.py --address 127.0.0.1:9502
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

OPEN_JS = """
(() => {
  const btns = Array.from(document.querySelectorAll('button'))
    .filter(b => (b.textContent || '').trim() === '+ 创建规格');
  if (btns.length !== 1) return { ok: false, hitCount: btns.length };
  btns[0].click();
  return { ok: true };
})()
"""

VALUE_JS = r"""
(() => {
  const drawer = document.querySelector('.sku-decouple-drawer-container');
  if (!drawer) return { found: false };

  const wraps = Array.from(drawer.querySelectorAll('.common-wrap'));
  const blocks = wraps.map((w, i) => {
    const header = w.querySelector('.header, .front-group .header');
    const headerText = header ? (header.textContent || '').trim().slice(0, 40) : '';
    const inputs = Array.from(w.querySelectorAll('input,textarea,[role="combobox"]'))
      .map(el => ({
        tag: el.tagName.toLowerCase(),
        role: el.getAttribute('role') || '',
        placeholder: el.getAttribute('placeholder') || '',
        className: typeof el.className === 'string' ? el.className.slice(0, 70) : '',
        visible: el.getBoundingClientRect().height > 0,
      }));
    const buttons = Array.from(w.querySelectorAll('button'))
      .map(b => (b.textContent || '').trim()).filter(Boolean).slice(0, 8);
    // 候选项（标准属性会有现成的值列表）
    const chips = Array.from(w.querySelectorAll('.next-tag, [class*="tag"], [class*="item"], li'))
      .map(el => (el.textContent || '').trim())
      .filter(t => t && t.length <= 14)
      .slice(0, 14);
    return {
      index: i,
      className: typeof w.className === 'string' ? w.className.slice(0, 90) : '',
      headerText,
      inputs,
      buttons,
      chips: [...new Set(chips)],
      textStart: (w.textContent || '').trim().slice(0, 70),
    };
  });

  // 标准属性面板里可选的属性值（点属性名之后可能出现）
  const tags = Array.from(drawer.querySelectorAll('.next-tag, .next-tag-body'))
    .map(el => (el.textContent || '').trim()).filter(Boolean).slice(0, 20);

  return { found: true, blockCount: blocks.length, blocks, tags };
})()
"""

CLOSE_JS = """
(() => {
  const btns = Array.from(document.querySelectorAll('button'));
  const cancel = btns.find(b => ['取消', '关闭'].includes((b.textContent || '').trim()));
  if (cancel) { cancel.click(); return 'clicked_cancel'; }
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

    with page.PageClient.connect(target["webSocketDebuggerUrl"]) as client:
        opened = client.evaluate(OPEN_JS)
        if not isinstance(opened, dict) or not opened.get("ok"):
            print("打开抽屉失败")
            return 1
        time.sleep(args.wait)
        data = client.evaluate(VALUE_JS)
        closed = client.evaluate(CLOSE_JS)

    if not isinstance(data, dict) or not data.get("found"):
        print("没找到抽屉")
        return 1

    print("值区块数：{}".format(data["blockCount"]))
    print()
    for block in data["blocks"]:
        print("── block[{}] class={}".format(block["index"], block["className"][:70]))
        print("   header : {!r}".format(block["headerText"]))
        print("   buttons: {}".format(json.dumps(block["buttons"], ensure_ascii=False)))
        print("   text   : {!r}".format(block["textStart"][:60]))
        print("   chips  : {}".format(json.dumps(block["chips"][:12], ensure_ascii=False)))
        for item in block["inputs"]:
            print("     input <{}> role={:<10} ph={!r:<18} vis={} class={}".format(
                item["tag"], item["role"] or "-", item["placeholder"][:16],
                "Y" if item["visible"] else "N", item["className"][:50]))
        print()

    if data.get("tags"):
        print("抽屉里的 tag 元素：{}".format(json.dumps(data["tags"][:16], ensure_ascii=False)))
    print()
    print("关闭动作：{}".format(closed))

    TMP_DIR.mkdir(parents=True, exist_ok=True)
    out = TMP_DIR / "sku-value-area-{}.json".format(datetime.now().strftime("%Y%m%d%H%M%S"))
    out.write_text(json.dumps({
        "captured_at": datetime.now().isoformat(timespec="seconds"),
        "clicked_confirm": False,
        "close_action": closed,
        **data,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print()
    print("产物：{}".format(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# -*- coding: utf-8 -*-
"""诊断：规格抽屉当前到底什么状态。

上一轮：选了 ``L（45-47）`` 但计数仍是 1，点「确认创建」后表格也没出现。
需要分清是「抽屉还开着」还是「创建失败被回滚」还是「值没加进去」。

**纯只读**，不点任何按钮。

用法::

    python taobao-publisher/scripts/diagnose-sku-state.py --address 127.0.0.1:9502
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

STATE_JS = r"""
(() => {
  const drawer = document.querySelector('.sku-decouple-drawer-container');
  const wrapper = document.querySelector('.sell-sku-table-wrapper-new');

  const drawerState = drawer ? (() => {
    const blocks = Array.from(drawer.querySelectorAll('.common-wrap')).map(w => {
      const h = w.querySelector('.header');
      const text = h ? (h.textContent || '').trim() : '';
      const m = text.match(/\((\d+)\)/);
      // 已选中的值：色块/标签/li
      const chips = Array.from(w.querySelectorAll(
        '.next-tag, [class*="tag-body"], .sell-color-item-wrap, li [class*="item"]'))
        .map(el => (el.textContent || '').trim()).filter(t => t && t.length <= 20);
      const inputs = Array.from(w.querySelectorAll('input,[role="combobox"]'))
        .filter(el => el.getBoundingClientRect().height > 0)
        .map(el => ({ ph: el.getAttribute('placeholder') || '',
                      value: String(el.value || '').slice(0, 20),
                      cls: typeof el.className === 'string' ? el.className.slice(0, 50) : '' }));
      return { header: text.slice(0, 30), count: m ? Number(m[1]) : null,
               chips: [...new Set(chips)].slice(0, 8), inputs };
    });
    const footer = drawer.querySelector('.sku-decouple-drawer-footer');
    return {
      visible: drawer.getBoundingClientRect().height > 0,
      blocks,
      footerButtons: footer ? Array.from(footer.querySelectorAll('button')).map(b => ({
        text: (b.textContent || '').trim(),
        disabled: b.disabled === true,
      })) : [],
    };
  })() : null;

  return {
    href: location.href.split('?')[0],
    drawer: drawerState,
    skuWrapper: wrapper ? {
      className: String(wrapper.className).slice(0, 100),
      visible: wrapper.getBoundingClientRect().height > 0,
      tables: wrapper.querySelectorAll('table').length,
      text: (wrapper.textContent || '').trim().slice(0, 160),
    } : null,
    // 页面上有没有报错提示
    messages: Array.from(document.querySelectorAll('.next-message, .next-feedback, [class*="error"]'))
      .filter(el => el.getBoundingClientRect().height > 0)
      .map(el => (el.textContent || '').trim().slice(0, 100)).filter(Boolean).slice(0, 5),
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
        data = client.evaluate(STATE_JS)
        # 顺便看看现在还有没有可见弹层
        overlays = client.evaluate("""
(() => Array.from(document.querySelectorAll('.next-overlay-inner, .next-select-popup-wrap'))
  .filter(e => e.getBoundingClientRect().height > 0)
  .map(e => ({ className: String(e.className).slice(0, 90),
               h: Math.round(e.getBoundingClientRect().height) })))()
""")

    print("页面：{}".format((data or {}).get("href")))
    print()
    drawer = (data or {}).get("drawer")
    if drawer:
        print("抽屉可见：{}".format(drawer["visible"]))
        for block in drawer["blocks"]:
            print("  {!r}  count={}".format(block["header"], block["count"]))
            if block["chips"]:
                print("      chips={}".format(json.dumps(block["chips"], ensure_ascii=False)))
            for item in block["inputs"]:
                print("      input ph={!r} value={!r}".format(item["ph"], item["value"]))
        print("  底部按钮：")
        for item in drawer["footerButtons"]:
            print("      {!r} disabled={}".format(item["text"], item["disabled"]))
    else:
        print("抽屉不在 DOM 里")
    print()
    wrapper = (data or {}).get("skuWrapper")
    print("SKU 容器：{}".format(json.dumps(wrapper, ensure_ascii=False) if wrapper else "不存在"))
    print()
    print("可见弹层：{}".format(json.dumps(overlays, ensure_ascii=False)[:300]))
    print()
    print("页面提示：{}".format(json.dumps((data or {}).get("messages"), ensure_ascii=False)))

    TMP_DIR.mkdir(parents=True, exist_ok=True)
    out = TMP_DIR / "sku-state-{}.json".format(datetime.now().strftime("%Y%m%d%H%M%S"))
    out.write_text(json.dumps({
        "captured_at": datetime.now().isoformat(timespec="seconds"),
        "clicked_nothing": True,
        "state": data,
        "overlays": overlays,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print()
    print("产物：{}".format(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

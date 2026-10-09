# -*- coding: utf-8 -*-
"""实验：规格值到底在**哪一步**才算提交。

已知（E-089 / E-093）：点中候选有时提交（header 计数 +1），有时只把文本填进
输入框。假设是**陈旧弹层**——旧的 ``.next-select-popup-wrap`` 还在 DOM 里，
点到的是上一次渲染的节点，React 处理器作用在旧状态上。

本脚本按「一次只加一个值」做，每一步之后都读计数，把提交时机钉死：

  1. 点开值输入 → 等 → 记录弹层身份（位置/尺寸/候选数）
  2. 点中候选      → 读计数
  3. 若未提交：回车 → 读计数
  4. 若仍未提交：失焦 → 读计数

**只加值，不点「确认创建」。** 结束前重新打开抽屉确认计数。

用法::

    python taobao-publisher/scripts/experiment-sku-commit.py --address 127.0.0.1:9502 --allow-write
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

OPEN_DRAWER_JS = """
(() => {
  const btns = Array.from(document.querySelectorAll('button'))
    .filter(b => (b.textContent || '').trim() === '+ 创建规格');
  if (btns.length !== 1) return { ok: false, hitCount: btns.length };
  btns[0].click();
  return { ok: true };
})()
"""

#: 读计数 + 尺码块输入框的当前值。
COUNT_JS = r"""
(() => {
  const drawer = document.querySelector('.sku-decouple-drawer-container');
  if (!drawer) return { found: false };
  const block = Array.from(drawer.querySelectorAll('.common-wrap')).find(w => {
    const h = w.querySelector('.header');
    return h && (h.textContent || '').includes('尺码');
  });
  if (!block) return { found: false, reason: 'no_block' };
  const h = block.querySelector('.header');
  const text = h ? (h.textContent || '').trim() : '';
  const m = text.match(/\((\d+)\)/);
  const input = Array.from(block.querySelectorAll('input,[role="combobox"]')).find(el => {
    const r = el.getBoundingClientRect();
    if (r.height === 0) return false;
    const cls = typeof el.className === 'string' ? el.className : '';
    return !cls.includes('checkbox') && !cls.includes('radio');
  });
  return {
    found: true,
    header: text.slice(0, 30),
    count: m ? Number(m[1]) : null,
    inputValue: input ? String(input.value || '').slice(0, 24) : null,
    inputPlaceholder: input ? (input.getAttribute('placeholder') || '') : null,
  };
})()
"""

#: 点开值输入，并记录**点之前**弹层里已经有多少个弹层（用于判断陈旧弹层）。
OPEN_INPUT_JS = r"""
(() => {
  const drawer = document.querySelector('.sku-decouple-drawer-container');
  if (!drawer) return { ok: false, reason: 'no_drawer' };
  const block = Array.from(drawer.querySelectorAll('.common-wrap')).find(w => {
    const h = w.querySelector('.header');
    return h && (h.textContent || '').includes('尺码');
  });
  if (!block) return { ok: false, reason: 'no_block' };
  const inputs = Array.from(block.querySelectorAll('input,[role="combobox"]')).filter(el => {
    const r = el.getBoundingClientRect();
    if (r.height === 0) return false;
    const cls = typeof el.className === 'string' ? el.className : '';
    return !cls.includes('checkbox') && !cls.includes('radio');
  });
  if (!inputs.length) return { ok: false, reason: 'no_input' };

  // 先记录：点之前页面上已有几个 .next-select-popup-wrap
  const before = document.querySelectorAll('.next-select-popup-wrap').length;

  const el = inputs[0];
  el.click();
  el.focus();

  return { ok: true, popupsBeforeClick: before };
})()
"""

#: 记录弹层身份：位置 + 尺寸 + 候选数 + 是否是新增的。
POPUP_ID_JS = r"""
(() => {
  const pops = Array.from(document.querySelectorAll('.next-select-popup-wrap'))
    .filter(e => e.getBoundingClientRect().height > 0)
    .map(e => {
      const r = e.getBoundingClientRect();
      return {
        left: Math.round(r.left), top: Math.round(r.top),
        w: Math.round(r.width), h: Math.round(r.height),
        items: e.querySelectorAll('.options-item').length,
        connected: e.isConnected,
      };
    });
  return { popupCount: pops.length, popups: pops };
})()
"""

#: 在**最后一个**（最新的）可见弹层里点中候选，返回命中的位置信息。
PICK_LATEST_JS = r"""
(() => {
  const WANT = __WANT__;
  const pops = Array.from(document.querySelectorAll('.next-select-popup-wrap'))
    .filter(e => e.getBoundingClientRect().height > 0);
  if (!pops.length) return { ok: false, reason: 'no_popup' };
  // 用**最后一个**：最新渲染的那个
  const pop = pops[pops.length - 1];
  const options = Array.from(pop.querySelectorAll('.options-item')).map(el => {
    const t = el.querySelector('.info-content');
    return { el, text: t ? (t.textContent || '').trim() : '' };
  }).filter(o => o.text);
  const hits = options.filter(o => o.text === WANT);
  if (hits.length !== 1) {
    return { ok: false, reason: hits.length === 0 ? 'no_match' : 'ambiguous',
             hitCount: hits.length, popupCount: pops.length,
             shown: [...new Set(options.map(o => o.text))].slice(0, 20) };
  }
  const target = hits[0].el;
  const r = target.getBoundingClientRect();
  const info = { text: hits[0].text, w: Math.round(r.width), h: Math.round(r.height),
                 visible: r.width > 0 && r.height > 0, connected: target.isConnected };
  target.click();
  return { ok: true, popupCount: pops.length, picked: info };
})()
"""

PRESS_ENTER_JS = r"""
(() => {
  const drawer = document.querySelector('.sku-decouple-drawer-container');
  if (!drawer) return { ok: false };
  const block = Array.from(drawer.querySelectorAll('.common-wrap')).find(w => {
    const h = w.querySelector('.header');
    return h && (h.textContent || '').includes('尺码');
  });
  if (!block) return { ok: false, reason: 'no_block' };
  const input = Array.from(block.querySelectorAll('input,[role="combobox"]')).find(el => {
    const r = el.getBoundingClientRect();
    if (r.height === 0) return false;
    const cls = typeof el.className === 'string' ? el.className : '';
    return !cls.includes('checkbox') && !cls.includes('radio');
  });
  if (!input) return { ok: false, reason: 'no_input' };
  input.focus();
  for (const type of ['keydown', 'keypress', 'keyup']) {
    input.dispatchEvent(new KeyboardEvent(type, {
      key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true, cancelable: true,
    }));
  }
  return { ok: true };
})()
"""

BLUR_JS = r"""
(() => {
  const drawer = document.querySelector('.sku-decouple-drawer-container');
  if (!drawer) return { ok: false };
  const block = Array.from(drawer.querySelectorAll('.common-wrap')).find(w => {
    const h = w.querySelector('.header');
    return h && (h.textContent || '').includes('尺码');
  });
  if (!block) return { ok: false };
  const input = Array.from(block.querySelectorAll('input,[role="combobox"]')).find(el => {
    const r = el.getBoundingClientRect();
    if (r.height === 0) return false;
    const cls = typeof el.className === 'string' ? el.className : '';
    return !cls.includes('checkbox') && !cls.includes('radio');
  });
  if (input) input.blur();
  // 再点一下页面空白，触发 React 的 onBlur
  const header = drawer.querySelector('.drawer-title');
  if (header) header.click();
  return { ok: true };
})()
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--address", default="127.0.0.1:9502")
    parser.add_argument("--allow-write", action="store_true")
    parser.add_argument("--value", default="L（45-47）")
    parser.add_argument("--wait", type=float, default=2.0)
    args = parser.parse_args()

    if not args.allow_write:
        print("这会往未保存的表单里加规格值，必须显式加 --allow-write。")
        return 2

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

    steps = []
    with page.PageClient.connect(target["webSocketDebuggerUrl"]) as client:
        print("页面：{}".format(str(client.evaluate("location.href.split('?')[0]"))[:90]))
        opened = client.evaluate(OPEN_DRAWER_JS)
        if not isinstance(opened, dict) or not opened.get("ok"):
            print("开抽屉失败")
            return 1
        time.sleep(max(3.0, args.wait))

        baseline = client.evaluate(COUNT_JS)
        print("基线：{}".format(json.dumps(baseline, ensure_ascii=False)))
        steps.append({"step": "baseline", "state": baseline})

        print()
        print("── 步骤 1：点开值输入 ──")
        opened_input = client.evaluate(OPEN_INPUT_JS)
        print("  {}".format(json.dumps(opened_input, ensure_ascii=False)))
        time.sleep(args.wait)
        popup = client.evaluate(POPUP_ID_JS)
        print("  弹层：{}".format(json.dumps(popup, ensure_ascii=False)[:300]))
        steps.append({"step": "open_input", "result": opened_input, "popup": popup})

        print()
        print("── 步骤 2：点中候选 {!r} ──".format(args.value))
        picked = client.evaluate(PICK_LATEST_JS.replace("__WANT__", json.dumps(args.value, ensure_ascii=False)))
        print("  {}".format(json.dumps(picked, ensure_ascii=False)[:300]))
        time.sleep(args.wait)
        after_pick = client.evaluate(COUNT_JS)
        print("  计数：{}".format(json.dumps(after_pick, ensure_ascii=False)))
        steps.append({"step": "pick", "result": picked, "state": after_pick})

        committed = (after_pick or {}).get("count") != (baseline or {}).get("count")

        if not committed:
            print()
            print("── 步骤 3：未提交 → 试回车 ──")
            entered = client.evaluate(PRESS_ENTER_JS)
            print("  {}".format(json.dumps(entered, ensure_ascii=False)))
            time.sleep(args.wait)
            after_enter = client.evaluate(COUNT_JS)
            print("  计数：{}".format(json.dumps(after_enter, ensure_ascii=False)))
            steps.append({"step": "enter", "result": entered, "state": after_enter})
            committed = (after_enter or {}).get("count") != (baseline or {}).get("count")

        if not committed:
            print()
            print("── 步骤 4：仍未提交 → 试失焦 ──")
            blurred = client.evaluate(BLUR_JS)
            print("  {}".format(json.dumps(blurred, ensure_ascii=False)))
            time.sleep(args.wait)
            after_blur = client.evaluate(COUNT_JS)
            print("  计数：{}".format(json.dumps(after_blur, ensure_ascii=False)))
            steps.append({"step": "blur", "result": blurred, "state": after_blur})
            committed = (after_blur or {}).get("count") != (baseline or {}).get("count")

        final = client.evaluate(COUNT_JS)

    print()
    print("==== 结论 ====")
    print("  基线计数：{}".format((baseline or {}).get("count")))
    print("  最终计数：{}".format((final or {}).get("count")))
    print("  是否提交：{}".format("是" if committed else "否"))
    if committed:
        last = steps[-1]["step"]
        name = {"pick": "点中候选即提交", "enter": "需要回车才提交", "blur": "需要失焦才提交"}.get(last, last)
        print("  提交时机：{}".format(name))

    TMP_DIR.mkdir(parents=True, exist_ok=True)
    out = TMP_DIR / "sku-commit-experiment-{}.json".format(datetime.now().strftime("%Y%m%d%H%M%S"))
    out.write_text(json.dumps({
        "captured_at": datetime.now().isoformat(timespec="seconds"),
        "clicked_confirm_create": False,
        "never_did": ["确认创建", "保存草稿", "提交宝贝信息"],
        "value": args.value,
        "committed": committed,
        "steps": steps,
        "baseline": baseline,
        "final": final,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print()
    print("产物：{}".format(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# -*- coding: utf-8 -*-
"""勘察：点「+ 创建规格」之后出现的规格面板结构。

背景：`skus.sku_table_root` 与 `skus.sku_row` 一直是 unknown——表格在点
「+ 创建规格」**之后**才渲染。本脚本把那个面板打开，把结构读出来。

边界：只**展开面板**（纯前端动作），读结构后按 Esc / 关闭按钮收起，
**不点任何「确定 / 生成」按钮**，因此不会创建任何规格。

用法::

    python taobao-publisher/scripts/probe-sku-panel.py --address 127.0.0.1:9502
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

from taobao_publish import locating, page  # noqa: E402

TMP_DIR = SUBPROJECT / "tmp"

#: 点「+ 创建规格」。按钮文本实测唯一命中（verify-locating-live）。
OPEN_JS = """
(() => {
  const TEXT = '+ 创建规格';
  const btns = Array.from(document.querySelectorAll('button'))
    .filter(b => (b.textContent || '').trim() === TEXT);
  if (btns.length !== 1) {
    return { ok: false, reason: btns.length === 0 ? 'not_found' : 'ambiguous',
             hitCount: btns.length,
             seen: Array.from(document.querySelectorAll('button'))
               .map(b => (b.textContent || '').trim()).filter(Boolean).slice(0, 30) };
  }
  const r = btns[0].getBoundingClientRect();
  if (r.width === 0 && r.height === 0) return { ok: false, reason: 'not_visible' };
  btns[0].click();
  return { ok: true };
})()
"""

#: 读打开后的弹层 / 抽屉 / 面板结构。
PANEL_JS = r"""
(() => {
  // 规格面板可能是弹窗、抽屉或就地展开。三类都找。
  const CANDIDATES = [
    '.next-dialog', '.next-overlay-inner', '.next-drawer', '.next-sidesheet',
    '[class*="spec"]', '[class*="Spec"]', '[class*="sku"]', '[class*="Sku"]',
  ];
  const found = [];
  for (const sel of CANDIDATES) {
    for (const el of Array.from(document.querySelectorAll(sel))) {
      const r = el.getBoundingClientRect();
      if (r.width === 0 || r.height === 0) continue;
      found.push({
        selector: sel,
        tag: el.tagName.toLowerCase(),
        className: typeof el.className === 'string' ? el.className.slice(0, 110) : '',
        width: Math.round(r.width),
        height: Math.round(r.height),
        textStart: (el.textContent || '').trim().slice(0, 80),
        childCount: el.children.length,
        inputs: el.querySelectorAll('input,textarea,select,[role="combobox"]').length,
        buttons: Array.from(el.querySelectorAll('button'))
          .map(b => (b.textContent || '').trim()).filter(Boolean).slice(0, 10),
      });
    }
  }

  // 页面上出现的销售属性候选值（颜色/尺码一类的词）
  const body = document.body ? (document.body.innerText || '') : '';
  const KEYWORDS = ['颜色', '尺码', '规格', '销售属性', '添加规格', '生成', '确定',
                    '批量生成', '自定义', '规格值', 'SKU'];
  const keywordHits = {};
  for (const k of KEYWORDS) keywordHits[k] = body.includes(k);

  return {
    panels: found.slice(0, 12),
    keywordHits,
    panelCount: found.length,
  };
})()
"""

CLOSE_JS = r"""
(() => {
  // 优先找「取消 / 关闭」；找不到就按 Esc。**绝不点「确定 / 生成」**。
  const btns = Array.from(document.querySelectorAll('button'));
  const cancel = btns.find(b => ['取消', '关闭'].includes((b.textContent || '').trim()));
  if (cancel) { cancel.click(); return 'clicked_cancel'; }
  const closer = document.querySelector('.next-dialog-close, .next-overlay-close, [aria-label="close"]');
  if (closer) { closer.click(); return 'clicked_close'; }
  document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', keyCode: 27, bubbles: true }));
  return 'escape';
})()
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--address", default="127.0.0.1:9502")
    parser.add_argument("--wait", type=float, default=3.0)
    parser.add_argument("--keep-open", action="store_true", help="读完不收起（默认收起）")
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

        # 先确认按钮还是唯一命中的
        probe = client.evaluate(locating.locate_button_expression("+ 创建规格"))
        button = locating.describe_located_button(probe)
        print("「+ 创建规格」：命中 {} 可见 {} 禁用 {}".format(
            button.hit_count, button.visible_count, button.disabled))

        # 记录当前 SKU 表格（打开面板之前）
        before = client.evaluate("""
(() => ({
  tables: document.querySelectorAll('table').length,
  rows: document.querySelectorAll('table tr').length,
  bodyHasSku: (document.body ? document.body.innerText : '').includes('SKU'),
}))()
""")
        print("打开前：{}".format(json.dumps(before, ensure_ascii=False)))

        opened = client.evaluate(OPEN_JS)
        print()
        print("点击「+ 创建规格」：{}".format(json.dumps(opened, ensure_ascii=False)[:200]))
        if not isinstance(opened, dict) or not opened.get("ok"):
            return 1

        time.sleep(args.wait)
        panel = client.evaluate(PANEL_JS)
        closed = None
        if not args.keep_open:
            closed = client.evaluate(CLOSE_JS)

    if not isinstance(panel, dict):
        print("没读到面板")
        return 1

    print()
    print("==== 关键词 ====")
    print("  {}".format(json.dumps(panel["keywordHits"], ensure_ascii=False)))
    print()
    print("==== 可见面板 {} 个 ====".format(panel["panelCount"]))
    for item in panel["panels"]:
        print("  {:<22} <{}> {}x{} inputs={} childs={}".format(
            item["selector"], item["tag"], item["width"], item["height"],
            item["inputs"], item["childCount"]))
        print("      class={}".format(item["className"][:90]))
        print("      buttons={}".format(json.dumps(item["buttons"], ensure_ascii=False)))
        print("      text={!r}".format(item["textStart"][:70]))
    print()
    print("关闭动作：{}".format(closed))

    TMP_DIR.mkdir(parents=True, exist_ok=True)
    out = TMP_DIR / "sku-panel-{}.json".format(datetime.now().strftime("%Y%m%d%H%M%S"))
    out.write_text(json.dumps({
        "captured_at": datetime.now().isoformat(timespec="seconds"),
        "clicked_confirm": False,
        "not_done": ["点确定/生成规格", "填 SKU 明细", "保存草稿", "提交"],
        "opened": opened,
        "before": before,
        "panel": panel,
        "close_action": closed,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print()
    print("产物：{}".format(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

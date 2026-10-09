# -*- coding: utf-8 -*-
"""勘察：页面上的「遮挡弹层」是什么元素 —— `common.blocking_overlay` 的取证。

`PageSnapshot` 有四个 DOM 事实字段（`has_workbench_root` / `has_blocking_overlay` /
`has_submit_control` / `has_save_draft_control`），`snapshot_from_probe` 把它们
一律留成 `None`（理由：本模块不做 Runtime.evaluate）。而预检在写模式下把 `None`
当成阻塞项——所以真实写入永远过不了预检。

现在有了 `PageClient`，可以真的评估这些事实。本脚本**只读**，把四件事一起取到：

  1. 工作台根节点是否存在；
  2. 有没有**遮挡**弹层（重点：区分「遮挡」与「非模态浮层」）；
  3. 提交控件在不在；
  4. 保存草稿控件在不在。

用法::

    python taobao-publisher/scripts/probe-page-facts.py --address 127.0.0.1:9502
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

#: 一次取四件事 + 顺带把候选的「遮挡」标记全部列出来。
FACTS_JS = r"""
(() => {
  const visible = (el) => {
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  };

  // 1) 工作台根节点
  const ROOT_SELECTORS = [
    '.sell-component-info-wrapper-wrap',
    '.sell-component-navigation-bar',
    '.next-form',
  ];
  const rootHits = {};
  for (const sel of ROOT_SELECTORS) {
    rootHits[sel] = Array.from(document.querySelectorAll(sel)).filter(visible).length;
  }

  // 2) 遮挡候选：Fusion 的模态遮罩与对话框
  const OVERLAY_CANDIDATES = [
    '.next-overlay-backdrop',          // 模态遮罩
    '.next-dialog',                    // 对话框
    '.next-dialog-body',
    '.next-loading',                   // 全屏加载
    '.next-message',                   // 顶部提示（不遮挡）
    '.next-overlay-inner',             // 所有浮层（含非模态）
  ];
  const overlayHits = {};
  for (const sel of OVERLAY_CANDIDATES) {
    overlayHits[sel] = Array.from(document.querySelectorAll(sel)).filter(visible).length;
  }

  // 模态遮罩的细节：它盖住多大面积
  const backdrops = Array.from(document.querySelectorAll('.next-overlay-backdrop'))
    .filter(visible)
    .map(el => {
      const r = el.getBoundingClientRect();
      return { w: Math.round(r.width), h: Math.round(r.height),
               className: String(el.className).slice(0, 80) };
    });

  // 3/4) 提交与保存草稿控件
  const btns = Array.from(document.querySelectorAll('button'));
  const countText = (text) => btns.filter(b => (b.textContent || '').trim() === text).length;

  return {
    href: location.href.split('?')[0],
    rootHits,
    overlayHits,
    backdrops,
    submitControls: countText('提交宝贝信息'),
    saveDraftControls: countText('保存草稿'),
    // 页面上所有可见浮层的类名，便于判断哪种算「遮挡」
    visibleOverlays: Array.from(document.querySelectorAll('.next-overlay-inner'))
      .filter(visible).map(el => String(el.className).slice(0, 90)),
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
        clean = client.evaluate(FACTS_JS)
        print("==== 干净页面（无弹层）====")
        print(json.dumps(clean, ensure_ascii=False, indent=1)[:1400])

        # 故意打开一个浮层，看遮罩会不会出现
        print()
        print("── 打开图片选择弹层，再读一次 ──")
        area = client.evaluate("""
(() => {
  const a = Array.from(document.querySelectorAll('.sell-component-info-wrapper-wrap'))
    .find(el => (el.textContent || '').includes('1:1主图'));
  const s = a && a.querySelector('.image-empty');
  if (s) { s.click(); return true; }
  return false;
})()
""")
        print("  点了空位：{}".format(area))
        time.sleep(4)
        with_popup = client.evaluate(FACTS_JS)
        print(json.dumps(with_popup, ensure_ascii=False, indent=1)[:1400])
        # 关掉
        client.evaluate("""
(() => {
  document.dispatchEvent(new KeyboardEvent('keydown', {key:'Escape',keyCode:27,bubbles:true}));
  return 'closed';
})()
""")

    TMP_DIR.mkdir(parents=True, exist_ok=True)
    out = TMP_DIR / "page-facts-{}.json".format(datetime.now().strftime("%Y%m%d%H%M%S"))
    out.write_text(json.dumps({
        "captured_at": datetime.now().isoformat(timespec="seconds"),
        "clicked_nothing_else": True,
        "clean": clean,
        "with_popup": with_popup,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print()
    print("产物：{}".format(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# -*- coding: utf-8 -*-
"""勘察：展开运费模板下拉，同时抓 **DOM 选项**与**拉模板的接口**。

两件事一起做，因为展开下拉这个动作只做一次：

  1. B-04 要的接口名 —— 之前一直只有「怎么定位控件」，没有「数据从哪来」；
  2. `fill_freight` 要的选项结构。

边界：只**展开**下拉（纯前端动作），读结构后按 Esc 收起，**不选任何值**。

用法::

    python taobao-publisher/scripts/probe-freight-dropdown.py --address 127.0.0.1:9502
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SUBPROJECT = SCRIPT_DIR.parent
if str(SUBPROJECT) not in sys.path:
    sys.path.insert(0, str(SUBPROJECT))

from taobao_publish import locating, page  # noqa: E402

TMP_DIR = SUBPROJECT / "tmp"

#: 按文本锚点找到「运费模板」的容器，点它里面的 combobox。
OPEN_JS = r"""
(() => {
  const ANCHOR = '运费模板';
  const all = Array.from(document.querySelectorAll('div,span,label'));
  const exact = all.filter(el => (el.textContent || '').trim() === ANCHOR);
  if (!exact.length) return { ok: false, reason: 'anchor_not_found' };
  const anchorEl = exact[exact.length - 1];
  let node = anchorEl;
  let container = null;
  for (let hop = 0; hop <= 4 && node; hop++) {
    const controls = Array.from(node.querySelectorAll('input,textarea,select,[role="combobox"]'))
      .filter(el => { const b = el.getBoundingClientRect(); return b.width > 0 && b.height > 0; });
    if (controls.length === 1) { container = node; break; }
    node = node.parentElement;
  }
  if (!container) return { ok: false, reason: 'no_unique_container' };
  const control = container.querySelector('input,select,[role="combobox"]');
  if (!control) return { ok: false, reason: 'no_control' };
  control.click();
  control.focus();
  return {
    ok: true,
    containerClass: String(container.className).slice(0, 100),
    controlPlaceholder: control.getAttribute('placeholder') || '',
  };
})()
"""

#: 读下拉选项与它所在的容器结构。
#:
#: ⚠️ **两种下拉的容器类名不一样**，实测：
#:
#: * 品牌下拉   ``.next-select-popup-wrap``（带搜索框，虚拟滚动）
#: * 运费模板   ``.next-overlay-inner.next-select-single-menu``（简单单选菜单）
#:
#: 上一版只认前者，于是「下拉明明开了」却报「没有可见的下拉容器」。
#: 另外**不要把 ``.next-menu`` 算进来**：那会抓到顶部导航栏
#: （基础信息/销售信息/物流服务/图文描述），选项看起来完全不对。
DROPDOWN_SELECTORS = (
    ".next-select-popup-wrap",
    ".next-overlay-inner.next-select-single-menu",
    ".next-overlay-inner.next-select-menu",
)

OPTIONS_JS = """
(() => {
  const SELS = __SELS__;
  let root = null;
  let usedSelector = '';
  for (const sel of SELS) {
    const found = Array.from(document.querySelectorAll(sel))
      .filter(e => e.getBoundingClientRect().height > 0);
    if (found.length) { root = found[0]; usedSelector = sel; break; }
  }
  if (!root) {
    return {
      visible: false,
      visibleOverlays: Array.from(document.querySelectorAll('.next-overlay-inner'))
        .filter(e => e.getBoundingClientRect().height > 0)
        .map(e => ({ className: String(e.className).slice(0, 100),
                     height: Math.round(e.getBoundingClientRect().height) })),
    };
  }

  const describe = (el) => ({
    tag: el.tagName.toLowerCase(),
    className: typeof el.className === 'string' ? el.className.slice(0, 90) : '',
    text: (el.textContent || '').trim().slice(0, 30),
    childCount: el.children.length,
  });

  const rows = [];
  const walk = (el, depth) => {
    if (depth > 4 || rows.length > 30) return;
    for (const kid of Array.from(el.children).slice(0, 8)) {
      rows.push({ depth, ...describe(kid) });
      walk(kid, depth + 1);
    }
  };
  walk(root, 0);

  const optionLike = Array.from(root.querySelectorAll('*')).filter(el => {
    const t = (el.textContent || '').trim();
    return el.children.length === 0 && t.length > 0 && t.length <= 30;
  }).slice(0, 20).map(describe);

  return {
    visible: true,
    usedSelector,
    rootClass: String(root.className).slice(0, 110),
    structure: rows,
    optionLike,
  };
})()
""".replace("__SELS__", json.dumps(list(DROPDOWN_SELECTORS)))

CLOSE_JS = r"""
(() => {
  document.body.click();
  document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', keyCode: 27, bubbles: true }));
  return 'closed';
})()
"""

#: 记这些 host 的请求；用于找拉运费模板列表的接口。
INTERESTING = ("taobao.com", "tmall.com", "alibaba")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--address", default="127.0.0.1:9502")
    parser.add_argument("--wait", type=float, default=4.0)
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

    ws = websocket.create_connection(target["webSocketDebuggerUrl"], timeout=10, suppress_origin=True)
    ws.settimeout(2)
    counter = [0]
    requests = []

    def send(method, params=None):
        counter[0] += 1
        ws.send(json.dumps({"id": counter[0], "method": method, "params": params or {}}))
        return counter[0]

    def wait_for(message_id, timeout=20):
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                message = json.loads(ws.recv())
            except Exception:
                continue
            if message.get("method") == "Network.requestWillBeSent":
                params = message.get("params") or {}
                request = params.get("request") or {}
                url = str(request.get("url") or "")
                host = urllib.parse.urlsplit(url).netloc
                if url.startswith("http") and any(d in host for d in INTERESTING):
                    query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
                    requests.append({
                        "host": host,
                        "path": urllib.parse.urlsplit(url).path,
                        "method": request.get("method"),
                        "mtop_api": (query.get("api") or [""])[0] or None,
                        "param_names": sorted(query.keys()),
                    })
                continue
            if message.get("id") == message_id:
                return (message.get("result") or {}).get("result", {}).get("value")
        return None

    send("Network.enable")
    send("Runtime.enable")

    print("页面：{}".format(str(wait_for(send("Runtime.evaluate", {
        "expression": "location.href.split('?')[0]", "returnByValue": True})))[:90]))

    baseline = len(requests)
    opened = wait_for(send("Runtime.evaluate", {
        "expression": OPEN_JS, "returnByValue": True, "awaitPromise": True}))
    print()
    print("展开运费模板下拉：{}".format(json.dumps(opened, ensure_ascii=False)[:200]))
    if not isinstance(opened, dict) or not opened.get("ok"):
        ws.close()
        return 1

    time.sleep(args.wait)
    options = wait_for(send("Runtime.evaluate", {
        "expression": OPTIONS_JS, "returnByValue": True, "awaitPromise": True}))
    wait_for(send("Runtime.evaluate", {"expression": CLOSE_JS, "returnByValue": True}))
    ws.close()

    print()
    if isinstance(options, dict) and options.get("visible"):
        print("容器 class：{}".format(options["rootClass"]))
        print()
        print("==== 结构 ====")
        for row in options["structure"][:24]:
            print("  {:>2} {:<6} {:<6} {:<44} {!r}".format(
                row["depth"], row["tag"], row["childCount"], row["className"][:42], row["text"][:26]))
        print()
        print("==== 叶子候选（可能是选项）====")
        for item in options["optionLike"]:
            print("  <{}> {:<44} {!r}".format(item["tag"], item["className"][:42], item["text"]))
    else:
        print("没有可见的下拉容器")

    print()
    new_requests = requests[baseline:]
    print("==== 展开期间新产生的请求（{} 个）====".format(len(new_requests)))
    seen = set()
    for item in new_requests:
        key = (item["host"], item["path"], item["mtop_api"])
        if key in seen:
            continue
        seen.add(key)
        extra = "  mtop={}".format(item["mtop_api"]) if item["mtop_api"] else ""
        print("  {:<28} {:<52}{}".format(item["host"][:26], item["path"][:50], extra))

    TMP_DIR.mkdir(parents=True, exist_ok=True)
    out = TMP_DIR / "freight-dropdown-{}.json".format(datetime.now().strftime("%Y%m%d%H%M%S"))
    out.write_text(json.dumps({
        "captured_at": datetime.now().isoformat(timespec="seconds"),
        "selected_nothing": True,
        "not_done": ["选择运费模板值", "保存草稿", "提交"],
        "opened": opened,
        "options": options,
        "requests_during_open": new_requests,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print()
    print("产物：{}".format(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

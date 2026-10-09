# -*- coding: utf-8 -*-
"""勘察：类目页「搜索发品」结果条目的结构。

目标是把 `contracts/selectors.json` 的 ``category.search_result_item`` 从 unknown 取证。
前一轮只知道「搜索会返回匹配的已有商品，带 全部/类目/我的商品 三个 tab」，
但不知道**结果条目本身长什么样、怎么唯一识别一个条目**。

边界（本脚本）：

  做：导航到类目页、在「搜索发品」框里输入关键词、点「搜索」、读结果结构。
  不做：**不点击任何结果条目**（点它会选中类目，属于状态变更，由下一步单独做）。

输入+搜索只让页面去查建议，**不改变平台上的任何商品状态**。

用法::

    python taobao-publisher/scripts/probe-category-results.py --address 127.0.0.1:9502 --keyword 袜子
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
CATEGORY_URL = "https://item.upload.taobao.com/sell/ai/category.htm"

SEARCH_JS = """
(() => {
  const input = document.querySelector('input[placeholder*="可输入产品名称"]');
  if (!input) return { ok: false, step: 'input' };
  const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
  setter.call(input, __KEYWORD__);
  input.dispatchEvent(new Event('input', { bubbles: true }));
  input.dispatchEvent(new Event('change', { bubbles: true }));
  const btn = Array.from(document.querySelectorAll('button')).find(b => (b.textContent || '').trim() === '搜索');
  if (!btn) return { ok: false, step: 'button' };
  btn.click();
  return { ok: true };
})()
"""

# 读结果条目：找出「标题元素」并往上看它的可点击容器。
RESULTS_JS = r"""
(() => {
  // 上一轮实测：结果标题用 class 含 sell-rich-text card-title
  const titleEls = Array.from(document.querySelectorAll('.card-title'));
  const items = titleEls.slice(0, 12).map(el => {
    const title = (el.textContent || '').trim();
    // 往上找可点击的祖先（onclick / cursor:pointer / role=button 皆算）
    let clickable = null;
    let node = el;
    for (let hop = 0; hop < 7 && node && node.parentElement; hop++) {
      node = node.parentElement;
      const style = window.getComputedStyle(node);
      const hasHandler = typeof node.onclick === 'function';
      const role = node.getAttribute('role') || '';
      const tag = node.tagName.toLowerCase();
      if (hasHandler || style.cursor === 'pointer' || role === 'button' || tag === 'a' || tag === 'li') {
        clickable = {
          hop, tag,
          role,
          className: typeof node.className === 'string' ? node.className.slice(0, 100) : '',
          hasOnclick: hasHandler,
          cursor: style.cursor,
          childCount: node.children.length,
        };
        break;
      }
    }
    return {
      title,
      titleTag: el.tagName.toLowerCase(),
      titleClass: typeof el.className === 'string' ? el.className.slice(0, 100) : '',
      clickable,
    };
  });

  // 结果的列表容器：看看条目共同的父节点
  const parents = titleEls.map(el => el.parentElement).filter(Boolean);
  const parentInfo = parents.slice(0, 3).map(p => ({
    tag: p.tagName.toLowerCase(),
    className: typeof p.className === 'string' ? p.className.slice(0, 100) : '',
    childCount: p.children.length,
  }));

  // 当前选中的 tab
  const tabs = Array.from(document.querySelectorAll('[role="tab"]')).map(t => ({
    text: (t.textContent || '').trim().slice(0, 12),
    active: (t.className || '').includes('active') || t.getAttribute('aria-selected') === 'true',
  }));

  // 「确认，下一步」当前是否可用
  const nextBtn = Array.from(document.querySelectorAll('button'))
    .find(b => (b.textContent || '').trim().includes('确认，下一步'));

  return {
    titleCount: titleEls.length,
    items,
    parentInfo,
    tabs,
    nextButton: nextBtn ? { disabled: nextBtn.disabled === true, className: String(nextBtn.className).slice(0, 90) } : null,
  };
})()
"""


def resolve(address):
    with urllib.request.urlopen("http://{}/json/list".format(address), timeout=5) as response:
        targets = json.loads(response.read().decode("utf-8"))
    return next(
        (t for t in targets
         if t.get("type") == "page" and "item.upload.taobao.com" in str(t.get("url") or "")),
        None,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--address", default="127.0.0.1:9502")
    parser.add_argument("--keyword", default="袜子")
    parser.add_argument("--wait", type=float, default=7.0)
    parser.add_argument("--skip-navigate", action="store_true", help="已经在类目页时跳过导航")
    args = parser.parse_args()

    target = resolve(args.address)
    if target is None:
        print("没有发布工作台页面")
        return 1

    with page.PageClient.connect(target["webSocketDebuggerUrl"]) as client:
        if not args.skip_navigate:
            print("导航到类目页…")
            client.evaluate("location.href = {!r}; 'navigating'".format(CATEGORY_URL))
            time.sleep(10)
        else:
            client.evaluate("'stay'")

        print("当前页面：{}".format(str(client.evaluate("location.href.split('?')[0]"))[:90]))

        print("输入 {!r} 并点「搜索」…".format(args.keyword))
        typed = client.evaluate(SEARCH_JS.replace("__KEYWORD__", json.dumps(args.keyword, ensure_ascii=False)))
        if not isinstance(typed, dict) or not typed.get("ok"):
            print("搜索交互失败：{}".format(json.dumps(typed, ensure_ascii=False)))
            return 1

        time.sleep(args.wait)
        data = client.evaluate(RESULTS_JS)

        # 顺便确认「选择类目」按钮还在（它是类目页的入口之一）
        selector_button = client.evaluate(locating.locate_button_expression("选择类目"))

    if not isinstance(data, dict):
        print("没取到结果结构")
        return 1

    print()
    print("结果标题数：{}".format(data["titleCount"]))
    print("tab：{}".format(json.dumps(data["tabs"], ensure_ascii=False)))
    print("「确认，下一步」：{}".format(json.dumps(data["nextButton"], ensure_ascii=False)))
    print()
    print("==== 结果条目 ====")
    for i, item in enumerate(data["items"]):
        click = item.get("clickable") or {}
        print("  {:>2}. {!r}".format(i, item["title"][:40]))
        print("      标题 <{}> class={}".format(item["titleTag"], item["titleClass"][:60]))
        if click:
            print("      可点击祖先 hop={} <{}> role={} cursor={} class={}".format(
                click.get("hop"), click.get("tag"), click.get("role") or "-",
                click.get("cursor"), click.get("className", "")[:56]))
        else:
            print("      ** 未找到可点击祖先 **")
    print()
    print("==== 条目父节点 ====")
    for p in data["parentInfo"]:
        print("  <{}> childs={} class={}".format(p["tag"], p["childCount"], p["className"][:70]))

    print()
    print("==== 「选择类目」按钮 ====")
    print("  {}".format(json.dumps(selector_button, ensure_ascii=False)[:200]))

    TMP_DIR.mkdir(parents=True, exist_ok=True)
    out = TMP_DIR / "category-results-{}.json".format(datetime.now().strftime("%Y%m%d%H%M%S"))
    out.write_text(json.dumps({
        "captured_at": datetime.now().isoformat(timespec="seconds"),
        "keyword": args.keyword,
        "clicked_any_result": False,
        "not_done": ["点击结果条目", "点击确认下一步", "保存草稿", "提交"],
        **data,
        "selector_button": selector_button,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print()
    print("产物：{}".format(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

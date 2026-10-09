# -*- coding: utf-8 -*-
"""验证：按标签文本定位「行」是否唯一且稳定。

这是 9 个阶段共同的基础。上一轮已确认真实行容器是
``.sell-component-info-wrapper-wrap``、标签是 ``.sell-component-info-wrapper-label``；
本脚本验证「按标签精确匹配行」在每个字段上是否**恰好命中 1 行**。

命中 0 行 → 字段在别的结构里，不能臆测。
命中 ≥2 行 → **绝对不能用来驱动写操作**（会写到错误的行），必须补更强的限定条件。

**纯只读**：不点击、不输入、不保存、不提交。

用法::

    python taobao-publisher/scripts/verify-label-locating.py --address 127.0.0.1:9502
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.request
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
TMP_DIR = SCRIPT_DIR.parent / "tmp"

FIELDS = [
    "材质成分", "面料", "上市年份季节", "编织工艺", "吊牌价", "防滑设计",
    "风格", "缝头工艺", "厚薄", "抗菌处理", "款式细节", "里料",
    "是否商场同款", "图案", "袜口弹性材质", "款号",
    "宝贝标题", "导购标题", "一口价", "总库存", "购买须知", "商家编码",
]

# 页面内实现「按标签找行」并统计命中数，同时给出每行内的控件画像。
VERIFY_EXPRESSION = r"""
(() => {
  const FIELDS = __FIELDS__;
  const ROW = '.sell-component-info-wrapper-wrap';
  const LABEL = '.sell-component-info-wrapper-label';

  const labelOf = (row) => {
    const el = row.querySelector(LABEL);
    return el ? (el.textContent || '').trim() : '';
  };

  // 先建立一次索引，避免每个字段都全量查询
  const rows = Array.from(document.querySelectorAll(ROW));
  const index = new Map();
  for (const row of rows) {
    const key = labelOf(row);
    if (!key) continue;
    if (!index.has(key)) index.set(key, []);
    index.get(key).push(row);
  }

  const result = [];
  for (const field of FIELDS) {
    // 精确匹配优先；再退回「标签区文本以字段名开头」（有些带 * 或 重要 后缀）
    let hits = index.get(field) || [];
    let matchMode = 'exact';
    if (!hits.length) {
      hits = rows.filter(r => labelOf(r).startsWith(field));
      matchMode = 'prefix';
    }
    const detail = hits.slice(0, 3).map(row => {
      const controls = Array.from(row.querySelectorAll('input,textarea,select,[role="combobox"]'))
        .filter(el => { const b = el.getBoundingClientRect(); return b.width > 0 && b.height > 0; });
      return {
        rowClass: typeof row.className === 'string' ? row.className.slice(0, 100) : '',
        visible: row.getBoundingClientRect().height > 0,
        controlCount: controls.length,
        controls: controls.slice(0, 3).map(el => ({
          tag: el.tagName.toLowerCase(),
          role: el.getAttribute('role') || '',
          placeholder: el.getAttribute('placeholder') || '',
          disabled: el.disabled === true,
        })),
      };
    });
    result.push({ field, matchMode, hitCount: hits.length, detail });
  }

  // 顺带统计：整个页面里有多少行、多少行的标签是重复的
  const labelCounts = new Map();
  for (const row of rows) {
    const key = labelOf(row);
    if (!key) continue;
    labelCounts.set(key, (labelCounts.get(key) || 0) + 1);
  }
  const duplicated = Array.from(labelCounts.entries()).filter(([, n]) => n > 1);
  const unlabeled = rows.filter(r => !labelOf(r)).length;

  return {
    totalRows: rows.length,
    distinctLabels: labelCounts.size,
    rowsWithoutLabel: unlabeled,
    duplicatedLabels: duplicated.map(([k, n]) => ({ label: k, count: n })).slice(0, 20),
    fields: result,
  };
})()
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--address", default="127.0.0.1:9502")
    args = parser.parse_args()

    with urllib.request.urlopen("http://{}/json/list".format(args.address), timeout=5) as response:
        targets = json.loads(response.read().decode("utf-8"))
    pages = [
        t for t in targets
        if t.get("type") == "page" and "item.upload.taobao.com" in str(t.get("url") or "")
    ]
    if not pages:
        print("没有发布工作台页面")
        return 1
    page = pages[0]

    import websocket

    ws = websocket.create_connection(page["webSocketDebuggerUrl"], timeout=10, suppress_origin=True)
    ws.settimeout(3)
    ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate", "params": {
        "expression": VERIFY_EXPRESSION.replace("__FIELDS__", json.dumps(FIELDS, ensure_ascii=False)),
        "returnByValue": True, "awaitPromise": True,
    }}))

    data = None
    deadline = time.time() + 30
    while time.time() < deadline:
        try:
            message = json.loads(ws.recv())
        except Exception:
            continue
        if message.get("id") != 1:
            continue
        payload = message.get("result") or {}
        if payload.get("exceptionDetails"):
            print("页面内报错：{}".format(str(payload["exceptionDetails"])[:300]))
            ws.close()
            return 1
        data = (payload.get("result") or {}).get("value")
        break
    ws.close()

    if not isinstance(data, dict):
        print("没取到结果")
        return 1

    print("页面行总数 {}，其中无标签 {}；不同标签 {} 个".format(
        data["totalRows"], data["rowsWithoutLabel"], data["distinctLabels"]))
    if data["duplicatedLabels"]:
        print("!! 有重复标签（这些字段不能只靠标签定位）：")
        for item in data["duplicatedLabels"]:
            print("     {!r} 出现 {} 次".format(item["label"], item["count"]))
    else:
        print("没有重复标签 —— 说明标签可以唯一定位行")
    print()

    unique = ambiguous = missing = 0
    print("{:<12} {:<7} {:<6} {}".format("字段", "匹配方式", "命中", "行内控件"))
    print("-" * 78)
    for row in data["fields"]:
        hits = row["hitCount"]
        if hits == 0:
            missing += 1
            flag = "[缺失]"
        elif hits == 1:
            unique += 1
            flag = "[唯一]"
        else:
            ambiguous += 1
            flag = "[多重]"
        first = (row["detail"] or [{}])[0]
        controls = first.get("controls") or []
        ctrl = controls[0] if controls else {}
        print("{:<8}{:<12} {:<7} {:<6} 控件{}个 {} ph={!r}".format(
            flag, row["field"][:10], row["matchMode"], hits,
            first.get("controlCount", 0), ctrl.get("tag", "-"), (ctrl.get("placeholder") or "")[:14]))
    print()
    print("唯一 {} / 多重 {} / 缺失 {}".format(unique, ambiguous, missing))
    if ambiguous:
        print("!! 有多重命中的字段，实现时必须补限定条件，不能直接用标签定位")

    TMP_DIR.mkdir(parents=True, exist_ok=True)
    out = TMP_DIR / "label-locating-verify-{}.json".format(datetime.now().strftime("%Y%m%d%H%M%S"))
    out.write_text(json.dumps({
        "captured_at": datetime.now().isoformat(timespec="seconds"),
        "page_url": page.get("url"),
        "read_only": True,
        "row_selector": ".sell-component-info-wrapper-wrap",
        "label_selector": ".sell-component-info-wrapper-label",
        **data,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print()
    print("产物：{}".format(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

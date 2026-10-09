# -*- coding: utf-8 -*-
"""只读实测：表单上每一行的**控件类型**。

## 为什么要量

`MEASURED_ROW_LABELS` 只记了 ``controls=N``（行内有几个控件），**没记控件是什么**。
而 `fill_props` 对每个属性都用 `fill_text_field`——它自己的文档就写着
「属性控件**多是下拉框**」。

后果：地图里 `controls=1` 的行里，凡是下拉（品牌、适用季节、风格…）
都会以「标签 '品牌' 没有定位到行」失败——**那个报错说的是症状，不是原因**。

这次量出每行的 `kind`，让 `fill_props` 能**按控件类型**决定能不能写、
并给出说得出原因的错误。

## 只读

只读 DOM 结构与 class/属性，**不点、不写、不改**。

用法::

    python taobao-publisher/scripts/probe-row-control-kinds.py --address 127.0.0.1:9502
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
from taobao_publish.locating import MEASURED_ROW_LABELS  # noqa: E402

TMP_DIR = SUBPROJECT / "tmp"

#: 在页面里判定每一行的控件类型。**纯读**。
MEASURE_EXPRESSION = r"""
((labels) => {
  const out = [];
  // 表单行：每个 `<label>` 往上找到承载这一行的容器。
  const allLabels = Array.from(document.querySelectorAll('label'));
  const seen = new Set();
  for (const label of allLabels) {
    const text = (label.textContent || '').trim();
    if (!labels.includes(text) || seen.has(text)) continue;
    seen.add(text);

    // 往上找这一行的容器
    let row = label;
    for (let i = 0; i < 6 && row.parentElement; i++) {
      row = row.parentElement;
      if (row.querySelector('input, textarea, select, [class*="next-select"], [class*="next-input"]')) break;
    }
    const scope = row || label.parentElement || label;

    const selectors = [
      ['text', 'input[type="text"], input:not([type]), textarea'],
      ['number', 'input[type="number"]'],
      ['select', 'select'],
      ['dropdown', '[class*="next-select"]'],
      ['radio', 'input[type="radio"], [class*="next-radio"]'],
      ['checkbox', 'input[type="checkbox"], [class*="next-checkbox"]'],
      ['button', 'button'],
    ];
    const kinds = {};
    for (const [name, sel] of selectors) {
      const n = scope.querySelectorAll(sel).length;
      if (n) kinds[name] = n;
    }
    out.push({ label: text, kinds, rowCls: String(scope.className || '').slice(0, 70) });
  }
  return out;
})(LABELS)
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

    labels = sorted(MEASURED_ROW_LABELS)
    with page.PageClient.connect(target["webSocketDebuggerUrl"]) as client:
        payload = client.evaluate(
            MEASURE_EXPRESSION.replace("LABELS", json.dumps(labels, ensure_ascii=False)))

    if not isinstance(payload, list):
        print("量不到：{}".format(str(payload)[:200]))
        return 1

    print("=" * 78)
    print("表单行的控件类型（只读实测）")
    print("=" * 78)
    print("地图里标了 controls>0、但页面上没量到的行：")
    measured = {item["label"]: item for item in payload}
    for label, info in sorted(MEASURED_ROW_LABELS.items()):
        if info.get("controls", 0) > 0 and label not in measured:
            print("  ? {}".format(label))
    print()

    print("=" * 78)
    print("量到的行（{} 个）".format(len(payload)))
    print("=" * 78)
    text_like, dropdown_like, other = [], [], []
    for item in payload:
        kinds = item.get("kinds") or {}
        if kinds.get("dropdown"):
            dropdown_like.append(item)
        elif kinds.get("text") or kinds.get("number"):
            text_like.append(item)
        else:
            other.append(item)

    def show(title, items):
        print()
        print("---- {}（{}）----".format(title, len(items)))
        for item in items:
            print("  {:<14} {}  {}".format(
                item["label"],
                json.dumps(item.get("kinds") or {}, ensure_ascii=False),
                item.get("rowCls", "")[:40]))

    show("**含下拉**（文本方式写不进去）", dropdown_like)
    show("文本/数字类（可能能写）", text_like)
    show("两者都没有", other)

    TMP_DIR.mkdir(parents=True, exist_ok=True)
    out = TMP_DIR / "row-control-kinds-{}.json".format(datetime.now().strftime("%Y%m%d%H%M%S"))
    out.write_text(json.dumps({
        "captured_at": datetime.now().isoformat(timespec="seconds"),
        "read_only": True,
        "never_did": ["点击", "写入", "上传", "保存草稿", "提交"],
        "rows": payload,
        "summary": {
            "dropdown_like": [i["label"] for i in dropdown_like],
            "text_like": [i["label"] for i in text_like],
            "other": [i["label"] for i in other],
        },
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print()
    print("产物：{}".format(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

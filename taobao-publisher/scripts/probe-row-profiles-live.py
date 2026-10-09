# -*- coding: utf-8 -*-
"""用**生产逻辑**（`locate_row_expression`）量 46 个标签，回答一个问题：

**`品牌` 是「定位不到」还是「定位到了但控件是下拉」？**

这决定了修法：
* `hitCount == 0` → 定位逻辑有问题；
* `hitCount == 1` 但控件是下拉/组合框 → **`fill_props` 用文本方式写不进去**，
  报错应该说这件事，而不是说「没有定位到行」。

顺带把每行的控件 `role`/`tag`/`placeholder` 记录下来——这是 **kind** 的原始材料。

**只读**：`locate_row_expression` 页面端不点任何东西。
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

from taobao_publish import locating, page  # noqa: E402

TMP_DIR = SUBPROJECT / "tmp"


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

    rows = []
    with page.PageClient.connect(target["webSocketDebuggerUrl"]) as client:
        for label in sorted(locating.MEASURED_ROW_LABELS):
            try:
                profile = client.evaluate(locating.locate_row_expression(label))
            except Exception as exc:  # noqa: BLE001
                rows.append({"label": label, "error": "{}: {}".format(type(exc).__name__, exc)})
                continue
            if isinstance(profile, dict):
                profile["label"] = label
                rows.append(profile)

    found = [r for r in rows if r.get("hitCount")]
    missing = [r for r in rows if not r.get("hitCount")]

    print("=" * 78)
    print("用生产逻辑定位 46 个标签")
    print("=" * 78)
    print("定位到：{} 个；定位不到：{} 个".format(len(found), len(missing)))
    print()

    print("---- **定位不到**的（hitCount=0）----")
    for item in missing:
        print("  {}  {}".format(item["label"], item.get("error", "")))
    print()

    print("---- 定位到的，按控件形态分组 ----")
    combobox, plain, unknown = [], [], []
    for item in found:
        controls = item.get("controls") or []
        roles = {c.get("role") or "" for c in controls}
        tags = {c.get("tag") or "" for c in controls}
        if "combobox" in roles:
            combobox.append(item)
        elif tags & {"input", "textarea"}:
            plain.append(item)
        else:
            unknown.append(item)

    def show(title, items):
        print()
        print("  -- {}（{}）--".format(title, len(items)))
        for item in items:
            first = (item.get("controls") or [{}])[0]
            print("    {:<14} controls={} role={:<10} tag={:<8} placeholder={}".format(
                item["label"], item.get("controlCount"),
                first.get("role") or "-", first.get("tag") or "-",
                (first.get("placeholder") or "-")[:26]))

    show("**role=combobox（可搜索下拉）——文本方式写不进去**", combobox)
    show("普通 input/textarea", plain)
    show("其他", unknown)

    TMP_DIR.mkdir(parents=True, exist_ok=True)
    out = TMP_DIR / "row-profiles-{}.json".format(datetime.now().strftime("%Y%m%d%H%M%S"))
    out.write_text(json.dumps({
        "captured_at": datetime.now().isoformat(timespec="seconds"),
        "read_only": True,
        "never_did": ["点击", "写入", "上传", "保存草稿", "提交"],
        "profiles": rows,
        "summary": {
            "not_located": [i["label"] for i in missing],
            "combobox": [i["label"] for i in combobox],
            "plain_input": [i["label"] for i in plain],
            "other": [i["label"] for i in unknown],
        },
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print()
    print("产物：{}".format(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

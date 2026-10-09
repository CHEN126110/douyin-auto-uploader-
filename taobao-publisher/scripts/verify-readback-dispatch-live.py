# -*- coding: utf-8 -*-
"""只读实机验证：`readback` 的分派在真实发布页上逐条跑得通。

第 33 轮把 `readback` 从 4 项扩到 7 项（加了主图张数 / SKU 行数 / 运费模板），
之后一直没在真实页面上跑过。本脚本补上这一步——**纯只读，不写任何东西**。

它按 kind 逐条调 `_read_expected_value`，把读到的值打出来。
判据不是「值等于多少」（那取决于页面当前状态），而是：

1. **每条都不抛错**；
2. **每条的产物都是字符串**（比较两边 `strip()` 的前提）。

用法::

    python taobao-publisher/scripts/verify-readback-dispatch-live.py --address 127.0.0.1:9502
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

from taobao_publish import page, stages  # noqa: E402

TMP_DIR = SUBPROJECT / "tmp"

#: 逐条覆盖全部 kind。`text` 用几个真实存在的行标签。
CASES = (
    {"label": "宝贝标题", "kind": "text"},
    {"label": "导购标题", "kind": "text"},
    {"label": "一口价", "kind": "text"},
    {"label": "总库存", "kind": "text"},
    {"label": "主图张数", "kind": "main_image_count"},
    {"label": "SKU 行数", "kind": "sku_row_count"},
    {"label": "运费模板", "kind": "freight_template"},
)


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

    results = []
    with page.PageClient.connect(target["webSocketDebuggerUrl"]) as client:
        print("页面：{}".format(str(client.evaluate("location.href"))[:92]))
        print()
        print("=== readback 分派逐条 ===")
        for entry in CASES:
            record = dict(entry)
            try:
                got = stages._read_expected_value(client, page, entry)
                record["value"] = got
                record["isString"] = isinstance(got, str)
                print("  {:<10} kind={:<18} -> {!r}".format(
                    entry["label"], entry["kind"], got))
            except Exception as exc:  # noqa: BLE001
                record["error"] = "{}: {}".format(type(exc).__name__, exc)
                print("  {:<10} kind={:<18} -> **抛错** {}".format(
                    entry["label"], entry["kind"], record["error"][:70]))
            results.append(record)

    failed = [r for r in results if "error" in r or not r.get("isString")]
    print()
    print("=" * 62)
    print("共 {} 条：{} 条抛错、{} 条产物不是字符串".format(
        len(results),
        sum(1 for r in results if "error" in r),
        sum(1 for r in results if "error" not in r and not r.get("isString"))))
    print("→ {}".format("**全部跑通**" if not failed else "**有失败项**"))

    TMP_DIR.mkdir(parents=True, exist_ok=True)
    out = TMP_DIR / "readback-dispatch-{}.json".format(
        datetime.now().strftime("%Y%m%d%H%M%S"))
    out.write_text(json.dumps({
        "captured_at": datetime.now().isoformat(timespec="seconds"),
        "read_only": True,
        "never_did": ["上传", "保存草稿", "提交宝贝信息"],
        "results": results,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print()
    print("产物：{}".format(out))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

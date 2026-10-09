# -*- coding: utf-8 -*-
"""页面交互层的实机冒烟。

**默认只读**：只把每个字段的当前值读回来，验证「定位 → 读回」这条链路。
只有显式传 ``--allow-write`` 才会真的写值，而且写入的字段由 ``--field`` 指定、
值由 ``--value`` 指定——不提供「随便写点什么」的默认行为。

写入**不会保存草稿、不会提交**：值只停留在页面表单里。

用法::

    # 只读：列出各字段当前值
    python taobao-publisher/scripts/smoke-page-client.py --address 127.0.0.1:9502

    # 试写一个字段（显式授权），写完立刻回读校验
    python taobao-publisher/scripts/smoke-page-client.py --address 127.0.0.1:9502 \
        --allow-write --field 商家编码 --value TEST-001
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

#: 只读冒烟覆盖的字段：既包括文本字段，也包括下拉框（读回值同样是字符串）。
READ_FIELDS = [
    "宝贝标题", "导购标题", "商家编码", "款式细节", "款号", "是否商场同款",
    "吊牌价", "一口价", "总库存", "购买须知",
]


def resolve_target(address: str):
    with urllib.request.urlopen("http://{}/json/list".format(address), timeout=5) as response:
        targets = json.loads(response.read().decode("utf-8"))
    pages = [
        t for t in targets
        if t.get("type") == "page" and "item.upload.taobao.com" in str(t.get("url") or "")
    ]
    return pages[0] if pages else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--address", default="127.0.0.1:9502")
    parser.add_argument("--allow-write", action="store_true", help="显式允许写值（仍然不保存、不提交）")
    parser.add_argument("--field", default="", help="要试写的字段标签")
    parser.add_argument("--value", default="", help="要试写的值")
    args = parser.parse_args()

    target = resolve_target(args.address)
    if target is None:
        print("没有找到发布工作台页面")
        return 1
    print("页面：{}".format(str(target.get("url"))[:110]))
    print()

    results = {"read": [], "write": None}
    failures = 0

    with page.PageClient.connect(target["webSocketDebuggerUrl"], target_url=target.get("url", "")) as client:
        print("==== 只读：定位 + 读回 ====")
        print("{:<12} {:<8} {}".format("字段", "状态", "当前值"))
        print("-" * 60)
        for label in READ_FIELDS:
            try:
                value = page.read_text_field(client, label)
                shown = "(空)" if value is None or value == "" else repr(value)[:34]
                print("{:<12} {:<8} {}".format(label, "OK", shown))
                results["read"].append({"label": label, "ok": True, "value": value})
            except Exception as exc:  # noqa: BLE001 - 逐个字段报告，不中断
                failures += 1
                print("{:<12} {:<8} {}".format(label, "失败", type(exc).__name__ + ": " + str(exc)[:40]))
                results["read"].append({"label": label, "ok": False, "error": str(exc)})

        if args.allow_write:
            print()
            if not args.field or not args.value:
                print("--allow-write 需要同时给 --field 与 --value")
                return 1
            print("==== 写入（显式授权）：{} = {!r} ====".format(args.field, args.value))
            before = page.read_text_field(client, args.field)
            print("  写入前：{!r}".format(before))
            try:
                outcome = page.fill_text_field(client, args.field, args.value)
                print("  写入后回读：{!r}".format(outcome["read_back"]))
                print("  结果：回读一致，写入生效")
                results["write"] = {"field": args.field, "ok": True, **outcome, "before": before}
            except Exception as exc:  # noqa: BLE001
                failures += 1
                print("  结果：失败 {}: {}".format(type(exc).__name__, str(exc)[:80]))
                results["write"] = {"field": args.field, "ok": False, "error": str(exc), "before": before}
        else:
            print()
            print("（未传 --allow-write，没有写任何值）")

    TMP_DIR.mkdir(parents=True, exist_ok=True)
    out = TMP_DIR / "page-client-smoke-{}.json".format(datetime.now().strftime("%Y%m%d%H%M%S"))
    out.write_text(json.dumps({
        "captured_at": datetime.now().isoformat(timespec="seconds"),
        "page_url": target.get("url"),
        "wrote_anything": bool(args.allow_write),
        "never_did": ["保存草稿", "提交宝贝信息", "上传图片"],
        **results,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    print()
    print("产物：{}".format(out))
    print("结论：{}".format("全部通过" if failures == 0 else "{} 项失败".format(failures)))
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

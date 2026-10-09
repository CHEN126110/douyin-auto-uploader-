# -*- coding: utf-8 -*-
"""实机验证：用 ``taobao_publish.locating`` 生成的表达式去真实页面定位。

离线测试只能证明表达式「长得对」；这里证明它**真的能命中**——包括
唯一性命中、控件数量、以及唯一性守卫在真实数据上确实成立。

**纯只读**：只读 DOM，不点击、不输入、不保存、不提交。

用法::

    python taobao-publisher/scripts/verify-locating-live.py --address 127.0.0.1:9502
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

from taobao_publish import locating  # noqa: E402

TMP_DIR = SUBPROJECT / "tmp"


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
    counter = [0]

    def evaluate(expression: str):
        counter[0] += 1
        current = counter[0]
        ws.send(json.dumps({"id": current, "method": "Runtime.evaluate", "params": {
            "expression": expression, "returnByValue": True, "awaitPromise": True,
        }}))
        deadline = time.time() + 20
        while time.time() < deadline:
            try:
                message = json.loads(ws.recv())
            except Exception:
                continue
            if message.get("id") != current:
                continue
            payload = message.get("result") or {}
            if payload.get("exceptionDetails"):
                return {"__error__": str(payload["exceptionDetails"])[:300]}
            return (payload.get("result") or {}).get("value")
        return {"__error__": "超时"}

    labels = []
    for stage in ("fill_base", "fill_props", "fill_price_stock"):
        for label in locating.verified_labels_for(stage):
            labels.append((stage, label))

    print("用模块生成的表达式定位 {} 个标签…".format(len(labels)))
    print()
    print("{:<18} {:<16} {:<8} {:<7} {:<7} {}".format("标签", "阶段", "命中", "唯一", "控件", "判定"))
    print("-" * 82)

    results = []
    unique = ambiguous = missing = errors = 0
    for stage, label in labels:
        payload = evaluate(locating.locate_row_expression(label))
        if isinstance(payload, dict) and payload.get("__error__"):
            errors += 1
            print("{:<16} {:<16} {:<8} {:<7} {:<7} 页面报错：{}".format(
                label, stage, "-", "-", "-", payload["__error__"][:40]))
            results.append({"label": label, "stage": stage, "error": payload["__error__"]})
            continue

        row = locating.describe_located_row(payload)
        try:
            locating.require_unique(row)
            verdict = "可用"
            unique += 1
        except locating.LabelNotFound as exc:
            verdict = "缺失: {}".format(str(exc)[:24])
            missing += 1
        except locating.LabelAmbiguous as exc:
            verdict = "多重: {}".format(str(exc)[:24])
            ambiguous += 1

        print("{:<16} {:<16} {:<8} {:<7} {:<7} {}".format(
            label, stage, row.hit_count, str(row.unique), row.control_count, verdict))
        results.append({
            "label": label, "stage": stage, "hit_count": row.hit_count,
            "unique": row.unique, "control_count": row.control_count,
            "match_mode": row.match_mode, "verdict": verdict,
            "payload": payload if isinstance(payload, dict) else None,
        })

    # ---------- 按钮 ----------
    button_texts = [
        "提交宝贝信息", "保存草稿", "+ 创建规格", "添加材质成分", "切换类目",
        "批量导入", "预览", "保存为模板", "从1:1主图裁剪", "从3:4主图裁剪",
    ]
    print()
    print("用模块生成的表达式定位 {} 个按钮…".format(len(button_texts)))
    print()
    print("{:<18} {:<8} {:<8} {:<8} {}".format("按钮文本", "命中", "可见", "禁用", "判定"))
    print("-" * 70)
    button_results = []
    b_unique = b_bad = 0
    for text in button_texts:
        payload = evaluate(locating.locate_button_expression(text))
        if isinstance(payload, dict) and payload.get("__error__"):
            b_bad += 1
            print("{:<16} 页面报错：{}".format(text, payload["__error__"][:36]))
            button_results.append({"text": text, "error": payload["__error__"]})
            continue
        button = locating.describe_located_button(payload)
        try:
            locating.require_unique_button(button)
            verdict = "可用"
            b_unique += 1
        except (locating.LabelNotFound, locating.LabelAmbiguous) as exc:
            verdict = str(exc)[:34]
            b_bad += 1
        print("{:<16} {:<8} {:<8} {:<8} {}".format(
            text, button.hit_count, button.visible_count, str(button.disabled), verdict))
        button_results.append({
            "text": text, "hit_count": button.hit_count, "visible_count": button.visible_count,
            "disabled": button.disabled, "class_name": button.class_name, "verdict": verdict,
        })

    print()
    print("=" * 82)
    print("标签：唯一 {} / 多重 {} / 缺失 {} / 报错 {}".format(unique, ambiguous, missing, errors))
    print("按钮：可用 {} / 需补限定 {}".format(b_unique, b_bad))
    print("=" * 82)

    # 判定要分清两件事，别把「守卫正确拒绝」误报成「模块坏了」：
    #
    #   * 硬失败 —— 表达式本身不能用：命中 0、页面报错。这是缺陷。
    #   * 需补限定 —— 命中多个（或不可见）。**守卫按设计拒绝了**，
    #     这是正确行为；但该按钮在补齐限定条件之前不可用于写入。
    #
    # 因此 ``passed`` 只表示「模块的表达式在真实页面可用」，
    # 不表示「每个按钮都能直接点」。
    button_hard_failures = [
        r for r in button_results
        if r.get("error") or not r.get("hit_count")
    ]
    button_needs_qualifier = [
        r for r in button_results
        if not r.get("error") and (r.get("hit_count") or 0) > 1
    ]
    ok = (
        errors == 0 and ambiguous == 0 and missing == 0 and unique == len(labels)
        and not button_hard_failures
    )

    # 材质成分等自定义控件：行内没有可见控件是**已知**的（用「添加材质成分」按钮），
    # 单独标出来，不当成失败，但必须在报告里可见。
    no_control = [r["label"] for r in results if r.get("control_count") == 0]

    TMP_DIR.mkdir(parents=True, exist_ok=True)
    out = TMP_DIR / "locating-live-verify-{}.json".format(datetime.now().strftime("%Y%m%d%H%M%S"))
    out.write_text(json.dumps({
        "captured_at": datetime.now().isoformat(timespec="seconds"),
        "page_url": page.get("url"),
        "read_only": True,
        "row_selector": locating.ROW_SELECTOR,
        "label_selector": locating.LABEL_SELECTOR,
        "passed": ok,
        "labels": {"unique": unique, "ambiguous": ambiguous, "missing": missing, "errors": errors},
        "buttons": {"usable": b_unique, "needs_qualifier": b_bad,
                    "hard_failures": button_hard_failures,
                    "needs_qualifier_detail": button_needs_qualifier},
        "labels_without_inline_control": no_control,
        "label_results": results,
        "button_results": button_results,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    if no_control:
        print()
        print("注意：以下标签的行内没有可见控件，需要专门的处理方式（不能用通用控件定位）：")
        for label in no_control:
            print("    {}".format(label))
    if button_needs_qualifier:
        print()
        print("以下按钮**守卫已按设计拒绝**（命中多个），补齐限定条件前不可用于写入：")
        for item in button_needs_qualifier:
            print("    {!r} 命中 {} 个（可见 {} 个）".format(
                item["text"], item["hit_count"], item.get("visible_count")))
    print()
    print("产物：{}".format(out))
    print("结论：{}".format(
        "模块表达式在真实页面可用" if ok else "存在硬失败（命中 0 或页面报错），见上表"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

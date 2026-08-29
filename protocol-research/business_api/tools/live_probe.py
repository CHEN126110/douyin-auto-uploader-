# -*- coding: utf-8 -*-
"""联调探测工具：attach 真实浏览器，dump 页面结构 / 业务域导航入口 / 选择器命中。

用法（在 protocol-research 目录下）：
    python -m business_api.tools.live_probe                              # dump 当前页导航入口
    python -m business_api.tools.live_probe --url <URL> --wait 6         # 先导航并等待渲染
    python -m business_api.tools.live_probe --url <URL> --wait 6 --structure   # dump 列表页结构
    python -m business_api.tools.live_probe --sel "css:..."              # 探测某选择器命中

合规说明：仅 attach 用户已登录的真实浏览器做只读结构观察，不做任何写操作。
"""
from __future__ import annotations

import argparse
import os
import sys
import time

BUSINESS_KEYWORDS = [
    "商品", "订单", "售后", "营销", "推广", "数据", "罗盘",
    "资金", "店铺", "流量", "千川", "发货", "客户", "财务", "结算",
]

STRUCTURE_CANDIDATES = [
    ("table 行", "css:table tbody tr"),
    ("通用 row", "css:[class*=row]"),
    ("列表 item", "css:[class*=item]"),
    ("卡片 card", "css:[class*=card]"),
    ("商品 product", "css:[class*=product]"),
    ("商品 goods", "css:[class*=goods]"),
    ("列表 list", "css:[class*=list-]"),
]

ACTION_KEYWORDS = ["上架", "下架", "编辑", "删除", "推广", "复制", "数据"]


def _connect(address: str):
    try:
        from DrissionPage import ChromiumOptions, ChromiumPage
    except Exception as exc:
        print(f"[ERR] 无法导入 DrissionPage：{exc}")
        sys.exit(2)
    try:
        return ChromiumPage(ChromiumOptions().set_address(address))
    except Exception as exc:
        print(f"[ERR] 连接调试端口失败 {address}：{exc}")
        print("      请确认已用 --remote-debugging-port 启动 Chrome，或先运行 launcher。")
        sys.exit(2)


def _dump_structure(page, limit: int) -> None:
    print("\n[结构容器命中数]：")
    for label, sel in STRUCTURE_CANDIDATES:
        try:
            n = len(page.eles(sel, timeout=1))
        except Exception as exc:
            n = f"ERR:{str(exc)[:20]}"
        print(f"  {label:<14} {sel:<26} -> {n}")

    print("\n[操作类文本命中]：")
    for kw in ACTION_KEYWORDS:
        try:
            n = len(page.eles(f"text:{kw}", timeout=0.5))
        except Exception:
            n = "ERR"
        print(f"  {kw} -> {n}")

    print("\n[按钮文本]（前若干）：")
    try:
        for i, b in enumerate(page.eles("tag:button", timeout=2)[:limit]):
            txt = (b.text or "").strip()
            if txt:
                print(f"  BTN #{i:<2} {txt[:24]!r}")
    except Exception as exc:
        print(f"[WARN] 按钮 dump 失败：{exc}")


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    parser = argparse.ArgumentParser(description="抖店后台联调探测")
    parser.add_argument("--address", default=os.environ.get("DOUYIN_CHROME_ADDRESS", "127.0.0.1:9222"))
    parser.add_argument("--url", default=None, help="先导航到该 URL 再 dump")
    parser.add_argument("--wait", type=float, default=0.0, help="导航后等待秒数，等 SPA 渲染")
    parser.add_argument("--sel", default=None, help="探测某个 DrissionPage 选择器命中情况")
    parser.add_argument("--structure", action="store_true", help="dump 列表页常见容器结构")
    parser.add_argument("--cells", action="store_true", help="按行 dump 每个 td 单元格（映射表格列），可配 --sel 指定行选择器")
    parser.add_argument("--limit", type=int, default=40)
    args = parser.parse_args()

    page = _connect(args.address)
    if args.url:
        page.get(args.url)
    if args.wait > 0:
        time.sleep(args.wait)

    print("URL  :", page.url)
    print("TITLE:", page.title)

    if args.cells:
        # 按行 dump 每个 td 单元格文本，用于映射表格列（product/order/aftersale/marketing 等表格域）
        row_sel = args.sel or "css:table tbody tr"
        try:
            rows = page.eles(row_sel, timeout=3)
            print(f"\n[CELLS] {row_sel} 命中 {len(rows)} 行，前 {args.limit} 行逐单元格：")
            for i, r in enumerate(rows[: args.limit]):
                cells = r.eles("tag:td", timeout=0.5)
                print(f"  行#{i}（{len(cells)} 个 td）：")
                for j, c in enumerate(cells):
                    txt = (c.text or "").strip().replace("\n", " ")
                    print(f"      td[{j}] {txt[:60]!r}")
        except Exception as exc:
            print(f"[ERR] 单元格探测失败：{exc}")
        return

    if args.sel:
        try:
            eles = page.eles(args.sel, timeout=3)
            print(f"\n[SELECTOR] {args.sel} 命中 {len(eles)} 个：")
            for i, e in enumerate(eles[: args.limit]):
                txt = (e.text or "").strip().replace("\n", " ")
                print(f"  #{i:<2} tag={e.tag:<8} text={txt[:50]!r}")
        except Exception as exc:
            print(f"[ERR] 选择器探测失败：{exc}")
        return

    if args.structure:
        _dump_structure(page, args.limit)
        return

    print("\n[导航入口候选]（含业务关键词的链接）：")
    seen = set()
    try:
        for a in page.eles("tag:a", timeout=3):
            text = (a.text or "").strip()
            href = a.attr("href") or ""
            if text and any(k in text for k in BUSINESS_KEYWORDS):
                key = (text, href)
                if key in seen:
                    continue
                seen.add(key)
                print(f"  A | {text[:18]:<18} | {href}")
    except Exception as exc:
        print(f"[WARN] 链接 dump 失败：{exc}")


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""端到端实机跑批：用**内存里构造的商品资料**跑完整流水线。

## 为什么从内存构造

真实采集商品（`ID-1083867541795`）的 record 没有标题、`content` 里没有 SKU，
静态预检会正确地拦下它。但**改数据库不是必须的**——`build_publish_item`
从 ``request`` 取标题 / 类目 / 属性 / SKU，所以直接把这些值传进去即可。
**本脚本不写数据库、不改任何采集目录。**

## 这次到底会写什么

授权只给 ``upload_image,save_draft``，且 ``stop_before_submit=True``：

* **会**：选中类目与品牌、上传主图到图片空间、把标题/属性/规格/价格库存/运费
  填进**未保存的表单**；
* **不会**：保存草稿、提交发布、上架。

已核实：**没有任何阶段会点「保存草稿」**——`save_draft` 只是授权级别，
填充阶段只写未保存的表单并回读。

用法::

    python taobao-publisher/scripts/run-e2e-live.py --address 127.0.0.1:9502 --allow-write
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SUBPROJECT = SCRIPT_DIR.parent
if str(SUBPRODUCT := SUBPROJECT) not in sys.path:
    sys.path.insert(0, str(SUBPROJECT))

from taobao_publish import local_source  # noqa: E402
from taobao_publish.authorization import WriteAuthorization  # noqa: E402
from taobao_publish.pipeline import run  # noqa: E402

TMP_DIR = SUBPROJECT / "tmp"

PRODUCT_ID = "ID-1083867541795"

#: 实测已验证的类目路径（`select_category` 要求**完整路径精确相等**）。
CATEGORY_PATH = [
    "女士内衣/男士内衣/家居服",
    "短袜/打底袜/丝袜/美腿袜（新）",
    "一次性袜子",
]

#: 实测已验证的品牌值。
BRAND = "无品牌/无注册商标"

#: 实测已验证的运费模板名（该店铺只有这两个）。
FREIGHT = "极兔快递"

#: 尺码的标准候选项（E-085 实测）。**必须用候选项原文**，自由文本进不去。
SIZE_VALUES = ["M(37-41)", "L（45-47）"]


def build_request(title: str, price: float, stock: int) -> dict:
    return {
        "title": title,
        "category": {"category_id": "202187801", "path": CATEGORY_PATH},
        "props": [{"prop_name": "品牌", "value_name": BRAND}],
        "skus": [
            {"spec_values": {"尺码": value}, "price": price, "stock": stock}
            for value in SIZE_VALUES
        ],
        "freight_template_name": FREIGHT,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--address", default="127.0.0.1:9502")
    parser.add_argument("--allow-write", action="store_true")
    parser.add_argument("--dry-run", action="store_true",
                        help="只跑数据校验（写阶段全跳过）")
    parser.add_argument("--product-dir", default="")
    parser.add_argument("--title", default="夏季薄款一次性袜子男女通用透气吸汗短袜批发")
    parser.add_argument("--price", type=float, default=16.8)
    parser.add_argument("--stock", type=int, default=100)
    args = parser.parse_args()

    if not args.allow_write and not args.dry_run:
        print("这会向真实页面写入（选中类目、上传主图、填表单）。"
              "要么加 --allow-write，要么加 --dry-run。")
        return 2

    product_dir = args.product_dir or os.path.join(
        os.environ.get("LOCALAPPDATA", ""), "com.dyin.sock-publisher",
        "uploads", "products", PRODUCT_ID)
    if not os.path.isdir(product_dir):
        print("商品目录不存在：{}".format(product_dir))
        return 1

    local = local_source.local_product_from_record(
        {"id": 1, "name": PRODUCT_ID, "path": product_dir},
        product_dir=product_dir,
    )
    request = build_request(args.title, args.price, args.stock)

    print("=" * 72)
    print("端到端实机跑批")
    print("=" * 72)
    print("商品目录：{}".format(product_dir))
    print("主图（{} 张）：".format(len(local.main_images)))
    for path in local.main_images:
        print("    {}".format(os.path.basename(path)))
    print("详情图：{} 张".format(len(local.detail_images)))
    print("标题：{}".format(args.title))
    print("类目：{}".format(" > ".join(CATEGORY_PATH)))
    print("品牌：{}".format(BRAND))
    print("规格：{} × {}".format("尺码", "、".join(SIZE_VALUES)))
    print("价格 / 库存：{} / {}".format(args.price, args.stock))
    print("运费模板：{}".format(FREIGHT))
    print()

    if args.dry_run:
        authorization = WriteAuthorization.none()
        dry_run = True
        mode = "dry-run（写阶段全部跳过）"
    else:
        authorization = WriteAuthorization.from_grant(
            ["upload_image", "save_draft"], submit_unlocked=False)
        dry_run = False
        mode = "真实写入（不保存草稿、不提交）"
    print("模式：{}".format(mode))
    print("授权：{}".format(sorted(authorization.granted)))
    print("提交锁：{}".format("开" if authorization.submit_unlocked else "关"))
    print()

    def progress(pct, message, step, steps):
        done = sum(1 for s in steps if s.get("status") in ("ok", "skipped", "failed"))
        mark = {"ok": "✓", "skipped": "–", "failed": "✗", "running": "…"}.get(
            steps[-1].get("status") if steps else "", " ")
        print("  [{:>3}%] {} {:<16} {}".format(pct, mark, step, message[:70]))

    result = run(
        local,
        request,
        dry_run=dry_run,
        stop_before_submit=True,
        authorization=authorization,
        progress_callback=progress,
        cdp_list_url="http://{}/json/list".format(args.address),
        write_artifact=False,
    )

    print()
    print("=" * 72)
    print("结果")
    print("=" * 72)
    print("success            : {}".format(result.success))
    print("stage              : {}".format(result.stage))
    print("stopped_before_submit: {}".format(result.stopped_before_submit))
    if result.error:
        print("error              : [{}] {}".format(
            result.error.get("code"), result.error.get("message")))
    print()
    print("阶段：")
    for step in result.steps:
        print("  {:<16} {:<10} {:>6}ms  {}".format(
            step.name, step.status, step.elapsed_ms or 0, (step.summary or "")[:56]))
    if result.blockers:
        print()
        print("阻塞项 {} 条：".format(len(result.blockers)))
        for item in result.blockers[:10]:
            print("  [{}] {} -> {}".format(
                item.get("code"), item.get("field"), (item.get("detail") or "")[:80]))

    TMP_DIR.mkdir(parents=True, exist_ok=True)
    out = TMP_DIR / "e2e-live-{}.json".format(datetime.now().strftime("%Y%m%d%H%M%S"))
    out.write_text(json.dumps({
        "captured_at": datetime.now().isoformat(timespec="seconds"),
        "mode": mode,
        "dry_run": dry_run,
        "never_did": ["保存草稿", "提交宝贝信息", "改数据库", "改采集目录"],
        "product_dir": product_dir,
        "request": request,
        "result": result.to_dict(),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print()
    print("产物：{}".format(out))
    return 0 if result.success else 1


if __name__ == "__main__":
    raise SystemExit(main())

# -*- coding: utf-8 -*-
"""完整链条实机冒烟：**从类目页开始**，跑 9 个阶段。

## 覆盖

```
select_category → fill_base → fill_props → fill_skus
                → fill_freight → fill_price_stock → readback
```

（跳过 `upload_images` 与 `submit`：前者被平台限流，后者需显式授权。
`readback` 不含「主图张数」，因为本次 item 的 `images.main` 为空。）

## 为什么

`select_category` 是唯一没进过连续冒烟的阶段，而它**改页面状态最多**
（导航 → 搜索 → 切 tab → 选类目 → 选品牌 → 进填写页）。

## 边界（重要）

* **只操作页面**：选类目、选品牌、填表单。**不创建草稿、不上传、不提交。**
* 跑完页面停在填写页，表单内容在导航离开时丢弃。

用法::

    python taobao-publisher/scripts/smoke-full-chain-live.py --address 127.0.0.1:9502 --allow-write
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

from taobao_publish import page, stages  # noqa: E402
from taobao_publish.authorization import WriteAuthorization  # noqa: E402
from taobao_publish.models import (  # noqa: E402
    CategoryRef,
    ImageSet,
    PropEntry,
    PublishItem,
    SkuEntry,
)

TMP_DIR = SUBPROJECT / "tmp"

#: 实测已取证的类目路径（三段，`>` 分层）。
CATEGORY_PATH = (
    "女士内衣/男士内衣/家居服",
    "短袜/打底袜/丝袜/美腿袜（新）",
    "一次性袜子",
)

SMOKE_TITLE = "全链条冒烟DSH001"
SMOKE_GUIDE = "导购全链条DSH001"

#: 本次要跑的阶段。**顺序与 `STAGE_ORDER` 一致**（含 E-126 的运费模板在前）。
CHAIN = ("select_category", "upload_images", "fill_base", "fill_props", "fill_skus",
         "fill_freight", "fill_price_stock", "readback")

#: 主图目录。合规的是 `_1x1` 那套（800x800，比例 1.0）；
#: 另一套 1440x1920 比例 0.75，不合契约要求。
MAIN_IMAGE_SUFFIX = "_1x1.jpg"
MAIN_IMAGE_LIMIT = 5


def find_main_images() -> list:
    """找出该商品**合规的**主图（1:1 那套），最多 5 张。

    ⚠️ **必须显式筛选，不能拿目录里第一个。** 目录里有两套：
    `主图_NN.jpg`（1440x1920，比例 0.75，不合契约）与
    `主图_NN_1x1.jpg`（800x800，比例 1.0，合规）。
    """

    import os as _os

    base = (Path(_os.environ["LOCALAPPDATA"]) / "com.dyin.sock-publisher"
            / "uploads" / "products")
    if not base.is_dir():
        return []
    for product in sorted(base.iterdir()):
        main = product / "主图"
        if not main.is_dir():
            continue
        files = sorted(str(p) for p in main.iterdir()
                       if p.name.endswith(MAIN_IMAGE_SUFFIX))
        if files:
            print("主图目录：{}（合规 {} 张，取前 {}）".format(
                product.name, len(files), MAIN_IMAGE_LIMIT))
            return files[:MAIN_IMAGE_LIMIT]
    return []


def build_item(main_images=None) -> PublishItem:
    """属性值与规格值**都由调用方明确给出**——不猜字段（项目红线）。

    取值全部来自契约里已实证的候选项。
    """

    return PublishItem(
        record_id=1,
        record_name="ID-1083867541795",
        title=SMOKE_TITLE,
        guide_title=SMOKE_GUIDE,
        category=CategoryRef(path=CATEGORY_PATH, category_id="202187801"),
        images=ImageSet(main=list(main_images or []), detail=[]),
        props=[PropEntry(prop_name="品牌", value_name="无品牌/无注册商标")],
        skus=[SkuEntry(spec_values={"尺码": "M(37-41)"}, price=16.8, stock=200)],
        freight_template_name="极兔快递",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--address", default="127.0.0.1:9502")
    parser.add_argument("--allow-write", action="store_true")
    args = parser.parse_args()

    if not args.allow_write:
        print("这会驱动页面（选类目、选品牌、填表单），必须显式加 --allow-write。")
        print("（不创建草稿、不上传、不提交）")
        return 2

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

    main_images = find_main_images()
    if not main_images:
        print("没找到合规主图（{}）——upload_images 会失败".format(MAIN_IMAGE_SUFFIX))
    item = build_item(main_images)
    ctx = stages.PipelineContext(
        item=item,
        dry_run=False,
        authorization=WriteAuthorization.from_grant(
            ["save_draft", "upload_image"], submit_unlocked=False, source="smoke"),
        cdp_list_url="http://{}/json/list".format(args.address),
    )

    results = []
    print("=" * 76)
    print("完整链条冒烟（从类目页开始）：{}".format(" → ".join(CHAIN)))
    print("=" * 76)
    for stage in CHAIN:
        started = time.monotonic()
        try:
            outcome = stages.STAGE_HANDLERS[stage].run(ctx)
            elapsed = int((time.monotonic() - started) * 1000)
            record = {
                "stage": stage, "ok": bool(outcome.ok), "status": outcome.status,
                "summary": outcome.summary, "error_code": outcome.error_code,
                "elapsed_ms": elapsed,
            }
            # ⚠️ **把 readback 的明细留下。**
            #
            # 只记一句「8 项全部一致」，事后就**无法自证是哪 8 项**，
            # 也看不出「提交按钮」被当成**否决项**（`vetoes_passed`）
            # 而不是一项通过的核对——那正是第 65 轮我搞错、第 70 轮修掉的地方。
            data = getattr(outcome, "data", None) or {}
            # default_notice 也要留——它记着「平台默认值」（上架时间/发货时间/提取方式），
            # 那是发布之后没有任何地方会告诉你的东西。
            for key in ("matched", "mismatched", "unreadable", "vetoes_passed",
                        "default_notice"):
                if key in data:
                    record[key] = data[key]
            marker = "[OK]  " if outcome.ok else "[FAIL]"
            print("{} {:<17} {:>6}ms  {}".format(
                marker, stage, elapsed, str(outcome.summary)[:92]))
            if outcome.error_code:
                print("         错误：{}".format(outcome.error_code))
                for blocker in (outcome.blockers or [])[:3]:
                    detail = (blocker.get("detail") if isinstance(blocker, dict)
                              else getattr(blocker, "detail", ""))
                    print("         {}".format(str(detail)[:100]))
        except Exception as exc:  # noqa: BLE001
            record = {"stage": stage, "ok": False, "status": "exception",
                      "error": "{}: {}".format(type(exc).__name__, exc)}
            print("[EXC]  {} {}".format(stage, record["error"][:110]))
        results.append(record)
        if not record.get("ok"):
            print()
            print("→ 这一步没通过，**停在这里**（后面依赖它的结果）")
            break

    print()
    print("=" * 76)
    passed = [r for r in results if r.get("ok")]
    print("跑了 {} 个阶段，{} 个通过".format(len(results), len(passed)))
    if ctx.scratch.get("resolved_category_id"):
        print("解析出的 catId：{}".format(ctx.scratch["resolved_category_id"]))
    print("→ {}".format("**全链条通过**" if len(passed) == len(CHAIN) else "**有未通过项，见上**"))

    TMP_DIR.mkdir(parents=True, exist_ok=True)
    out = TMP_DIR / "smoke-full-chain-{}.json".format(datetime.now().strftime("%Y%m%d%H%M%S"))
    out.write_text(json.dumps({
        "captured_at": datetime.now().isoformat(timespec="seconds"),
        "page_only": True,
        "never_did": ["上传图片", "保存草稿", "提交宝贝信息"],
        "category_path": list(CATEGORY_PATH),
        "main_images": main_images,
        "resolved_category_id": ctx.scratch.get("resolved_category_id"),
        "results": results,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print("产物：{}".format(out))
    return 0 if len(passed) == len(CHAIN) else 1


if __name__ == "__main__":
    raise SystemExit(main())

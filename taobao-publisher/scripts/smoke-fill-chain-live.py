# -*- coding: utf-8 -*-
"""连续页面冒烟：`fill_base` → `fill_props` → `fill_skus` → `fill_freight`
→ `fill_price_stock` → `readback`，用**当前代码**在真实页面上跑一遍。

## 为什么做这个

第 28 轮那次实机跑之后，改了很多：`readback` 扩到 7 项、导购标题、
`fill_freight` 挪到 `fill_price_stock` **之前**（E-126：选运费模板会重置价格库存）、
SKU 建行顺序修正。**这些都只跑过单阶段，没连起来跑过。**

## 边界（重要）

* **只写页面表单**——这 6 个阶段都不点「保存草稿」、不点「提交」
  （第 26 轮静态核验过：`SAVE_DRAFT_BUTTON_TEXT` 只被 `countButton()` 与定位注册表用到）。
* **不碰上传**——`upload_images` 不在本次序列里。
* 表单内容在导航离开时丢弃，但**跑完会把关键字段恢复原值**。

用法::

    python taobao-publisher/scripts/smoke-fill-chain-live.py --address 127.0.0.1:9502 --allow-write
"""

from __future__ import annotations

import argparse
import json
import os
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
    ImageSet,
    PropEntry,
    PublishItem,
    SkuEntry,
)

TMP_DIR = SUBPROJECT / "tmp"

#: 表单里要恢复原值的字段（跑之前先读，跑完写回）。
RESTORE_LABELS = ("宝贝标题", "导购标题")

SMOKE_TITLE = "冒烟链条DSH001"
SMOKE_GUIDE = "导购冒烟DSH001"

#: 本次要跑的阶段顺序。**与 `STAGE_ORDER` 一致**（含 E-126 的次序修正）。
CHAIN = ("fill_base", "fill_props", "fill_skus", "fill_freight",
         "fill_price_stock", "readback")


def build_item() -> PublishItem:
    """构造一个尽量贴近实机的商品。

    ⚠️ 属性值与规格值**必须由调用方明确给出**——不许从别处推断（项目红线：
    不猜字段）。这里用的是契约里已实证的取值。
    """

    return PublishItem(
        record_id=1,
        record_name="ID-1083867541795",
        title=SMOKE_TITLE,
        guide_title=SMOKE_GUIDE,
        images=ImageSet(main=[], detail=[]),
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
        print("这会写页面表单，必须显式加 --allow-write。")
        print("（不保存草稿、不提交、不上传；跑完恢复关键字段）")
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

    ws_url = target["webSocketDebuggerUrl"]

    # 先把弹层关掉——开着会让后续阶段找不到元素。
    with page.PageClient.connect(ws_url) as client:
        if page.read_media_popup(client).get("open"):
            page.close_media_popup(client)
            time.sleep(1.5)
        before_values = {}
        for label in RESTORE_LABELS:
            try:
                before_values[label] = page.read_text_field(client, label)
            except Exception as exc:  # noqa: BLE001
                before_values[label] = None
                print("读不到 {!r}：{}".format(label, exc))
    print("跑之前：{}".format(json.dumps(before_values, ensure_ascii=False)))
    print()

    item = build_item()
    # `fill_*` 都映射到 `save_draft`——**这不等于保存草稿**，
    # 只是「本次会改动草稿内容」的登记；真正的保存需要点按钮，没有阶段点它。
    ctx = stages.PipelineContext(
        item=item,
        dry_run=False,
        authorization=WriteAuthorization.from_grant(
            ["save_draft", "upload_image"], submit_unlocked=False, source="smoke"),
        cdp_list_url="http://{}/json/list".format(args.address),
    )

    results = []
    print("=" * 72)
    print("连续页面冒烟：{}".format(" → ".join(CHAIN)))
    print("=" * 72)
    for stage in CHAIN:
        started = time.monotonic()
        try:
            outcome = stages.STAGE_HANDLERS[stage].run(ctx)
            elapsed = int((time.monotonic() - started) * 1000)
            record = {
                "stage": stage,
                "ok": bool(outcome.ok),
                "status": outcome.status,
                "summary": outcome.summary,
                "error_code": outcome.error_code,
                "elapsed_ms": elapsed,
            }
            marker = "[OK]  " if outcome.ok else "[FAIL]"
            print("{} {:<18} {:>6}ms  {}".format(
                marker, stage, elapsed, str(outcome.summary)[:96]))
            if outcome.error_code:
                print("        错误：{}".format(outcome.error_code))
                for blocker in (outcome.blockers or [])[:3]:
                    print("        [{}] {}".format(
                        blocker.get("code") if isinstance(blocker, dict) else blocker.code,
                        str(blocker.get("detail") if isinstance(blocker, dict) else blocker.detail)[:90]))
        except Exception as exc:  # noqa: BLE001
            record = {"stage": stage, "ok": False, "status": "exception",
                      "error": "{}: {}".format(type(exc).__name__, exc)}
            print("[EXC] {} {}".format(stage, record["error"][:100]))
        results.append(record)
        if not record.get("ok"):
            print()
            print("→ 这一步没通过，**停在这里**（后面依赖它的结果）")
            break

    # 恢复关键字段
    restored = {}
    try:
        with page.PageClient.connect(ws_url) as client:
            for label, original in before_values.items():
                if original is None:
                    continue
                page.fill_text_field(client, label, original or "")
                restored[label] = page.read_text_field(client, label)
    except Exception as exc:  # noqa: BLE001
        print("恢复过程出错：{}: {}".format(type(exc).__name__, exc))

    print()
    print("=" * 72)
    passed = [r for r in results if r.get("ok")]
    print("跑了 {} 个阶段，{} 个通过".format(len(results), len(passed)))
    print("恢复：{}".format(json.dumps(restored, ensure_ascii=False)))
    print("→ {}".format("**全链条通过**" if len(passed) == len(CHAIN) else "**有未通过项，见上**"))

    TMP_DIR.mkdir(parents=True, exist_ok=True)
    out = TMP_DIR / "smoke-fill-chain-{}.json".format(datetime.now().strftime("%Y%m%d%H%M%S"))
    out.write_text(json.dumps({
        "captured_at": datetime.now().isoformat(timespec="seconds"),
        "wrote_page_only": True,
        "never_did": ["上传图片", "保存草稿", "提交宝贝信息"],
        "page_url": target.get("url"),
        "before_values": before_values,
        "restored": restored,
        "results": results,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print("产物：{}".format(out))
    return 0 if len(passed) == len(CHAIN) else 1


if __name__ == "__main__":
    raise SystemExit(main())

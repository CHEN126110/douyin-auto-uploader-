# -*- coding: utf-8 -*-
"""探针：**空规格值的 SKU 会怎么走**。

前端把 `spec_values` 默认成空串（`seedDraft` 里 `spec_values: ""`），
操作人可能**没填就发起发布**。要看这条路径：
1. `build_publish_item` 会不会报阻塞；
2. `_desired_specs()` 算出什么；
3. `fill_skus` 会做什么。

**纯离线，不连浏览器。**
"""

from __future__ import annotations

import json
import pathlib
import sys

SUBPROJECT = pathlib.Path(__file__).resolve().parents[1]
if str(SUBPROJECT) not in sys.path:
    sys.path.insert(0, str(SUBPROJECT))

from taobao_publish import stages  # noqa: E402
from taobao_publish.mapping import build_publish_item  # noqa: E402
from taobao_publish.models import ImageSet, LocalProduct, PublishItem  # noqa: E402


def run_case(label, skus):
    print("=" * 66)
    print("用例：{}".format(label))
    local = LocalProduct(record_id=1, record_name="ID-1", title="本地标题",
                         main_images=["a.jpg"], detail_images=[])
    out = build_publish_item(local, {"title": "标题", "skus": skus})
    print("  build_publish_item.ok = {}".format(out.ok))
    blockers = [b.to_dict() for b in out.blockers]
    print("  blockers ({}): {}".format(
        len(blockers), json.dumps(blockers, ensure_ascii=False)[:260]))
    item = out.item
    if item is None:
        print("  item = None")
        return
    print("  SKU 条数 = {}".format(len(item.skus or [])))
    for sku in (item.skus or []):
        print("     spec_values={!r} price={} stock={}".format(
            sku.spec_values, sku.price, sku.stock))

    # _desired_specs 算出什么
    try:
        desired = stages._desired_specs(item)
        print("  _desired_specs() = {}".format(json.dumps(desired, ensure_ascii=False)[:220]))
    except Exception as exc:  # noqa: BLE001
        print("  _desired_specs() 抛错: {}: {}".format(type(exc).__name__, exc))


run_case("两条 SKU 都是空 spec_values", [
    {"spec_values": {}, "price": 16.8, "stock": 100},
    {"spec_values": {}, "price": 16.8, "stock": 100},
])

run_case("一条空、一条正常", [
    {"spec_values": {}, "price": 16.8, "stock": 100},
    {"spec_values": {"尺码": "M(37-41)"}, "price": 16.8, "stock": 100},
])

run_case("两条 spec_values 完全相同", [
    {"spec_values": {"尺码": "M(37-41)"}, "price": 16.8, "stock": 100},
    {"spec_values": {"尺码": "M(37-41)"}, "price": 16.8, "stock": 100},
])

run_case("正常两条", [
    {"spec_values": {"尺码": "M(37-41)"}, "price": 16.8, "stock": 100},
    {"spec_values": {"尺码": "L（45-47）"}, "price": 16.8, "stock": 100},
])

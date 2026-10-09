# -*- coding: utf-8 -*-
"""跨边界核对：**界面发的字段** vs **Sidecar 接受的字段**。

## 为什么

上一轮（第 66 轮）的教训：「两处算同一件事、算法不一致」——
`desktop` 排除 `_1x1` 而 `local_source` 偏好 `_1x1`，**768 条测试全绿，缺陷照样活着**。

这一轮把同一把尺子用到**界面 ↔ Sidecar 这条边界**上：

* `TaobaoPublishPanel.vue` 的 `buildProductRequest()` 造出 `product`；
* `app.py` 的 `_taobao_product_request_payload()` 把它翻译成流水线的 `request`。

**两边字段集对不上**的后果是静默的：界面填了半天，Sidecar 看不懂就丢掉，
而流水线在**预检**才报「缺这个字段」——用户看不出是丢在哪一环。

## 判据

1. 界面造的每个键，Sidecar 都要认识；
2. Sidecar 认识的每个键，界面要么能造、要么**明确不需要**（例如 `category_id`
   是可选透传）。

**只读**：解析两边源码取字段名。
"""

from __future__ import annotations

import json
import pathlib
import re
import sys

SUB = pathlib.Path(__file__).resolve().parents[1]
REPO = SUB.parent
PANEL = REPO / "tauri-app" / "src" / "components" / "TaobaoPublishPanel.vue"
MAIN_VIEW = REPO / "tauri-app" / "src" / "views" / "ProductManager.vue"
APP = REPO / "tauri-app" / "python-sidecar" / "app.py"
TYPES = REPO / "tauri-app" / "src" / "types" / "index.ts"


def interface_type_fields() -> set:
    """从 `types/index.ts` 的 `TaobaoProductRequest` 取字段名。"""

    source = TYPES.read_text(encoding="utf-8")
    match = re.search(r"export interface TaobaoProductRequest \{(.*?)\n\}", source, re.S)
    if not match:
        return set()
    body = match.group(1)
    body = re.sub(r"/\*.*?\*/", "", body, flags=re.S)
    body = "\n".join(line for line in body.splitlines()
                     if not line.strip().startswith("//"))
    # ⚠️ **只取顶层键。**
    #
    # 朴素的 `^\s*(\w+)\??\s*:` 会把**嵌套**字段也算进来：
    # `skus?: Array<{ spec_values?: ...; price?: ...; stock?: ... }>`
    # 里的 `spec_values` / `price` / `stock` 都被当成了顶层。
    #
    # **会误报的检查器迟早被忽略**，所以先把 `<>` 与 `{}` 包起来的内容挖空。
    top_level = re.sub(r"<[^<>]*(?:<[^<>]*>[^<>]*)*>", "", body, flags=re.S)
    top_level = re.sub(r"\{[^{}]*\}", "", top_level, flags=re.S)
    return set(re.findall(r"^\s*(\w+)\??\s*:", top_level, re.M))


def ui_built_fields() -> set:
    """从 `buildProductRequest()` 里取它**实际会写进 product 的键**。"""

    source = PANEL.read_text(encoding="utf-8")
    match = re.search(r"function buildProductRequest\(\).*?\n\}", source, re.S)
    if not match:
        return set()
    body = match.group(0)
    body = re.sub(r"/\*.*?\*/", "", body, flags=re.S)
    keys = set(re.findall(r"product\.(\w+)\s*=", body))
    # 对象字面量里直接写的键：`const product: TaobaoProductRequest = { ... }`
    literal = re.search(r"const product[^=]*=\s*\{(.*?)\n\s*\};", body, re.S)
    if literal:
        block = "\n".join(line for line in literal.group(1).splitlines()
                          if not line.strip().startswith("//"))
        keys |= set(re.findall(r"^\s*(\w+)\s*:", block, re.M))
    # 主操作入口直接构造填写快照；独立旧面板仍可生成完整路径资料。
    main_source = MAIN_VIEW.read_text(encoding="utf-8")
    main_match = re.search(r"async function handlePublishByAccount\(\).*?\n\}", main_source, re.S)
    if main_match:
        main_literal = re.search(r"const product[^=]*=\s*\{(.*?)\n\s*\};", main_match.group(0), re.S)
        if main_literal:
            fields = re.findall(r"^(\s*)(\w+)\s*(?::|,)", main_literal.group(1), re.M)
            if fields:
                top_indent = min(len(indent) for indent, _key in fields)
                keys |= {key for indent, key in fields if len(indent) == top_indent}
    return keys


def sidecar_accepted_fields() -> set:
    """从 `_taobao_product_request_payload` 取它读的键。"""

    source = APP.read_text(encoding="utf-8")
    start = source.index("def _taobao_product_request_payload(")
    end = source.index("\ndef ", start + 10)
    body = source[start:end]
    body = "\n".join(line for line in body.splitlines()
                     if not line.strip().startswith("#"))
    # `for key in ("a", "b", "c")` 与 `product.get("x")`
    keys = set()
    for group in re.findall(r"for key in \(([^)]*)\)", body):
        keys |= set(re.findall(r'"(\w+)"', group))
    keys |= set(re.findall(r'product\.get\("(\w+)"\)', body))
    return keys


#: 界面**有意不写**的字段，每条都必须写明依据。
#:
#: ⚠️ **一个永远失败的检查器迟早会被忽略。** 所以每条例外要么在代码里能找到依据
#: （下面注释里引的原文），要么就该去修——不许因为「反正它一直报」就放宽。
INTENTIONALLY_UNSET = {
    # Sidecar 的 `_taobao_product_request_payload` 原文：
    #   `category_id` 原样传给 `category.category_id`（**可空，流水线会回读权威值）
    "category_id": (
        "可空。流水线在 `select_category` 里回读平台的权威 catId 并写进结果"
        "（实测回读到 202187801）；界面不提供反而避免了「界面猜的 id 与平台不一致」。"
    ),
}


def main() -> int:
    declared = interface_type_fields()
    built = ui_built_fields()
    accepted = sidecar_accepted_fields()

    print("=" * 74)
    print("跨边界核对：界面发的字段 vs Sidecar 接受的字段")
    print("=" * 74)
    print()
    print("  types 里声明的（TaobaoProductRequest）：{}".format(sorted(declared)))
    print("  界面实际会写的：                    {}".format(sorted(built)))
    print("  Sidecar 会读的：                    {}".format(sorted(accepted)))
    print()

    problems = []

    # 1) 界面写的，Sidecar 必须认识
    unknown = sorted(built - accepted)
    if unknown:
        problems.append("界面会写这些键，但 **Sidecar 不读**——会被静默丢掉：{}".format(unknown))

    # 2) 界面声明了却不写的
    never_built = sorted(declared - built - set(INTENTIONALLY_UNSET))
    if never_built:
        problems.append(
            "types 里声明了、但界面从没写过（可能是死字段）：{}".format(never_built))
    for name in sorted(declared - built):
        if name in INTENTIONALLY_UNSET:
            print("  · {:<14} 界面有意不写：{}".format(
                name, INTENTIONALLY_UNSET[name]))

    # 3) Sidecar 读了、但界面造不出来的
    ui_cannot = sorted(accepted - declared)
    if ui_cannot:
        problems.append("Sidecar 会读这些键，但界面造不出来：{}".format(ui_cannot))

    # **例外清单也会过期**：它列的字段若哪天界面开始写了，这条例外就该删。
    for name in sorted(INTENTIONALLY_UNSET):
        if name in built:
            problems.append(
                "例外清单过期：`{}` 界面已经开始写了，从 INTENTIONALLY_UNSET 里删掉它"
                .format(name))

    if not problems:
        print()
        print("  ✓ 三边一致（例外 {} 条，各有依据）".format(len(INTENTIONALLY_UNSET)))
        return 0

    for item in problems:
        print("  [!] {}".format(item))
    print()
    print("⚠️ 字段集对不上，后果是**静默的**：界面填了半天、Sidecar 看不懂就丢掉，")
    print("   而流水线在预检才报「缺这个字段」——用户看不出丢在哪一环。")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

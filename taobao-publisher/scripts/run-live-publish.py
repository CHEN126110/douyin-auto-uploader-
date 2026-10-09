# -*- coding: utf-8 -*-
"""真机跑一遍淘宝发布流水线：**默认只做只读 dry-run，写到提交前截停**。

## 与 CLI 的关系

CLI 只有 ``dry-run``（永远 ``dry_run=True``），而这次要验证的是
「协议整批上传 → 直接填好图位 → 继续后面阶段」这条**真实写路径**。
所以这里是一个独立入口，但它调用的仍是生产函数 ``pipeline.run``，
不另写一份流水线。

## 红线

* 默认 ``--dry-run``：写阶段全部跳过，只读页面与本地数据；
* 要真写必须**同时**满足：``TAOBAO_UPLOAD_ALLOW_WRITE=upload_image,save_draft``
  **且**命令行给 ``--i-understand-this-writes``；
* **永远** ``stop_before_submit=True``，并且这一项在脚本里写死、不接受命令行覆盖——
  提交不可撤销，不属于「顺手试一下」的范围。

## 用法

```powershell
# 1) 只读彩排（不发任何写请求）
python taobao-publisher/scripts/run-live-publish.py --record-id 1 --sku-stock 100

# 2) 真跑（写到提交前截停）
$env:TAOBAO_UPLOAD_ALLOW_WRITE = 'upload_image,save_draft'
$env:TAOBAO_MEDIA_ROUTE = 'protocol'
python taobao-publisher/scripts/run-live-publish.py --record-id 1 --sku-stock 100 --i-understand-this-writes
```
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _path in (str(_REPO_ROOT / "taobao-publisher"), str(_REPO_ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from taobao_publish.authorization import WriteAuthorization  # noqa: E402
from taobao_publish.constants import (  # noqa: E402
    ENV_ALLOW_WRITE,
    WRITE_SAVE_DRAFT,
    WRITE_UPLOAD_IMAGE,
)
from taobao_publish.local_source import local_product_from_record  # noqa: E402
from taobao_publish.pipeline import run  # noqa: E402
from taobao_publish.protocol_media import ENV_MEDIA_ROUTE, media_route_from_environment  # noqa: E402

#: 淘宝「颜色分类」是这类袜子商品的销售属性名（本地 SKU 名就是它的取值）。
#: 换类目要跟着换——**不猜**，由调用方显式给。
DEFAULT_SPEC_NAME = "颜色分类"


def default_db_path() -> Path:
    local = os.environ.get("LOCALAPPDATA", "")
    candidates = [
        Path(local) / "com.dyin.sock-publisher" / "sqlite.db",
        _REPO_ROOT / "sqlite.db",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise SystemExit("找不到 sqlite.db；请用 --db 指定")


def read_record(db: Path, record_id: int) -> Dict[str, Any]:
    connection = sqlite3.connect(str(db))
    connection.row_factory = sqlite3.Row
    try:
        row = connection.execute("select * from record where id = ?", (record_id,)).fetchone()
    finally:
        connection.close()
    if row is None:
        raise SystemExit(f"record 表里没有 id={record_id}")
    return dict(row)


def build_request(
    row: Dict[str, Any],
    *,
    spec_name: str,
    stock: int,
    title: str,
    freight: str,
    category_path: str = "",
    category_id: str = "",
) -> Dict[str, Any]:
    items = json.loads(row.get("content") or "[]")
    skus: List[Dict[str, Any]] = []
    for item in items:
        name = str(item.get("name") or "").strip()
        price = item.get("price")
        if not name or price is None:
            raise SystemExit(f"SKU 条目缺少名称或价格：{item!r}")
        skus.append({
            "spec_values": {spec_name: name},
            "price": float(price),
            "stock": int(stock),
            "image_path": str(item.get("path") or ""),
        })
    if not skus:
        raise SystemExit("本地没有 SKU 条目，无法构造请求（不允许默认值）")
    request: Dict[str, Any] = {
        "record_id": int(row["id"]),
        "record_name": str(row.get("name") or ""),
        "title": title or str(row.get("title") or ""),
        "skus": skus,
    }
    # 类目路径**必须由调用方从平台候选里读出来**，不在这里猜。
    # 平台用 ``>`` 分隔层级；层级名内部可能自带 ``/``（如「短袜/打底袜/丝袜/美腿袜（新）」）。
    if category_path.strip():
        parts = [part.strip() for part in category_path.split(">") if part.strip()]
        if not parts:
            raise SystemExit("--category-path 解析后为空")
        category: Dict[str, Any] = {"path": parts}
        if category_id.strip():
            category["category_id"] = category_id.strip()
        request["category"] = category
    template = freight or str(row.get("shipping_template") or "").strip()
    if template:
        request["freight_template_name"] = template
    return request


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="真机跑淘宝发布流水线（写到提交前截停）")
    parser.add_argument("--record-id", type=int, required=True)
    parser.add_argument("--db", default="", help="sqlite.db 路径（默认取运行目录里的那份）")
    parser.add_argument("--sku-stock", type=int, required=True,
                        help="总库存：本地没有这个字段，必须显式给")
    parser.add_argument("--spec-name", default=DEFAULT_SPEC_NAME, help="销售属性名")
    parser.add_argument("--title", default="", help="覆盖标题")
    parser.add_argument("--freight", default="", help="运费模板名（默认取 record.shipping_template）")
    parser.add_argument("--category-path", default="",
                        help="完整类目路径，层级用 > 分隔（从平台候选里读，不要猜）")
    parser.add_argument("--category-id", default="", help="类目 ID（可选；不给就只按路径选）")
    parser.add_argument("--start-from", default="",
                        help="从某个阶段开始跑（例如 upload_images）；默认从头。"
                             "已经走到填写页时用它接着跑，不回退页面")
    parser.add_argument("--cdp-address", default="127.0.0.1:9334", help="调试浏览器地址")
    parser.add_argument("--dry-run", action="store_true", default=False,
                        help="只做只读彩排（写阶段全部跳过）")
    parser.add_argument("--i-understand-this-writes", action="store_true",
                        help="确认这是一次真实写入（会改平台状态，但仍在提交前截停）")
    parser.add_argument("--max-blockers", type=int, default=15)
    parser.add_argument("--json", action="store_true", help="以 JSON 输出完整结果")
    parser.add_argument("--out", default="", help="把结果 JSON 写到该路径")
    arguments = parser.parse_args(argv)

    # --- 授权判定：默认零写入 ---
    authorization = WriteAuthorization.from_environment()
    live = not arguments.dry_run
    if live:
        missing = [op for op in (WRITE_UPLOAD_IMAGE, WRITE_SAVE_DRAFT)
                   if not authorization.is_granted(op)]
        if missing or not arguments.i_understand_this_writes:
            sys.stderr.write(
                "[WRITE_NOT_AUTHORIZED] 真跑需要同时满足：\n"
                f"  1) 环境变量 {ENV_ALLOW_WRITE} 含 {WRITE_UPLOAD_IMAGE},{WRITE_SAVE_DRAFT}\n"
                "     （当前白名单：" + authorization.describe_granted() + "）\n"
                "  2) 命令行加 --i-understand-this-writes\n"
                "本次未发送任何请求。\n"
            )
            return 2

    db = Path(arguments.db) if arguments.db else default_db_path()
    row = read_record(db, arguments.record_id)
    local = local_product_from_record(row, product_dir=str(row.get("path") or ""))
    request = build_request(row, spec_name=arguments.spec_name, stock=arguments.sku_stock,
                            title=arguments.title, freight=arguments.freight,
                            category_path=arguments.category_path, category_id=arguments.category_id)

    route = media_route_from_environment()
    cdp_list_url = "http://{}/json/list".format(arguments.cdp_address.strip())

    header = {
        "record_id": local.record_id,
        "record_name": local.record_name,
        "main_images": len(local.main_images),
        "sku_images": len(local.images.sku) if hasattr(local, "images") else None,
        "detail_images": len(local.detail_images),
        "sku_count": len(request["skus"]),
        "stock_each": arguments.sku_stock,
        "media_route": route,
        "dry_run": arguments.dry_run,
        "writes": live,
        "stop_before_submit": True,
    }
    if not arguments.json:
        sys.stdout.write("=" * 72 + "\n")
        sys.stdout.write(f"record {local.record_id}（{local.record_name}）  素材路线={route}\n")
        sys.stdout.write(
            f"主图 {header['main_images']} 张 / 详情 {header['detail_images']} 张 / "
            f"SKU {header['sku_count']} 行（每行库存 {arguments.sku_stock}）\n"
        )
        sys.stdout.write(("只读彩排（写阶段跳过）" if arguments.dry_run else "**真写**（提交前截停）") + "\n")
        sys.stdout.write("=" * 72 + "\n")

    def progress(message: str) -> None:
        if not arguments.json:
            sys.stdout.write(f"  … {message}\n")
            sys.stdout.flush()

    result = run(
        local,
        request,
        progress_callback=progress,
        dry_run=arguments.dry_run,
        stop_before_submit=True,          # 写死：提交不可撤销
        authorization=authorization,
        cdp_list_url=cdp_list_url,
        start_from=arguments.start_from.strip(),
    )

    payload = result.to_dict()
    payload["header"] = header
    text = json.dumps(payload, ensure_ascii=False, indent=2)

    if arguments.json:
        sys.stdout.write(text + "\n")
    else:
        sys.stdout.write("\n")
        sys.stdout.write(f"结果：{'成功' if result.success else '失败'}\n")
        sys.stdout.write(f"停在阶段：{result.stage}\n")
        for step in result.steps:
            marker = {"ok": "[OK]  ", "failed": "[FAIL]", "skipped": "[SKIP]", "running": "[..]  "}.get(
                step.status, "[?]   ")
            sys.stdout.write(f"{marker} {step.label:<16} {step.elapsed_ms:>6}ms  {step.summary}\n")
        if result.error:
            sys.stdout.write(f"\n错误：{result.error.get('code')} — {result.error.get('message')}\n")
        if result.blockers:
            sys.stdout.write(f"\n阻塞项（{len(result.blockers)}）：\n")
            for blocker in result.blockers[: arguments.max_blockers]:
                sys.stdout.write(
                    f"  [{blocker.get('code')}] {blocker.get('field') or '-'}: {blocker.get('detail')}\n"
                )
        scratch = payload.get("data", {}).get("scratch") or {}
        media = scratch.get("prepared_media") or {}
        if media:
            sys.stdout.write("\n素材回执（SKU/详情）：\n")
            for role, entries in media.items():
                sys.stdout.write(f"  {role}: {len(entries)} 张\n")

    if arguments.out:
        Path(arguments.out).parent.mkdir(parents=True, exist_ok=True)
        Path(arguments.out).write_text(text, encoding="utf-8")
        sys.stdout.write(f"[已写入产物] {arguments.out}\n")

    return 0 if result.success else 1


if __name__ == "__main__":
    raise SystemExit(main())

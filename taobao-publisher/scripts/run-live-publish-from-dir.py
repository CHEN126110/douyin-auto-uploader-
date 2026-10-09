# -*- coding: utf-8 -*-
"""真机跑流水线：**用现成的采集目录构造测试商品**，不读也不写数据库。

为什么单独一个入口：`run-live-publish.py` 从 `sqlite.db` 读记录，而当前工作区里那条
记录的采集目录已经不在本地了。为了能继续验证「协议整批传图 → 选图 → 继续填」，
这里直接按目录构造 ``LocalProduct``——**完全不碰用户的数据库**。

```powershell
$env:TAOBAO_UPLOAD_ALLOW_WRITE = 'upload_image,save_draft'
$env:TAOBAO_MEDIA_ROUTE = 'protocol'
python taobao-publisher/scripts/run-live-publish-from-dir.py `
  --dir "uploads\capture\b97253b4" --record-id 9900937 --sku-stock 100 `
  --category-path "女士内衣/男士内衣/家居服>短袜/打底袜/丝袜/美腿袜（新）>中筒袜" `
  --start-from upload_images --i-understand-this-writes
```
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _path in (str(_REPO_ROOT / "taobao-publisher"), str(_REPO_ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from taobao_publish.authorization import WriteAuthorization  # noqa: E402
from taobao_publish.constants import (  # noqa: E402
    ENV_ALLOW_WRITE, WRITE_SAVE_DRAFT, WRITE_UPLOAD_IMAGE,
)
from taobao_publish.models import LocalProduct, LocalSku  # noqa: E402
from taobao_publish.pipeline import run  # noqa: E402
from taobao_publish.protocol_media import media_route_from_environment  # noqa: E402

IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".bmp", ".webp")


def collect(directory: Path, names: tuple) -> List[str]:
    for name in names:
        folder = directory / name
        if folder.is_dir():
            files = sorted(
                (item for item in folder.iterdir()
                 if item.is_file() and item.suffix.lower() in IMAGE_SUFFIXES),
                key=lambda item: item.name,
            )
            if files:
                return [str(item) for item in files]
    return []


def build_product(directory: Path, record_id: int, title: str, freight: str,
                  stock: int, price: float, spec_name: str) -> LocalProduct:
    main = collect(directory, ("主图", "主图/800", "主图/750"))
    detail = collect(directory, ("详情页", "详情图片"))
    sku_images = collect(directory, ("SKU",))
    if not main:
        raise SystemExit(f"目录里没有主图：{directory}")
    # SKU 行只取前 5 个，避免一次建 28 行把页面拖慢（验证的是图片链路，不是 SKU 规模）
    skus: List[LocalSku] = []
    for index, path in enumerate(sku_images[:5], 1):
        name = Path(path).stem
        skus.append(LocalSku(name=name, path=path, price=price,
                             dir_name="SKU", file_name=Path(path).name))
    if not skus:
        skus = [LocalSku(name="默认", path=main[0], price=price, dir_name="主图",
                         file_name=Path(main[0]).name)]
    return LocalProduct(
        record_id=record_id,
        record_name=directory.name,
        title=title,
        product_dir=str(directory),
        skus=skus,
        main_images=main,
        detail_images=detail,
        shipping_template=freight,
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="用现成目录跑真机流水线（不碰数据库）")
    parser.add_argument("--dir", required=True, help="采集目录")
    parser.add_argument("--record-id", type=int, required=True, help="素材命名用的商品编号")
    parser.add_argument("--title", default="", help="标题（不给就用目录名）")
    parser.add_argument("--freight", default="", help="运费模板名（不给就不填）")
    parser.add_argument("--sku-stock", type=int, required=True)
    parser.add_argument("--sku-price", type=float, default=5.9)
    parser.add_argument("--spec-name", default="颜色分类")
    parser.add_argument("--sku-mode", default="standard", choices=("standard", "custom"),
                        help="规格模式：standard=标准属性模式（图片入口未取证，带 SKU 图会被拒）；"
                             "custom=自定义规格（SKU 图片入槽走这条）")
    parser.add_argument("--no-sku-images", action="store_true",
                        help="SKU 行不带 image_path（SKU 图片绑定控件尚未确认结构时用它把链路跑下去）")
    parser.add_argument("--category-path", default="")
    parser.add_argument("--category-id", default="")
    parser.add_argument("--start-from", default="upload_images")
    parser.add_argument("--skip-stages", default="",
                        help="逗号分隔、明确要跳过的阶段（例如只验证详情图时跳过 fill_skus）")
    parser.add_argument("--listing-mode", default="", choices=("", "立刻上架", "定时上架", "放入仓库"),
                        help="上架方式；留空=放入仓库（**默认进仓库，不直接上架**）")
    parser.add_argument("--save-draft", action="store_true",
                        help="回读通过后**保存草稿**（默认不保存，一个动作都不做）")
    parser.add_argument("--cdp-address", default="127.0.0.1:9334")
    parser.add_argument("--dry-run", action="store_true", default=False)
    parser.add_argument("--i-understand-this-writes", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--out", default="")
    arguments = parser.parse_args(argv)

    authorization = WriteAuthorization.from_environment()
    if not arguments.dry_run:
        missing = [op for op in (WRITE_UPLOAD_IMAGE, WRITE_SAVE_DRAFT)
                   if not authorization.is_granted(op)]
        if missing or not arguments.i_understand_this_writes:
            sys.stderr.write(
                "[WRITE_NOT_AUTHORIZED] 真跑需要 " + ENV_ALLOW_WRITE +
                " 含 upload_image,save_draft，且加 --i-understand-this-writes\n"
            )
            return 2

    directory = Path(arguments.dir)
    if not directory.is_dir():
        return _die(f"目录不存在：{directory}", 2)
    product = build_product(directory, arguments.record_id,
                            arguments.title or directory.name,
                            arguments.freight, arguments.sku_stock,
                            arguments.sku_price, arguments.spec_name)

    request: Dict[str, Any] = {
        "record_id": product.record_id,
        "record_name": product.record_name,
        "title": product.title,
        "sku_mode": arguments.sku_mode,
        "skus": [
            dict(
                {"spec_values": {arguments.spec_name: sku.name}, "price": sku.price,
                 "stock": arguments.sku_stock},
                **({} if arguments.no_sku_images else {"image_path": sku.path}),
            )
            for sku in product.skus
        ],
    }
    if arguments.freight:
        request["freight_template_name"] = arguments.freight
    if arguments.category_path.strip():
        request["category"] = {
            "path": [part.strip() for part in arguments.category_path.split(">") if part.strip()]
        }
        if arguments.category_id.strip():
            request["category"]["category_id"] = arguments.category_id.strip()

    route = media_route_from_environment()
    header = {
        "dir": str(directory),
        "record_id": product.record_id,
        "main": len(product.main_images), "detail": len(product.detail_images),
        "skus": len(product.skus), "media_route": route,
        "dry_run": arguments.dry_run, "start_from": arguments.start_from,
    }
    if not arguments.json:
        sys.stdout.write("=" * 72 + "\n")
        sys.stdout.write(f"目录 {directory.name}  素材路线={route}  从 {arguments.start_from} 开始\n")
        sys.stdout.write(f"主图 {len(product.main_images)} / 详情 {len(product.detail_images)} / "
                         f"SKU {len(product.skus)} 行（每行库存 {arguments.sku_stock}）\n")
        sys.stdout.write(("只读彩排" if arguments.dry_run else "**真写**（提交前截停）") + "\n")
        sys.stdout.write("=" * 72 + "\n")

    def progress(message: str) -> None:
        if not arguments.json:
            sys.stdout.write(f"  … {message}\n")
            sys.stdout.flush()

    result = run(
        product, request, progress_callback=progress,
        dry_run=arguments.dry_run, stop_before_submit=True,
        authorization=authorization,
        cdp_list_url="http://{}/json/list".format(arguments.cdp_address.strip()),
        start_from=arguments.start_from.strip(),
        skip_stages=[part.strip() for part in arguments.skip_stages.split(",") if part.strip()],
        listing_mode=arguments.listing_mode.strip(),
        save_draft=arguments.save_draft,
    )

    payload = result.to_dict()
    payload["header"] = header
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if arguments.json:
        sys.stdout.write(text + "\n")
    else:
        sys.stdout.write("\n")
        sys.stdout.write(f"结果：{'成功' if result.success else '失败'}    停在：{result.stage}\n")
        for step in result.steps:
            marker = {"ok": "[OK]  ", "failed": "[FAIL]", "skipped": "[SKIP]"}.get(step.status, "[?]   ")
            sys.stdout.write(f"{marker} {step.label:<16} {step.elapsed_ms:>7}ms  {step.summary}\n")
        if result.error:
            sys.stdout.write(f"\n错误：{result.error.get('code')} — {result.error.get('message')}\n")
        for blocker in result.blockers[:12]:
            sys.stdout.write(f"  [{blocker.get('code')}] {blocker.get('field') or '-'}: "
                             f"{str(blocker.get('detail'))[:200]}\n")
    if arguments.out:
        Path(arguments.out).parent.mkdir(parents=True, exist_ok=True)
        Path(arguments.out).write_text(text, encoding="utf-8")
        sys.stdout.write(f"[已写入产物] {arguments.out}\n")
    return 0 if result.success else 1


def _die(message: str, code: int = 2) -> int:
    sys.stderr.write(message.rstrip() + "\n")
    return code


if __name__ == "__main__":
    raise SystemExit(main())

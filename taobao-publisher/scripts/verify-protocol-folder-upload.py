# -*- coding: utf-8 -*-
"""真机验证：**生产路径的协议上传钩子**整批把商品文件夹送进图片空间。

它调用的就是 `stages._protocol_upload_hook(...)` 返回的那个函数——
发布流水线在 `TAOBAO_MEDIA_ROUTE=protocol` 时用的**同一个**实现，
不是另写一份探针。

**这是写操作**：会在淘宝图片空间里真实新增图片。需要显式授权。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(_ROOT / "taobao-publisher"), str(_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from taobao_publish.authorization import WriteAuthorization  # noqa: E402
from taobao_publish.constants import WRITE_UPLOAD_IMAGE  # noqa: E402
from taobao_publish.form_adapters import media_file_identity  # noqa: E402


def collect(directory: Path) -> list:
    images = [
        item for item in sorted(directory.rglob("*"))
        if item.is_file() and item.suffix.lower() in (".jpg", ".jpeg", ".png", ".bmp")
    ]
    return images


def main() -> int:
    parser = argparse.ArgumentParser(description="真机验证协议上传钩子（写操作）")
    parser.add_argument("--dir", required=True, help="商品采集目录")
    parser.add_argument("--record-id", type=int, required=True)
    parser.add_argument("--role", default="main", choices=("main", "sku", "detail"))
    parser.add_argument("--limit", type=int, default=6, help="最多传几张（控制影响面）")
    parser.add_argument("--i-understand-this-writes", action="store_true")
    parser.add_argument("--out", default="")
    arguments = parser.parse_args()

    authorization = WriteAuthorization.from_environment()
    if not authorization.is_granted(WRITE_UPLOAD_IMAGE) or not arguments.i_understand_this_writes:
        sys.stderr.write(
            "[WRITE_NOT_AUTHORIZED] 需要 TAOBAO_UPLOAD_ALLOW_WRITE 含 upload_image "
            "且显式 --i-understand-this-writes。本次未发送任何请求。\n"
        )
        return 2

    directory = Path(arguments.dir)
    if not directory.is_dir():
        sys.stderr.write(f"目录不存在：{directory}\n")
        return 2
    images = collect(directory)[: max(1, arguments.limit)]
    if not images:
        sys.stderr.write("目录下没有图片\n")
        return 2

    # 身份用生产同款实现（文件名里带内容摘要，避免与历史同名素材混淆）
    batch = []
    for index, path in enumerate(images, 1):
        identity = media_file_identity(
            str(path), arguments.record_id, arguments.role,
            slot=index if arguments.role == "main" else None,
        )
        if path.stat().st_size > 3 * 1024 * 1024:
            sys.stderr.write(f"跳过超过 3MB 的图：{path.name}\n")
            continue
        batch.append(identity)
    if not batch:
        sys.stderr.write("没有可上传的图片（可能都超过 3MB）\n")
        return 2

    os.environ["TAOBAO_MEDIA_ROUTE"] = "protocol"
    from taobao_publish import stages

    class _Ctx:
        pass

    ctx = _Ctx()
    ctx.authorization = authorization
    ctx.cdp_list_url = "http://127.0.0.1:9334/json/list"
    ctx.progress = None
    # `report_media_activity` 会读写这个字典（流水线里由 PipelineContext 提供）
    ctx.scratch = {}

    hook = stages._protocol_upload_hook(ctx)
    if hook is None:
        sys.stderr.write("协议钩子没有生效（TAOBAO_MEDIA_ROUTE 没被识别？）\n")
        return 2

    receipts = hook(batch)
    payload = {
        "dir": str(directory),
        "batch_name": {
            "count": len(batch),
            "sample": [entry["name"] for entry in batch[:2]],
        },
        "receipt_count": len(receipts),
        "receipt_sample": [
            {"name": name, "url": value.get("url", ""), "picture_id": value.get("picture_id", "")}
            for name, value in list(receipts.items())[:3]
        ],
        "all_https": all(str(value.get("url", "")).startswith("https://") for value in receipts.values()),
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        pass
    sys.stdout.write(text + "\n")
    if arguments.out:
        Path(arguments.out).parent.mkdir(parents=True, exist_ok=True)
        Path(arguments.out).write_text(text, encoding="utf-8")
        sys.stdout.write(f"[已写入产物] {arguments.out}\n")
    return 0 if len(receipts) == len(batch) else 1


if __name__ == "__main__":
    raise SystemExit(main())

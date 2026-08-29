from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

SCRIPT_PATH = Path(__file__).resolve()
PYTHON_SIDECAR_ROOT = SCRIPT_PATH.parents[2]
REPO_ROOT = SCRIPT_PATH.parents[4]
for path in (REPO_ROOT, PYTHON_SIDECAR_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from protocol_publish.dry_run import (  # noqa: E402
    ProtocolDryRunError,
    build_protocol_dry_run,
    merge_freight_probe_summary,
    merge_runtime_probe_summary,
)
from src.orm import Record  # noqa: E402


def _read_json(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8-sig") as fp:
        payload = json.load(fp)
    if not isinstance(payload, dict):
        raise ValueError(f"JSON 文件必须是对象：{path}")
    return payload


def _record_to_dict(record: Record) -> dict[str, Any]:
    return {
        "id": record.id,
        "name": record.name,
        "path": record.path,
        "type": record.type,
        "status": record.status,
        "repo": record.repo,
        "title": record.title,
        "clazz": record.clazz,
        "remark": record.remark,
        "content": record.content,
        "shipping_template": record.shipping_template,
        "update_time": record.update_time.isoformat() if record.update_time else None,
        "publish_time": record.publish_time.isoformat() if record.publish_time else None,
    }


def _load_record(record_id: int | None) -> dict[str, Any]:
    if record_id is not None:
        record = Record.get_or_none(Record.id == record_id)
        if record is None:
            raise ValueError(f"未找到商品记录：id={record_id}")
        return _record_to_dict(record)

    record = Record.select().order_by(Record.update_time.desc()).first()
    if record is None:
        raise ValueError("本地商品记录为空，无法生成 dry-run")
    return _record_to_dict(record)


def main() -> int:
    parser = argparse.ArgumentParser(description="从已采集商品记录生成协议化上传 dry-run 模型，不调用提交接口。")
    parser.add_argument("--schema", required=True, help="fxg-schema-probe 输出 JSON 路径")
    parser.add_argument("--runtime", default="", help="可选，fxg-runtime-options-probe 输出 JSON 路径")
    parser.add_argument("--freight", default="", help="可选，fxg-freight-probe 输出 JSON 路径")
    parser.add_argument("--record-id", type=int, default=None, help="可选，指定本地 Record.id；不传则使用最近更新记录")
    parser.add_argument("--assets", default="", help="可选，素材资产 JSON 路径")
    parser.add_argument("--output", default="", help="可选，输出 JSON 路径")
    parser.add_argument("--tube-height", default="", help="可选，显式筒高值，例如 长筒袜")
    parser.add_argument("--brand", default="", help="兼容旧命令；当前安全策略会忽略该值并统一使用 无品牌")
    parser.add_argument("--gender", default="", help="可选，显式适用性别，例如 女/男/通用")
    parser.add_argument("--thickness", default="", help="可选，显式厚度值，例如 薄款/厚款/常规款")
    args = parser.parse_args()

    schema_summary = _read_json(args.schema)
    runtime_probe = _read_json(args.runtime) if args.runtime else None
    schema_summary = merge_runtime_probe_summary(schema_summary, runtime_probe)
    freight_probe = _read_json(args.freight) if args.freight else None
    schema_summary = merge_freight_probe_summary(schema_summary, freight_probe)
    record = _load_record(args.record_id)
    assets = _read_json(args.assets) if args.assets else None

    try:
        dry_run = build_protocol_dry_run(
            schema_summary=schema_summary,
            record=record,
            assets=assets,
            tube_height_value=args.tube_height,
            brand_value=args.brand,
            gender_value=args.gender,
            thickness_value=args.thickness,
        )
    except ProtocolDryRunError as exc:
        print(f"dry-run 生成失败：{exc}", file=sys.stderr)
        return 2

    output_text = json.dumps(dry_run, ensure_ascii=False, indent=2)
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(output_text + "\n", encoding="utf-8")
    else:
        print(output_text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

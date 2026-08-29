from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve()
PYTHON_SIDECAR_ROOT = SCRIPT_PATH.parents[2]
REPO_ROOT = SCRIPT_PATH.parents[4]
for path in (REPO_ROOT, PYTHON_SIDECAR_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from protocol_publish.dry_run import build_protocol_dry_run, merge_freight_probe_summary, merge_runtime_probe_summary  # noqa: E402


def _read_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8-sig") as fp:
        payload = json.load(fp)
    if not isinstance(payload, dict):
        raise ValueError(f"JSON 文件必须是对象：{path}")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="生成协议化上传 dry-run 模型，不调用提交接口。")
    parser.add_argument("--schema", required=True, help="fxg-schema-probe 输出 JSON 路径")
    parser.add_argument("--runtime", default="", help="可选，fxg-runtime-options-probe 输出 JSON 路径")
    parser.add_argument("--freight", default="", help="可选，fxg-freight-probe 输出 JSON 路径")
    parser.add_argument("--record", required=True, help="商品记录 JSON 路径")
    parser.add_argument("--assets", default="", help="可选，素材资产 JSON 路径")
    parser.add_argument("--request-defaults", default="", help="可选，真实 addWithSchema 请求默认值 JSON 路径")
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
    record = _read_json(args.record)
    assets = _read_json(args.assets) if args.assets else None
    request_defaults = _read_json(args.request_defaults) if args.request_defaults else None
    dry_run = build_protocol_dry_run(
        schema_summary=schema_summary,
        record=record,
        assets=assets,
        request_defaults=request_defaults,
        tube_height_value=args.tube_height,
        brand_value=args.brand,
        gender_value=args.gender,
        thickness_value=args.thickness,
    )

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

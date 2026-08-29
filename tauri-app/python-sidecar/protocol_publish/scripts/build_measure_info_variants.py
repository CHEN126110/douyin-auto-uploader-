from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from protocol_publish.measure_info_variants import build_measure_info_variants


def _read_json(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8-sig") as fp:
        payload = json.load(fp)
    if not isinstance(payload, dict):
        raise ValueError(f"JSON 文件必须是对象：{path}")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="从 deep capture 生成 785.measure_info 的离线变体样本，不发送请求。")
    parser.add_argument("--capture", required=True, help="deep addWithSchema capture JSON 路径")
    parser.add_argument("--output", default="", help="可选，输出 JSON 路径")
    args = parser.parse_args()

    capture = _read_json(args.capture)
    result = build_measure_info_variants(capture)
    output_text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(output_text + "\n", encoding="utf-8")
    else:
        print(output_text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

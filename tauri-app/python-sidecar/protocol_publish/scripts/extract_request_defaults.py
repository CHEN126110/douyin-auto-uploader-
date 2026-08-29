from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


DEFAULT_KEYS = (
    "delivery_delay_day",
    "reduce_type",
    "reference_price_enable",
    "short_product_name",
)


def _read_json(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8-sig") as fp:
        payload = json.load(fp)
    if not isinstance(payload, dict):
        raise ValueError(f"JSON 文件必须是对象：{path}")
    return payload


def _extract_model_from_preview(preview_text: str) -> dict[str, Any] | None:
    try:
        preview_payload = json.loads(preview_text)
    except json.JSONDecodeError:
        return None
    schema = preview_payload.get("schema")
    if not isinstance(schema, dict):
        return None
    model = schema.get("model")
    return model if isinstance(model, dict) else None


def _extract_model_from_request(request: dict[str, Any]) -> dict[str, Any] | None:
    post_data = request.get("postData")
    if isinstance(post_data, dict):
        value = post_data.get("value")
        if isinstance(value, dict):
            schema = value.get("schema")
            if isinstance(schema, dict) and isinstance(schema.get("model"), dict):
                return schema["model"]

    preview = request.get("preview")
    if isinstance(preview, str):
        return _extract_model_from_preview(preview)
    return None


def _extract_request_defaults(model: dict[str, Any]) -> dict[str, Any]:
    defaults: dict[str, Any] = {}
    for key in DEFAULT_KEYS:
        field = model.get(key)
        if not isinstance(field, dict):
            continue
        if "value" not in field:
            continue
        defaults[key] = field.get("value")
    return defaults


def _find_request(capture: dict[str, Any], endpoint: str) -> dict[str, Any]:
    requests = capture.get("requests")
    if not isinstance(requests, list):
        raise ValueError("capture.requests 必须是数组")

    matched: list[dict[str, Any]] = []
    for item in requests:
        if not isinstance(item, dict):
            continue
        url_info = item.get("url")
        path = url_info.get("path") if isinstance(url_info, dict) else None
        if path == endpoint:
            matched.append(item)
    if not matched:
        raise ValueError(f"未在 capture 中找到目标请求：{endpoint}")
    return matched[-1]


def main() -> int:
    parser = argparse.ArgumentParser(description="从 addWithSchema/editWithSchema capture 中提取稳定 request defaults。")
    parser.add_argument("--capture", required=True, help="capture JSON 路径")
    parser.add_argument("--endpoint", default="/product/tproduct/addWithSchema", help="目标接口路径")
    parser.add_argument("--output", default="", help="可选，输出 JSON 路径")
    args = parser.parse_args()

    capture = _read_json(args.capture)
    request = _find_request(capture, args.endpoint)
    model = _extract_model_from_request(request)
    if not isinstance(model, dict):
        raise ValueError("目标请求里没有可解析的 schema.model")

    defaults = _extract_request_defaults(model)
    if not defaults:
        raise ValueError("未提取到任何 request defaults")

    payload = {
        "source_capture": args.capture,
        "source_endpoint": args.endpoint,
        "defaults": defaults,
        "keys": list(defaults.keys()),
    }

    output_text = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(output_text + "\n", encoding="utf-8")
    else:
        sys.stdout.write(output_text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

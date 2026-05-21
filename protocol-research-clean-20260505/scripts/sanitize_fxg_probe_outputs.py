from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


SENSITIVE_KEYS = {
    "publishId",
    "session_publish_id",
    "shop_id",
    "shopId",
    "ecom_gray_shop_id",
    "__token",
    "msToken",
    "a_bogus",
    "verifyFp",
    "fp",
}


def sanitize(value: Any, parent_key: str = "") -> Any:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if key in SENSITIVE_KEYS:
                result[key] = "[redacted]"
                continue
            if key == "feature" and isinstance(item, dict):
                result[key] = {
                    child_key: "[redacted]" if child_key in SENSITIVE_KEYS else sanitize(child_value, child_key)
                    for child_key, child_value in item.items()
                }
                continue
            result[key] = sanitize(item, key)
        return result
    if isinstance(value, list):
        return [sanitize(item, parent_key) for item in value]
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description="Sanitize FXG probe JSON outputs in place or into another file.")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)
    data = json.loads(input_path.read_text(encoding="utf-8"))
    sanitized = sanitize(data)
    output_path.write_text(json.dumps(sanitized, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"ok": True, "output": str(output_path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

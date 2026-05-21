from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


SENSITIVE_KEYWORDS = (
    "session",
    "sid",
    "token",
    "csrf",
    "passport",
    "odin",
    "ttwid",
    "ucas",
    "mfa",
    "auth",
)


def _safe_hash(value: str) -> str:
    if not value:
        return ""
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()[:12]


def _classify_cookie(name: str) -> str:
    lower_name = name.lower()
    if any(keyword in lower_name for keyword in SENSITIVE_KEYWORDS):
        return "sensitive_session"
    if lower_name.startswith("hm_") or lower_name in {"hmaccount"}:
        return "analytics"
    return "state_or_feature"


def sanitize_cookie(item: dict[str, Any]) -> dict[str, Any]:
    name = str(item.get("name") or "")
    value = str(item.get("value") or "")
    expiration = item.get("expirationDate")
    return {
        "domain": str(item.get("domain") or ""),
        "name": name,
        "path": str(item.get("path") or ""),
        "httpOnly": bool(item.get("httpOnly")),
        "secure": bool(item.get("secure")),
        "sameSite": item.get("sameSite"),
        "session": bool(item.get("session")),
        "hasExpiration": expiration is not None,
        "expirationDate": expiration,
        "valueLength": len(value),
        "valuePreviewHash": _safe_hash(value),
        "category": _classify_cookie(name),
    }


def build_summary(cookies: list[dict[str, Any]]) -> dict[str, Any]:
    sanitized = [sanitize_cookie(item) for item in cookies if isinstance(item, dict)]
    domains = sorted({item["domain"] for item in sanitized if item["domain"]})
    categories: dict[str, int] = {}
    for item in sanitized:
        categories[item["category"]] = categories.get(item["category"], 0) + 1
    return {
        "mode": "cookie_export_sanitized_summary",
        "rawValuesStored": False,
        "cookieCount": len(sanitized),
        "domains": domains,
        "categories": categories,
        "cookies": sanitized,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Sanitize Cookie-Editor JSON export without storing raw cookie values.")
    parser.add_argument("--input", required=True, help="Path to Cookie-Editor JSON export.")
    parser.add_argument("--output", required=True, help="Path to sanitized JSON summary.")
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)
    cookies = json.loads(input_path.read_text(encoding="utf-8"))
    if not isinstance(cookies, list):
        raise ValueError("Cookie export must be a JSON array.")
    summary = build_summary(cookies)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"ok": True, "output": str(output_path), "cookieCount": summary["cookieCount"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

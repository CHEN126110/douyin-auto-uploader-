from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


SUBMIT_ENDPOINTS = (
    "/product/tproduct/addWithSchema",
    "/product/tproduct/editWithSchema",
)

SENSITIVE_TOP_KEYS = {
    "__token",
    "_bid",
    "_lid",
    "appid",
    "msToken",
    "a_bogus",
    "session",
    "request_extra",
    "pass_through_extra",
    "context",
}


def _is_truncation_marker(value: Any) -> bool:
    return isinstance(value, str) and value in {"<max-depth>", "<unsupported>"}


def _contains_truncation_marker(value: Any) -> bool:
    if _is_truncation_marker(value):
        return True
    if isinstance(value, dict):
        return any(_contains_truncation_marker(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_truncation_marker(item) for item in value)
    return False


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return payload


def _normalize_text(value: Any) -> str:
    if _is_truncation_marker(value):
        return ""
    return " ".join(str(value or "").split()).strip()


def _hash_text(value: Any) -> str:
    text = _normalize_text(value)
    if not text:
        return ""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _request_path(request: dict[str, Any]) -> str:
    url = request.get("url") if isinstance(request.get("url"), dict) else {}
    return _normalize_text(url.get("path") or url.get("sanitized"))


def _post_data(request: dict[str, Any]) -> Any:
    post_data = request.get("postData") if isinstance(request.get("postData"), dict) else {}
    return post_data.get("value")


def _schema_model(body: dict[str, Any]) -> dict[str, Any]:
    schema = body.get("schema") if isinstance(body.get("schema"), dict) else {}
    model = schema.get("model") if isinstance(schema.get("model"), dict) else {}
    return model if isinstance(model, dict) else {}


def _field_value(model: dict[str, Any], key: str) -> Any:
    field_obj = model.get(key) if isinstance(model.get(key), dict) else {}
    return field_obj.get("value")


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _present_count(rows: list[Any], key: str) -> int:
    return sum(1 for row in rows if isinstance(row, dict) and key in row and row.get(key) not in (None, ""))


def _stock_num_count(rows: list[Any]) -> int:
    count = 0
    for row in rows:
        stock_info = row.get("stock_info") if isinstance(row, dict) and isinstance(row.get("stock_info"), dict) else {}
        if stock_info.get("stock_num") not in (None, ""):
            count += 1
    return count


def _build_spec_value_map(spec_detail: list[Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for axis in spec_detail:
        if not isinstance(axis, dict):
            continue
        axis_name = _normalize_text(axis.get("name"))
        for item in _as_list(axis.get("spec_values")):
            if not isinstance(item, dict):
                continue
            value_id = _normalize_text(item.get("id"))
            if not value_id:
                continue
            result[value_id] = {
                "axis_name": axis_name,
                "value_hash": _hash_text(item.get("name")),
                "has_cpv_id": item.get("cpv_id") not in (None, ""),
                "has_measure_info": isinstance(item.get("measure_info"), dict),
            }
    return result


def _summarize_spec_detail(spec_detail: list[Any]) -> dict[str, Any]:
    axes: list[dict[str, Any]] = []
    for axis in spec_detail:
        if not isinstance(axis, dict):
            continue
        values = [item for item in _as_list(axis.get("spec_values")) if isinstance(item, dict)]
        axes.append(
            {
                "id": _normalize_text(axis.get("id")),
                "name": _normalize_text(axis.get("name")),
                "cp_id": None if _is_truncation_marker(axis.get("cp_id")) else axis.get("cp_id"),
                "truncated": _contains_truncation_marker(axis),
                "value_count": len(values),
                "value_id_count": _present_count(values, "id"),
                "value_cpv_id_count": _present_count(values, "cpv_id"),
                "measure_info_count": sum(1 for item in values if isinstance(item.get("measure_info"), dict)),
            }
        )
    return {
        "axis_count": len(axes),
        "axes": axes,
    }


def _sku_label_hash(row: dict[str, Any], spec_value_map: dict[str, dict[str, Any]]) -> str:
    spec_ids = [_normalize_text(item) for item in _as_list(row.get("spec_detail_ids")) if _normalize_text(item)]
    parts = []
    for spec_id in spec_ids:
        item = spec_value_map.get(spec_id) or {}
        parts.append(f"{item.get('axis_name', '')}:{item.get('value_hash', '')}")
    return _hash_text("|".join(parts))


def _summarize_sku_detail(sku_detail: list[Any], spec_value_map: dict[str, dict[str, Any]]) -> dict[str, Any]:
    rows = [row for row in sku_detail if isinstance(row, dict)]
    row_summaries: list[dict[str, Any]] = []
    missing_price = 0
    missing_stock_info = 0
    missing_spec_ids = 0
    missing_id = 0
    for index, row in enumerate(rows):
        spec_ids = [_normalize_text(item) for item in _as_list(row.get("spec_detail_ids")) if _normalize_text(item)]
        stock_info = row.get("stock_info") if isinstance(row.get("stock_info"), dict) else {}
        if row.get("price") in (None, ""):
            missing_price += 1
        if not isinstance(row.get("stock_info"), dict) or stock_info.get("stock_num") in (None, ""):
            missing_stock_info += 1
        if not spec_ids:
            missing_spec_ids += 1
        if row.get("id") in (None, ""):
            missing_id += 1
        all_spec_ids_known = bool(spec_ids) and all(spec_id in spec_value_map for spec_id in spec_ids)
        row_summaries.append(
            {
                "index": index,
                "id_present": row.get("id") not in (None, ""),
                "sku_id_present": row.get("sku_id") not in (None, ""),
                "spec_detail_id_count": len(spec_ids),
                "all_spec_ids_known": all_spec_ids_known,
                "truncated": _contains_truncation_marker(row),
                "label_hash": _sku_label_hash(row, spec_value_map),
                "price_present": row.get("price") not in (None, ""),
                "price_type": type(row.get("price")).__name__ if row.get("price") is not None else "missing",
                "stock_present": row.get("stock") not in (None, ""),
                "stock_type": type(row.get("stock")).__name__ if row.get("stock") is not None else "missing",
                "stock_info_present": isinstance(row.get("stock_info"), dict),
                "stock_info_stock_num_present": stock_info.get("stock_num") not in (None, ""),
                "stock_info_keys": sorted(stock_info.keys()) if isinstance(stock_info, dict) else [],
                "sku_pic_count": len(_as_list(row.get("sku_pic"))),
                "sku_status_present": row.get("sku_status") not in (None, ""),
            }
        )
    return {
        "sku_count": len(rows),
        "price_count": _present_count(rows, "price"),
        "stock_count": _present_count(rows, "stock"),
        "stock_info_count": sum(1 for row in rows if isinstance(row.get("stock_info"), dict)),
        "stock_info_stock_num_count": _stock_num_count(rows),
        "spec_detail_ids_key_count": _present_count(rows, "spec_detail_ids"),
        "usable_spec_detail_ids_count": sum(
            1
            for row in rows
            if [_normalize_text(item) for item in _as_list(row.get("spec_detail_ids")) if _normalize_text(item)]
        ),
        "id_count": _present_count(rows, "id"),
        "sku_id_count": _present_count(rows, "sku_id"),
        "sku_pic_row_count": sum(1 for row in rows if _as_list(row.get("sku_pic"))),
        "missing": {
            "price": missing_price,
            "stock_info_stock_num": missing_stock_info,
            "spec_detail_ids": missing_spec_ids,
            "id": missing_id,
        },
        "rows": row_summaries,
    }


def _detect_blockers(
    *,
    submit_requests: list[dict[str, Any]],
    spec_detail: list[Any],
    sku_detail: list[Any],
    sku_summary: dict[str, Any],
    has_truncation_marker: bool,
) -> list[dict[str, str]]:
    blockers: list[dict[str, str]] = []
    if not submit_requests:
        blockers.append(
            {
                "code": "NO_SUBMIT_BODY",
                "message": "未找到 addWithSchema/editWithSchema 请求体，不能分析价格库存协议字段。",
            }
        )
        return blockers
    if has_truncation_marker:
        blockers.append(
            {
                "code": "CAPTURE_SANITIZED_DEPTH_LIMIT",
                "message": "样本中存在 <max-depth>/<unsupported> 截断标记，只能证明请求存在，不能作为完整字段映射证据。",
            }
        )
    if not spec_detail:
        blockers.append(
            {
                "code": "MISSING_SPEC_DETAIL",
                "message": "提交体缺少 spec_detail.value，无法建立规格值到 SKU 行的映射。",
            }
        )
    if not sku_detail:
        blockers.append(
            {
                "code": "MISSING_SKU_DETAIL",
                "message": "提交体缺少 sku_detail.value，无法确认价格库存字段。",
            }
        )
    if sku_summary.get("missing", {}).get("spec_detail_ids"):
        blockers.append(
            {
                "code": "SKU_SPEC_ID_GAP",
                "message": "存在 SKU 行缺少 spec_detail_ids，无法稳定映射本地 SKU。",
            }
        )
    if sku_summary.get("missing", {}).get("price"):
        blockers.append(
            {
                "code": "SKU_PRICE_GAP",
                "message": "存在 SKU 行缺少 price，不能证明价格字段完整。",
            }
        )
    if sku_summary.get("missing", {}).get("stock_info_stock_num"):
        blockers.append(
            {
                "code": "SKU_STOCK_INFO_GAP",
                "message": "存在 SKU 行缺少 stock_info.stock_num，不能证明库存字段完整。",
            }
        )
    if sku_summary.get("stock_count", 0) == 0 and sku_summary.get("stock_info_stock_num_count", 0) > 0:
        blockers.append(
            {
                "code": "STOCK_FIELD_RELATION_UNVERIFIED",
                "message": "样本使用 stock_info.stock_num，未出现顶层 stock；仍需验证 stock 与 stock_info 的服务端关系。",
            }
        )
    if not any(request.get("blocked") for request in submit_requests):
        blockers.append(
            {
                "code": "NO_BLOCKED_SUBMIT_SAMPLE",
                "message": "样本不是本地截停提交请求，不能作为安全的 preflight 证据。",
            }
        )
    return blockers


def _sanitize_body_key_presence(body: dict[str, Any]) -> dict[str, Any]:
    return {
        "top_level_keys": sorted(key for key in body.keys() if key not in SENSITIVE_TOP_KEYS),
        "sensitive_key_presence": {key: key in body for key in sorted(SENSITIVE_TOP_KEYS)},
    }


def analyze_price_stock_capture(capture: dict[str, Any], *, source_label: str = "") -> dict[str, Any]:
    requests = [item for item in _as_list(capture.get("requests")) if isinstance(item, dict)]
    submit_requests = [
        request
        for request in requests
        if any(endpoint in _request_path(request) for endpoint in SUBMIT_ENDPOINTS)
        and isinstance(_post_data(request), dict)
    ]
    primary_request = submit_requests[-1] if submit_requests else {}
    primary_body = _post_data(primary_request) if primary_request else {}
    model = _schema_model(primary_body) if isinstance(primary_body, dict) else {}
    has_truncation_marker = _contains_truncation_marker(primary_body)
    spec_detail = _as_list(_field_value(model, "spec_detail"))
    sku_detail = _as_list(_field_value(model, "sku_detail"))
    spec_value_map = _build_spec_value_map(spec_detail)
    spec_summary = _summarize_spec_detail(spec_detail)
    sku_summary = _summarize_sku_detail(sku_detail, spec_value_map)
    blockers = _detect_blockers(
        submit_requests=submit_requests,
        spec_detail=spec_detail,
        sku_detail=sku_detail,
        sku_summary=sku_summary,
        has_truncation_marker=has_truncation_marker,
    )
    evidence_status = "blocked_capture_verified" if submit_requests and any(item.get("blocked") for item in submit_requests) else "source_or_observed_only"
    return {
        "mode": "price_stock_capture_analysis",
        "submit_enabled": False,
        "source_label": source_label,
        "capture_profile": capture.get("captureProfile"),
        "capture_target_url_hash": _hash_text((capture.get("target") or {}).get("url") if isinstance(capture.get("target"), dict) else ""),
        "request_count": len(requests),
        "submit_request_count": len(submit_requests),
        "blocked_submit_request_count": sum(1 for request in submit_requests if request.get("blocked")),
        "evidence_status": evidence_status,
        "evidence_quality": {
            "has_sanitized_depth_marker": has_truncation_marker,
            "contains_sensitive_values": False,
            "note": "本报告只保存敏感顶层字段是否存在，不保存 token、cookie、session 原文。",
        },
        "primary_submit": {
            "method": primary_request.get("method") if primary_request else "",
            "path": _request_path(primary_request) if primary_request else "",
            "blocked": bool(primary_request.get("blocked")) if primary_request else False,
            "intercepted": bool(primary_request.get("intercepted")) if primary_request else False,
            "post_data_type": (primary_request.get("postData") or {}).get("type") if primary_request else "",
            "body_key_presence": _sanitize_body_key_presence(primary_body) if isinstance(primary_body, dict) else {},
            "category_id_present": bool(primary_body.get("category_id")) if isinstance(primary_body, dict) else False,
            "check_status": primary_body.get("check_status") if isinstance(primary_body, dict) else None,
            "schema_model_key_count": len(model),
            "schema_model_keys": sorted(model.keys()),
        },
        "spec_detail": spec_summary,
        "sku_detail": sku_summary,
        "field_relation": {
            "price_location": "schema.model.sku_detail.value[].price" if sku_summary.get("price_count") else "unverified",
            "stock_num_location": (
                "schema.model.sku_detail.value[].stock_info.stock_num"
                if sku_summary.get("stock_info_stock_num_count")
                else "unverified"
            ),
            "top_level_stock_present": bool(sku_summary.get("stock_count")),
            "stock_info_required_by_sample": bool(sku_summary.get("stock_info_stock_num_count")),
            "independent_price_stock_endpoint": "not_found_in_capture",
        },
        "blockers": blockers,
        "next_verification": [
            "用 submit-preflight 截停当前页面生成的新 addWithSchema/editWithSchema 请求体。",
            "对同一商品只改变价格和库存，比较 sku_detail 行 ID、spec_detail_ids 与 stock_info 是否稳定。",
            "在确认 stock 与 stock_info 关系前，不接入正式上传按钮。",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="离线分析 FXG 提交截停产物中的价格库存字段，不发送请求。")
    parser.add_argument("--capture", required=True, help="cdp_fxg_protocol_capture 输出 JSON 路径")
    parser.add_argument("--output", default="", help="可选，分析结果输出 JSON 路径")
    parser.add_argument("--source-label", default="", help="可选，标记样本来源，例如 legacy-reference 或 clean-current")
    args = parser.parse_args()

    capture_path = Path(args.capture)
    report = analyze_price_stock_capture(_read_json(capture_path), source_label=args.source_label)
    output_text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(output_text + "\n", encoding="utf-8")
    else:
        print(output_text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

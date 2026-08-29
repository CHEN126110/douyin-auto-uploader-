from __future__ import annotations

import argparse
import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any


TARGET_FIELD_GROUPS = {
    "sku_price_stock": [
        "spec_detail",
        "sku_detail",
        "price",
        "stock_info",
        "stock",
        "sku_pic",
        "spec_detail_ids",
    ],
    "media": [
        "pic",
        "main_image_three_to_four",
        "long_pic",
        "white_background_pic",
        "main_pic_video",
        "description",
    ],
    "qualification": [
        "qualification",
        "quality_attachment_id",
        "quality_content_name",
        "quality_attachments",
        "select_attachments",
    ],
    "submit": [
        "schema",
        "category_id",
        "context",
        "pass_through_extra",
        "check_status",
    ],
}


def _read_json(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8-sig") as fp:
        payload = json.load(fp)
    if not isinstance(payload, dict):
        raise ValueError(f"JSON 文件必须是对象：{path}")
    return payload


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _request_path(request: dict[str, Any]) -> str:
    url = request.get("url") if isinstance(request.get("url"), dict) else {}
    return _normalize_text(url.get("path") or url.get("sanitized"))


def _post_data_value(request: dict[str, Any]) -> Any:
    post_data = request.get("postData") if isinstance(request.get("postData"), dict) else {}
    return post_data.get("value")


def _post_data_type(request: dict[str, Any]) -> str:
    post_data = request.get("postData") if isinstance(request.get("postData"), dict) else {}
    return _normalize_text(post_data.get("type"))


def _schema_model(body: dict[str, Any]) -> dict[str, Any]:
    schema = body.get("schema") if isinstance(body.get("schema"), dict) else {}
    if isinstance(schema.get("model"), dict):
        return schema.get("model")
    return schema


def _walk_keys(value: Any, *, prefix: str = "") -> Iterable[tuple[str, Any]]:
    if isinstance(value, dict):
        for key, item in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            yield path, item
            yield from _walk_keys(item, prefix=path)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            path = f"{prefix}[{index}]"
            yield path, item
            yield from _walk_keys(item, prefix=path)


def _contains_field(value: Any, field_name: str) -> bool:
    if isinstance(value, dict) and field_name in value:
        return True
    return any(path.endswith(f".{field_name}") or path == field_name for path, _ in _walk_keys(value))


def _classify_request(path: str) -> list[str]:
    if "/product/tproduct/addWithSchema" in path or "/product/tproduct/editWithSchema" in path:
        return ["submit", "sku_price_stock", "media", "qualification"]
    if "/product/img/batchupload" in path:
        return ["image_upload", "media", "qualification"]
    if (
        "/product/tproduct/saveMaterial" in path
        or "/product/tproduct/materialDetail" in path
        or "/product/tproduct/material/batchApplyMaterial" in path
    ):
        return ["media"]
    if "/product/tproduct/submitWhiteImg" in path or "/product/tproduct/batchApprovalWhiteImgs" in path:
        return ["media"]
    if "/common/img/IsWhiteBackgroundPic" in path:
        return ["media"]
    if "/ffa/grs/qualification/list" in path or "/ffa/mshop/qualification/list" in path:
        return ["qualification"]
    return ["other"]


def _field_value_items(model: dict[str, Any], field: str) -> list[Any]:
    field_obj = model.get(field) if isinstance(model.get(field), dict) else {}
    value = field_obj.get("value")
    return value if isinstance(value, list) else []


def _category_properties_value(model: dict[str, Any]) -> dict[str, Any]:
    field_obj = model.get("category_properties") if isinstance(model.get("category_properties"), dict) else {}
    value = field_obj.get("value")
    return value if isinstance(value, dict) else {}


def _summarize_property_785(model: dict[str, Any]) -> dict[str, Any]:
    category_properties = _category_properties_value(model)
    items = category_properties.get("785") if isinstance(category_properties.get("785"), list) else []
    template_ids: list[Any] = []
    module_ids: list[Any] = []
    value_names: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        value_name = _normalize_text(item.get("value_name"))
        if value_name:
            value_names.append(value_name)
        measure_info = item.get("measure_info") if isinstance(item.get("measure_info"), dict) else {}
        template_id = measure_info.get("template_id")
        if template_id not in template_ids:
            template_ids.append(template_id)
        values = measure_info.get("values") if isinstance(measure_info.get("values"), list) else []
        for value_item in values:
            if not isinstance(value_item, dict):
                continue
            module_id = value_item.get("module_id")
            if module_id not in module_ids:
                module_ids.append(module_id)
    return {
        "item_count": len(items),
        "value_names": value_names,
        "template_ids": template_ids,
        "module_ids": module_ids,
        "items": items,
    }


def _summarize_submit_body(body: Any) -> dict[str, Any]:
    model = _schema_model(body) if isinstance(body, dict) else {}
    spec_detail = _field_value_items(model, "spec_detail")
    sku_detail = _field_value_items(model, "sku_detail")
    first_sku = sku_detail[0] if sku_detail and isinstance(sku_detail[0], dict) else {}
    main34 = _field_value_items(model, "main_image_three_to_four")
    white_bg = _field_value_items(model, "white_background_pic")
    video_items = _field_value_items(model, "main_pic_video")
    property_785 = _summarize_property_785(model)
    category_properties = _category_properties_value(model)
    return {
        "schema_key_count": len(model),
        "schema_keys": sorted(model.keys())[:120],
        "category_id": body.get("category_id") if isinstance(body, dict) else None,
        "check_status": body.get("check_status") if isinstance(body, dict) else None,
        "spec_axis_count": len(spec_detail),
        "spec_axis_names": [
            _normalize_text(item.get("name"))
            for item in spec_detail
            if isinstance(item, dict)
        ],
        "sku_count": len(sku_detail),
        "first_sku_keys": sorted(first_sku.keys()) if isinstance(first_sku, dict) else [],
        "first_sku_price": first_sku.get("price") if isinstance(first_sku, dict) else None,
        "first_sku_stock_info": first_sku.get("stock_info") if isinstance(first_sku, dict) else None,
        "media_summary": {
            "main_image_three_to_four_count": len(main34),
            "white_background_pic_count": len(white_bg),
            "main_pic_video_count": len(video_items),
            "first_main_pic_video": video_items[0] if video_items and isinstance(video_items[0], dict) else {},
        },
        "category_properties_summary": {
            "property_keys": sorted(category_properties.keys()),
            "property_785": property_785,
        },
        "field_presence": {
            field: _contains_field(body, field)
            for group in TARGET_FIELD_GROUPS.values()
            for field in group
        },
    }


def _summarize_multipart(body: Any) -> dict[str, Any]:
    parts = body if isinstance(body, list) else []
    return {
        "part_count": len(parts),
        "field_names": [
            _normalize_text(item.get("fieldName"))
            for item in parts
            if isinstance(item, dict)
        ],
        "binary_field_names": [
            _normalize_text(item.get("fieldName"))
            for item in parts
            if isinstance(item, dict) and item.get("binaryOmitted")
        ],
    }


def _request_evidence(request: dict[str, Any]) -> dict[str, Any]:
    path = _request_path(request)
    body = _post_data_value(request)
    post_data_type = _post_data_type(request)
    chains = _classify_request(path)
    evidence: dict[str, Any] = {
        "method": request.get("method"),
        "path": path,
        "chains": chains,
        "blocked": bool(request.get("blocked")),
        "intercepted": bool(request.get("intercepted")),
        "has_post_data": bool(request.get("hasPostData")),
        "post_data_type": post_data_type,
    }
    if ("submit" in chains or "sku_price_stock" in chains) and isinstance(body, dict):
        evidence["submit_body"] = _summarize_submit_body(body)
    elif post_data_type == "multipart":
        evidence["multipart"] = _summarize_multipart(body)
    elif isinstance(body, dict):
        evidence["json_keys"] = sorted(body.keys())[:80]
        evidence["field_presence"] = {
            field: _contains_field(body, field)
            for group in TARGET_FIELD_GROUPS.values()
            for field in group
        }
    return evidence


def _build_chain_status(requests: list[dict[str, Any]]) -> dict[str, Any]:
    chains = ["submit", "sku_price_stock", "media", "image_upload", "qualification", "other"]
    result: dict[str, Any] = {}
    request_evidence = [_request_evidence(item) for item in requests if isinstance(item, dict)]
    for chain in chains:
        items = [item for item in request_evidence if chain in item["chains"]]
        result[chain] = {
            "request_count": len(items),
            "blocked_count": sum(1 for item in items if item["blocked"]),
            "has_request_body": any(item["has_post_data"] for item in items),
            "paths": sorted({item["path"] for item in items if item["path"]}),
        }
    return result


def _dry_run_context(dry_run: dict[str, Any] | None) -> dict[str, Any]:
    if not dry_run:
        return {}
    proposed = dry_run.get("proposed_submit_model") if isinstance(dry_run.get("proposed_submit_model"), dict) else {}
    report = dry_run.get("field_verification_report") if isinstance(dry_run.get("field_verification_report"), dict) else {}
    return {
        "record_id": dry_run.get("record", {}).get("record_id") if isinstance(dry_run.get("record"), dict) else None,
        "title": proposed.get("title"),
        "category_leaf_id": (
            proposed.get("goods_category", {}).get("category_leaf_id")
            if isinstance(proposed.get("goods_category"), dict)
            else None
        ),
        "spec_axis_count": len(proposed.get("spec_detail")) if isinstance(proposed.get("spec_detail"), list) else 0,
        "sku_count": len(proposed.get("sku_detail")) if isinstance(proposed.get("sku_detail"), list) else 0,
        "verified_field_count": len(report.get("verified_fields")) if isinstance(report.get("verified_fields"), list) else 0,
        "missing_field_count": len(report.get("missing_fields")) if isinstance(report.get("missing_fields"), list) else 0,
        "cannot_submit_field_count": (
            len(report.get("cannot_submit_fields")) if isinstance(report.get("cannot_submit_fields"), list) else 0
        ),
    }


def analyze_capture_evidence(capture: dict[str, Any], dry_run: dict[str, Any] | None = None) -> dict[str, Any]:
    requests = capture.get("requests") if isinstance(capture.get("requests"), list) else []
    evidence = [_request_evidence(item) for item in requests if isinstance(item, dict)]
    chain_status = _build_chain_status(requests)
    missing_priority_evidence = [
        chain
        for chain in ("submit", "sku_price_stock", "media", "qualification")
        if not chain_status.get(chain, {}).get("has_request_body")
    ]
    return {
        "mode": "capture_evidence_analysis",
        "submit_enabled": False,
        "capture_profile": capture.get("captureProfile"),
        "target": capture.get("target"),
        "request_count": len(requests),
        "blocked_count": sum(1 for item in requests if isinstance(item, dict) and item.get("blocked")),
        "chain_status": chain_status,
        "request_evidence": evidence,
        "dry_run_context": _dry_run_context(dry_run),
        "missing_priority_evidence": missing_priority_evidence,
        "next_steps": [
            "继续补充不同样本下 category_properties.785.measure_info 的后端约束证据",
            "继续确认 submitWhiteImg/batchApprovalWhiteImgs 触发条件，而不是把当前成功样本外推成唯一链路",
            "继续确认 qualification 非空结构与 main_pic_video.resource_id 来源",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="离线分析 cdp_fxg_protocol_capture 产物，不调用平台接口。")
    parser.add_argument("--capture", required=True, help="cdp_fxg_protocol_capture 输出 JSON 路径")
    parser.add_argument("--dry-run", default="", help="可选，协议 dry-run 输出 JSON 路径")
    parser.add_argument("--output", default="", help="可选，分析结果输出 JSON 路径")
    args = parser.parse_args()

    capture = _read_json(args.capture)
    dry_run = _read_json(args.dry_run) if args.dry_run else None
    report = analyze_capture_evidence(capture, dry_run)
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

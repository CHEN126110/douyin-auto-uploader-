from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _read_json(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8-sig") as fp:
        payload = json.load(fp)
    if not isinstance(payload, dict):
        raise ValueError(f"JSON 文件必须是对象：{path}")
    return payload


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _schema_category_id(dry_run: dict[str, Any], schema_probe: dict[str, Any]) -> str:
    proposed = dry_run.get("proposed_submit_model") if isinstance(dry_run.get("proposed_submit_model"), dict) else {}
    goods_category = proposed.get("goods_category") if isinstance(proposed.get("goods_category"), dict) else {}
    category_id = goods_category.get("category_leaf_id")
    if category_id:
        return str(category_id)

    request_context = schema_probe.get("requestContext") if isinstance(schema_probe.get("requestContext"), dict) else {}
    category_id = request_context.get("category_id")
    if category_id:
        return str(category_id)

    response_context = schema_probe.get("responseContextSummary") if isinstance(schema_probe.get("responseContextSummary"), dict) else {}
    return str(response_context.get("category_id") or "")


def _build_context(schema_probe: dict[str, Any], category_id: str) -> dict[str, Any]:
    request_context = schema_probe.get("requestContext") if isinstance(schema_probe.get("requestContext"), dict) else {}
    response_context = schema_probe.get("responseContextSummary") if isinstance(schema_probe.get("responseContextSummary"), dict) else {}
    context = dict(request_context)
    if category_id:
        context["category_id"] = category_id
    if response_context.get("operation_type"):
        context["operation_type"] = response_context.get("operation_type")
    if response_context.get("product_id") is not None:
        context["product_id"] = response_context.get("product_id")
    if response_context.get("model_type") is not None:
        context["model_type"] = response_context.get("model_type")
    if response_context.get("version"):
        context["version"] = response_context.get("version")
    context.pop("gray_components", None)
    return context


def _field_names(items: Any) -> list[str]:
    if not isinstance(items, list):
        return []
    return [
        _normalize_text(item.get("field"))
        for item in items
        if isinstance(item, dict) and _normalize_text(item.get("field"))
    ]


def _first_sku_summary(model: dict[str, Any]) -> dict[str, Any]:
    sku_detail = model.get("sku_detail") if isinstance(model.get("sku_detail"), list) else []
    first_sku = sku_detail[0] if sku_detail and isinstance(sku_detail[0], dict) else {}
    return {
        "sku_count": len(sku_detail),
        "first_sku_keys": sorted(first_sku.keys()) if isinstance(first_sku, dict) else [],
        "first_sku_price": first_sku.get("price") if isinstance(first_sku, dict) else None,
        "first_sku_stock": first_sku.get("stock") if isinstance(first_sku, dict) else None,
        "first_sku_stock_info": first_sku.get("stock_info") if isinstance(first_sku, dict) else None,
    }


def build_submit_preflight_body(
    *,
    dry_run: dict[str, Any],
    schema_probe: dict[str, Any],
    check_status: str,
) -> dict[str, Any]:
    proposed = dry_run.get("proposed_submit_model") if isinstance(dry_run.get("proposed_submit_model"), dict) else {}
    report = dry_run.get("field_verification_report") if isinstance(dry_run.get("field_verification_report"), dict) else {}
    category_id = _schema_category_id(dry_run, schema_probe)
    context = _build_context(schema_probe, category_id)
    blocked_fields = _field_names(report.get("cannot_submit_fields"))
    missing_fields = _field_names(report.get("missing_fields"))
    request_body = {
        "schema": proposed,
        "category_id": category_id,
        "context": context,
        "pass_through_extra": {},
        "check_status": check_status,
    }

    return {
        "mode": "submit_preflight_body",
        "submit_enabled": False,
        "endpoint": f"/product/tproduct/addWithSchema?check_status={check_status}",
        "request_body": request_body,
        "audit": {
            "body_source": "dry-run proposed_submit_model plus schema probe context",
            "is_platform_capture": False,
            "can_send_to_platform": False,
            "reason": "该文件用于审计 addWithSchema envelope 和字段缺口；不是页面真实提交请求体，也不能发送到平台",
            "category_id": category_id,
            "schema_key_count": len(proposed),
            "spec_axis_count": len(proposed.get("spec_detail")) if isinstance(proposed.get("spec_detail"), list) else 0,
            **_first_sku_summary(proposed),
            "verified_fields": _field_names(report.get("verified_fields")),
            "missing_fields": missing_fields,
            "cannot_submit_fields": blocked_fields,
            "hard_blockers": [
                "spec_detail/sku_detail 规格值 ID 和 SKU 组合 ID 仍是 dry-run 候选值",
                "qualification 非空结构仍缺真实请求体证据",
                "main_pic_video.resource_id 与 saveMaterial/素材链关系仍未闭环",
                "category_properties.785.measure_info 后端约束仍只在单一样本下验证",
            ],
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="从 dry-run 和 schema probe 生成 addWithSchema 本地预检 body，不发送请求。")
    parser.add_argument("--dry-run", required=True, help="协议 dry-run 输出 JSON 路径")
    parser.add_argument("--schema", required=True, help="fxg-schema-probe 输出 JSON 路径")
    parser.add_argument("--check-status", default="0", help="addWithSchema check_status，默认 0")
    parser.add_argument("--output", default="", help="可选，输出 JSON 路径")
    args = parser.parse_args()

    dry_run = _read_json(args.dry_run)
    schema_probe = _read_json(args.schema)
    result = build_submit_preflight_body(
        dry_run=dry_run,
        schema_probe=schema_probe,
        check_status=_normalize_text(args.check_status) or "0",
    )
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

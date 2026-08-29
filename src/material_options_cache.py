# -*- coding: utf-8 -*-
"""平台面料材质选项的本地缓存。

内置的 `PLATFORM_MATERIAL_OPTIONS` 只有十余项，而平台该类目实际下发 144 项
（见 tmp_runtime_probe_live/fxg_category_matrix_socks_*.json 中属性 id=785 的 optionCount），
把它当白名单会把绝大多数真实材质挡在外面。

这里在发布流程真正打开材质下拉时顺带把平台完整列表采下来缓存，
设置界面据此展示，从而「拉取平台最新数据」而不是维护一份注定过时的清单。

设计约束：
- 采集失败**绝不覆盖已有缓存**，也绝不影响发布主流程；
- 失败留痕（last_error），由设置接口带给前端，不静默吞掉；
- 读侧永远可降级：缓存缺失时调用方回退内置默认，且下拉支持自定义输入。
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from typing import Any, Dict, List, Optional

from .runtime_paths import get_resource_dir, resolve_data_file

CACHE_FILENAME = "platform_material_options.json"
SCHEMA_VERSION = 1

# 少于该数量视为没采全（真实类目动辄上百项），不予采信
MIN_TRUSTWORTHY_COUNT = 5
# 新列表不足旧列表一半时视为异常收缩（多半是没滚完），保留旧值
SHRINK_GUARD_RATIO = 2
MATERIAL_NAME_MAX_LENGTH = 40


def resolve_cache_path():
    return resolve_data_file(
        CACHE_FILENAME, legacy_fallback=get_resource_dir() / CACHE_FILENAME
    )


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _empty_payload() -> Dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, "buckets": {}, "last_error": "", "last_error_at": ""}


def _read_payload() -> Dict[str, Any]:
    path = resolve_cache_path()
    try:
        if not os.path.exists(path):
            return _empty_payload()
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception:
        # 文件损坏时按空缓存处理；调用方会回退内置默认，不影响使用
        return _empty_payload()
    if not isinstance(data, dict):
        return _empty_payload()
    data.setdefault("schema_version", SCHEMA_VERSION)
    if not isinstance(data.get("buckets"), dict):
        data["buckets"] = {}
    data.setdefault("last_error", "")
    data.setdefault("last_error_at", "")
    return data


def _write_payload(payload: Dict[str, Any]) -> bool:
    """原子写入：先写临时文件再替换，避免进程被杀时留下半个 JSON。"""
    path = resolve_cache_path()
    try:
        directory = os.path.dirname(str(path))
        if directory:
            os.makedirs(directory, exist_ok=True)
        handle = tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=directory or None, delete=False, suffix=".tmp"
        )
        try:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        finally:
            handle.close()
        os.replace(handle.name, str(path))
        return True
    except Exception:
        return False


def _clean_options(options: Any) -> List[str]:
    if not isinstance(options, list):
        return []
    seen = set()
    cleaned: List[str] = []
    for item in options:
        name = str(item or "").strip()
        if not name or len(name) > MATERIAL_NAME_MAX_LENGTH or name in seen:
            continue
        seen.add(name)
        cleaned.append(name)
    return cleaned


def record_failure(reason: str) -> None:
    """记录一次采集失败，**不动已有的 buckets**。"""
    payload = _read_payload()
    payload["last_error"] = str(reason or "")[:200]
    payload["last_error_at"] = _now_iso()
    _write_payload(payload)


def save_options(category: str, options: Any, source: str = "publish-step2-dropdown") -> bool:
    """写入某个类目的平台材质列表。

    返回 True 表示确实写入；返回 False 表示因数据不可信而**保留旧值**
    （并把原因记进 last_error 供设置界面展示）。
    """
    cleaned = _clean_options(options)
    bucket_key = str(category or "").strip() or "default"

    if len(cleaned) < MIN_TRUSTWORTHY_COUNT:
        record_failure(f"too few options: {len(cleaned)}")
        return False

    payload = _read_payload()
    previous = payload["buckets"].get(bucket_key) or {}
    previous_options = previous.get("options") if isinstance(previous, dict) else None
    if isinstance(previous_options, list) and previous_options:
        if len(cleaned) * SHRINK_GUARD_RATIO < len(previous_options):
            record_failure(
                f"suspicious shrink: {len(previous_options)} -> {len(cleaned)} ({bucket_key})"
            )
            return False

    payload["buckets"][bucket_key] = {
        "updated_at": _now_iso(),
        "source": str(source or "")[:60],
        "count": len(cleaned),
        "options": cleaned,
    }
    payload["last_error"] = ""
    payload["last_error_at"] = ""
    return _write_payload(payload)


def load_options(category: Optional[str] = None) -> List[str]:
    """取平台材质列表。

    指定类目时优先返回该类目的；否则按更新时间倒序合并所有类目（保持顺序、去重）。
    缓存不存在时返回空列表，由调用方回退内置默认。
    """
    payload = _read_payload()
    buckets = payload.get("buckets") or {}
    if not isinstance(buckets, dict) or not buckets:
        return []

    key = str(category or "").strip()
    if key and isinstance(buckets.get(key), dict):
        return _clean_options(buckets[key].get("options"))

    ordered = sorted(
        (b for b in buckets.values() if isinstance(b, dict)),
        key=lambda b: str(b.get("updated_at") or ""),
        reverse=True,
    )
    merged: List[str] = []
    seen = set()
    for bucket in ordered:
        for name in _clean_options(bucket.get("options")):
            if name in seen:
                continue
            seen.add(name)
            merged.append(name)
    return merged


def load_meta() -> Dict[str, Any]:
    """给设置界面看的元信息：最近更新时间、条目数、最近一次失败原因。"""
    payload = _read_payload()
    buckets = payload.get("buckets") or {}
    latest_at = ""
    total = 0
    for bucket in buckets.values():
        if not isinstance(bucket, dict):
            continue
        updated_at = str(bucket.get("updated_at") or "")
        if updated_at > latest_at:
            latest_at = updated_at
        total = max(total, int(bucket.get("count") or 0))
    return {
        "updated_at": latest_at,
        "category_count": len(buckets),
        "option_count": total,
        "last_error": payload.get("last_error") or "",
        "last_error_at": payload.get("last_error_at") or "",
        "cache_path": str(resolve_cache_path()),
    }

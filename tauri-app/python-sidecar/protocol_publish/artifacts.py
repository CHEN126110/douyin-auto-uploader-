from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.runtime_paths import resolve_data_file

from .models import ProtocolCaptureArtifact, ProtocolCaptureEntry


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


class ProtocolArtifactStore:
    """协议化上传调试产物存储。

    目标不是做缓存，而是为接口挖掘与执行审计提供稳定落盘位置。
    """

    def __init__(self, run_id: str, root_relative_path: str = "protocol-publish") -> None:
        self.run_id = str(run_id).strip()
        if not self.run_id:
            raise ValueError("run_id is required")
        self.root = Path(resolve_data_file(Path(root_relative_path) / self.run_id))
        self.root.mkdir(parents=True, exist_ok=True)

    def append_capture(self, entry: ProtocolCaptureEntry) -> ProtocolCaptureArtifact:
        target = self.root / entry.stage / "captures.jsonl"
        _ensure_parent(target)
        with target.open("a", encoding="utf-8", errors="replace") as fp:
            fp.write(json.dumps(entry.to_dict(), ensure_ascii=False) + "\n")
        return ProtocolCaptureArtifact(
            run_id=self.run_id,
            stage=entry.stage,
            artifact_type="capture-jsonl",
            relative_path=str(target.relative_to(self.root)),
            meta={
                "source": entry.source,
                "url": entry.url,
                "method": entry.method,
                "intercepted": entry.intercepted,
                "blocked": entry.blocked,
            },
        )

    def append_cdp_capture_result(
        self,
        *,
        stage: str,
        capture_result: dict[str, Any],
        source: str = "cdp_fxg_protocol_capture",
    ) -> list[ProtocolCaptureArtifact]:
        """Import sanitized CDP capture output into the protocol artifact stream."""

        artifacts: list[ProtocolCaptureArtifact] = []
        requests = capture_result.get("requests") if isinstance(capture_result, dict) else None
        if not isinstance(requests, list):
            return artifacts

        for item in requests:
            if not isinstance(item, dict):
                continue
            url_info = item.get("url") if isinstance(item.get("url"), dict) else {}
            blocked = bool(item.get("blocked"))
            entry = ProtocolCaptureEntry(
                stage=stage,
                source=source,
                method=str(item.get("method") or "GET"),
                url=str(url_info.get("sanitized") or ""),
                request_id=str(item.get("requestId") or ""),
                transport="fetch" if item.get("intercepted") else "network",
                request_body=item.get("postData"),
                response_status=item.get("status"),
                response_body_preview=str(item.get("responseBodyPreview") or ""),
                intercepted=bool(item.get("intercepted")),
                blocked=blocked,
                blocked_error_reason=str(item.get("blockedErrorReason") or ""),
                success=not blocked,
                error="request blocked before reaching server" if blocked else str(item.get("postDataError") or ""),
                meta={
                    "fetchRequestId": item.get("fetchRequestId"),
                    "resourceType": item.get("resourceType"),
                    "hasPostData": item.get("hasPostData"),
                    "mimeType": item.get("mimeType"),
                },
            )
            artifacts.append(self.append_capture(entry))
        return artifacts

    def write_json(self, stage: str, name: str, payload: Any, artifact_type: str = "json") -> ProtocolCaptureArtifact:
        safe_stage = str(stage or "unknown").strip() or "unknown"
        safe_name = str(name or "artifact").strip() or "artifact"
        target = self.root / safe_stage / f"{safe_name}.json"
        _ensure_parent(target)
        with target.open("w", encoding="utf-8", errors="replace") as fp:
            json.dump(payload, fp, ensure_ascii=False, indent=2)
        return ProtocolCaptureArtifact(
            run_id=self.run_id,
            stage=safe_stage,
            artifact_type=artifact_type,
            relative_path=str(target.relative_to(self.root)),
        )

    def write_text(self, stage: str, name: str, content: str, artifact_type: str = "text") -> ProtocolCaptureArtifact:
        safe_stage = str(stage or "unknown").strip() or "unknown"
        safe_name = str(name or "artifact").strip() or "artifact"
        target = self.root / safe_stage / f"{safe_name}.txt"
        _ensure_parent(target)
        target.write_text(str(content or ""), encoding="utf-8", errors="replace")
        return ProtocolCaptureArtifact(
            run_id=self.run_id,
            stage=safe_stage,
            artifact_type=artifact_type,
            relative_path=str(target.relative_to(self.root)),
        )

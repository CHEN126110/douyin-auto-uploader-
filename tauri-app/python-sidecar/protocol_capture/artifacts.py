from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.runtime_paths import resolve_data_file


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


class CaptureArtifactStore:
    """采集协议化调试产物存储。

    与 protocol_publish 分离，避免货源采集与抖店上传的产物目录混杂。
    """

    def __init__(self, run_id: str, root_relative_path: str = "protocol-capture") -> None:
        self.run_id = str(run_id).strip()
        if not self.run_id:
            raise ValueError("run_id is required")
        self.root = Path(resolve_data_file(Path(root_relative_path) / self.run_id))
        self.root.mkdir(parents=True, exist_ok=True)

    def write_json(self, stage: str, name: str, payload: Any, artifact_type: str = "json") -> dict[str, Any]:
        safe_stage = str(stage or "unknown").strip() or "unknown"
        safe_name = str(name or "artifact").strip() or "artifact"
        target = self.root / safe_stage / f"{safe_name}.json"
        _ensure_parent(target)
        with target.open("w", encoding="utf-8", errors="replace") as fp:
            json.dump(payload, fp, ensure_ascii=False, indent=2)
        return {
            "run_id": self.run_id,
            "stage": safe_stage,
            "artifact_type": artifact_type,
            "relative_path": str(target.relative_to(self.root)),
        }

    def write_text(self, stage: str, name: str, content: str, artifact_type: str = "text") -> dict[str, Any]:
        safe_stage = str(stage or "unknown").strip() or "unknown"
        safe_name = str(name or "artifact").strip() or "artifact"
        target = self.root / safe_stage / f"{safe_name}.txt"
        _ensure_parent(target)
        target.write_text(str(content or ""), encoding="utf-8", errors="replace")
        return {
            "run_id": self.run_id,
            "stage": safe_stage,
            "artifact_type": artifact_type,
            "relative_path": str(target.relative_to(self.root)),
        }

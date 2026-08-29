from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any


def _now_iso() -> str:
    return datetime.now().isoformat()


@dataclass(slots=True)
class ProtocolCaptureEntry:
    stage: str
    source: str
    method: str
    url: str
    request_id: str = ""
    transport: str = "network"
    request_headers: dict[str, Any] = field(default_factory=dict)
    request_body: Any = None
    response_status: int | None = None
    response_headers: dict[str, Any] = field(default_factory=dict)
    response_body: Any = None
    response_body_preview: str = ""
    elapsed_ms: float | None = None
    intercepted: bool = False
    blocked: bool = False
    blocked_error_reason: str = ""
    success: bool = True
    error: str = ""
    meta: dict[str, Any] = field(default_factory=dict)
    captured_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ProtocolCaptureArtifact:
    run_id: str
    stage: str
    artifact_type: str
    relative_path: str
    created_at: str = field(default_factory=_now_iso)
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ProtocolStageDefinition:
    key: str
    title: str
    description: str
    protocol_ready: bool = False
    depends_on: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ProtocolExecutionPlan:
    engine: str
    version: str
    goal: str
    stages: list[ProtocolStageDefinition] = field(default_factory=list)
    created_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "engine": self.engine,
            "version": self.version,
            "goal": self.goal,
            "created_at": self.created_at,
            "stages": [item.to_dict() for item in self.stages],
        }

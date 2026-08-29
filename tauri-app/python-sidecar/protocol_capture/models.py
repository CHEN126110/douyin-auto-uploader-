from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any


def _now_iso() -> str:
    return datetime.now().isoformat()


@dataclass
class CaptureStageDefinition:
    key: str
    title: str
    description: str
    protocol_ready: bool = False
    platforms: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CaptureExecutionPlan:
    engine: str
    version: str
    goal: str
    stages: list[CaptureStageDefinition] = field(default_factory=list)
    created_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "engine": self.engine,
            "version": self.version,
            "goal": self.goal,
            "created_at": self.created_at,
            "stages": [item.to_dict() for item in self.stages],
        }


@dataclass
class SourcePlatformProfile:
    key: str
    title: str
    host_patterns: list[str] = field(default_factory=list)
    state_sources: list[str] = field(default_factory=list)
    asset_sources: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

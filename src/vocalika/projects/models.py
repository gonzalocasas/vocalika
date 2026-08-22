from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


@dataclass(frozen=True)
class ProjectReference:
    title: str
    source_type: Literal["youtube", "local"]
    source_url: str | None
    original_path: str
    vocal_path: str
    instrumental_path: str | None
    duration_seconds: float
    sample_rate: int
    separation_model: str | None
    separation_cached: bool

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ProjectReference:
        return cls(**payload)


@dataclass(frozen=True)
class Take:
    id: str
    name: str
    created_at: str
    source_path: str
    isolate_performance: bool
    status: Literal["ready", "analyzing", "analyzed", "failed"] = "ready"
    analysis_path: str | None = None
    analysis_summary: dict[str, Any] | None = None
    error: str | None = None

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> Take:
        return cls(**payload)


@dataclass(frozen=True)
class Project:
    id: str
    title: str
    created_at: str
    updated_at: str
    reference: ProjectReference
    lyrics: str = ""
    trim_start_seconds: float = 0.0
    trim_end_seconds: float | None = None
    transpose_semitones: int = 0
    takes: tuple[Take, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["takes"] = [asdict(take) for take in self.takes]
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> Project:
        values = dict(payload)
        values["reference"] = ProjectReference.from_dict(values["reference"])
        values["takes"] = tuple(Take.from_dict(take) for take in values.get("takes", []))
        return cls(**values)

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlparse


@dataclass(frozen=True)
class AudioAsset:
    path: Path
    source_type: str
    title: str | None
    source_url: str | None
    duration_seconds: float | None
    sample_rate: int | None
    content_hash: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["path"] = str(self.path)
        return payload


class AudioSource(Protocol):
    def acquire(self) -> AudioAsset: ...


def is_youtube_url(value: str) -> bool:
    try:
        parsed = urlparse(value)
    except ValueError:
        return False
    host = (parsed.hostname or "").lower()
    return parsed.scheme in {"http", "https"} and (
        host == "youtu.be" or host == "youtube.com" or host.endswith(".youtube.com")
    )

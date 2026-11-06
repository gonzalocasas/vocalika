from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from platformdirs import user_cache_path


def stable_hash(payload: dict[str, Any]) -> str:
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode()).hexdigest()


@dataclass(frozen=True)
class CacheManager:
    root: Path

    @classmethod
    def default(cls) -> CacheManager:
        """The per-user cache. ``VOCALIKA_CACHE_DIR`` points elsewhere.

        The desktop app sets it so everything it writes stays in its own data
        folder, and removing that folder removes the app completely.
        """
        override = os.environ.get("VOCALIKA_CACHE_DIR")
        if override:
            return cls(Path(override).expanduser())
        return cls(user_cache_path("vocalika"))

    def source_directory(self, source_key: str) -> Path:
        return self.root / "sources" / source_key

    def normalized_path(self, content_hash: str, parameters: dict[str, Any]) -> Path:
        key = stable_hash({"content_hash": content_hash, **parameters})
        return self.root / "normalized" / f"{key}.wav"

    def separation_directory(self, content_hash: str, parameters: dict[str, Any]) -> Path:
        key = stable_hash({"content_hash": content_hash, **parameters})
        return self.root / "separation" / key

    def pitch_path(self, content_hash: str, parameters: dict[str, Any]) -> Path:
        key = stable_hash({"content_hash": content_hash, **parameters})
        return self.root / "pitch" / f"{key}.npz"

    def lyrics_timing_path(self, content_hash: str, parameters: dict[str, Any]) -> Path:
        key = stable_hash({"content_hash": content_hash, **parameters})
        return self.root / "lyrics" / f"{key}.json"

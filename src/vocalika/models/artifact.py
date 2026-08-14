from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_artifact(path: Path) -> dict[str, Any]:
    with path.expanduser().resolve().open(encoding="utf-8") as source:
        payload: dict[str, Any] = json.load(source)
    if payload.get("schema_version") != "0.1.0":
        raise ValueError(f"Unsupported analysis schema: {payload.get('schema_version')!r}")
    return payload

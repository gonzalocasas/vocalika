"""Small derived values kept next to the file they come from.

The project list and its cards need a few numbers per project and per take (a
waveform outline, a take's alignment), each derived from a file that is large
to read: a whole song's audio, a whole analysis. Deriving them on every page
load made the list slower with every song. Each is stored once, keyed by the
source file's size and modification time, so a changed source is noticed and
a moved data folder keeps its cache (moves preserve both).
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any


def _fingerprint(source: Path, parameters: dict[str, Any]) -> dict[str, Any]:
    status = source.stat()
    return {
        "name": source.name,
        "size": status.st_size,
        "mtime_ns": status.st_mtime_ns,
        **parameters,
    }


def cached[T](
    cache_file: Path,
    source: Path,
    compute: Callable[[], T],
    **parameters: Any,
) -> T:
    """``compute()``, or its stored result if ``source`` has not changed since."""
    key = _fingerprint(source, parameters)
    try:
        stored = json.loads(cache_file.read_text(encoding="utf-8"))
        if stored.get("key") == key:
            value: T = stored["value"]
            return value
    except (OSError, ValueError, KeyError, AttributeError):
        pass
    value = compute()
    try:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        temporary = cache_file.with_name(f"{cache_file.name}.{os.getpid()}.tmp")
        temporary.write_text(json.dumps({"key": key, "value": value}), encoding="utf-8")
        temporary.replace(cache_file)
    except OSError:
        # A read-only or full disk costs the speed-up, never the answer.
        pass
    return value

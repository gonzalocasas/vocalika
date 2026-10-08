from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path
from typing import Any

from vocalika.audio.sources import LocalAudioSource
from vocalika.cache.manager import CacheManager
from vocalika.lyrics.alignment import (
    ALIGNMENT_VERSION,
    LyricsAligner,
    MmsLyricsAligner,
    align_lyrics,
)
from vocalika.projects.models import Project

_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _lock_for(key: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(key, threading.Lock())


def build_lyrics_timing(
    project: Project,
    cache: CacheManager,
    *,
    aligner: LyricsAligner | None = None,
) -> dict[str, Any]:
    """Word timings for the project's lyrics against its isolated vocal.

    Timed against the untransposed vocal: transposition preserves duration,
    so the same timings hold in every key, and one alignment serves them all.

    Cached on the vocal's content and the exact lyric text, so editing a
    single word re-times the song but reopening it never does. The first
    request for a given text pays for the alignment (some seconds per song);
    a lock keeps a second request for the same text from paying again.
    """
    aligner = aligner or MmsLyricsAligner()
    if not project.lyrics.strip():
        return {"version": ALIGNMENT_VERSION, "aligner": aligner.name, "lines": []}
    asset = LocalAudioSource(Path(project.reference.vocal_path)).acquire()
    parameters = {
        "lyrics_sha256": hashlib.sha256(project.lyrics.encode()).hexdigest(),
        "aligner": aligner.name,
        "version": ALIGNMENT_VERSION,
    }
    path = cache.lyrics_timing_path(asset.content_hash, parameters)
    with _lock_for(str(path)):
        if path.is_file():
            try:
                cached: dict[str, Any] = json.loads(path.read_text())
                return cached
            except (OSError, json.JSONDecodeError):
                pass
        result = align_lyrics(asset.path, project.lyrics, aligner)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(result))
        temporary.replace(path)
        return result

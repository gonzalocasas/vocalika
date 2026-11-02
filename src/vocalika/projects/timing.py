"""One physical timeline policy for playback, preview and export.

Positive offset means the take contains extra lead-in: read take[t + offset].
DTW and vocal-envelope similarity measure performance, not capture latency.
Never use them to move recorded audio, even when their scores look confident.
"""
from __future__ import annotations

import math
from contextlib import suppress
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from vocalika.models.artifact import load_artifact
from vocalika.projects.models import Take


@dataclass(frozen=True)
class PlaybackTiming:
    offset_seconds: float
    source: str
    message: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def resolve_timing(take: Take) -> PlaybackTiming:
    captured = take.recording_offset_seconds
    if captured is not None and math.isfinite(captured):
        return PlaybackTiming(captured, "recording", "Using the recorded backing-track timing.")
    alignment: dict[str, Any] = {}
    if take.analysis_path:
        with suppress(OSError, ValueError):
            alignment = load_artifact(Path(take.analysis_path)).get("alignment", {})
    # Only direct waveform identity or a guarded spectral phrase match can
    # establish imported audio placement. Old spectral searches were unguarded.
    candidates = [{
        "method": alignment.get("global_offset_method"),
        "seconds": alignment.get("global_offset_seconds"),
        "confidence": alignment.get("global_offset_confidence"),
    }]
    if alignment.get("timing_estimator_version", 0) >= 2:
        candidates.extend(alignment.get("global_offset_candidates", []))
    for candidate in candidates:
        method = candidate.get("method")
        trusted_method = method == "pcm-cross-correlation" or (
            alignment.get("timing_estimator_version", 0) >= 2
            and method == "spectral-change-correlation"
        )
        offset = candidate.get("seconds")
        confidence = candidate.get("confidence")
        if (trusted_method and isinstance(offset, (int, float)) and math.isfinite(offset)
                and isinstance(confidence, (int, float)) and 0.9 <= confidence <= 1.0):
            return PlaybackTiming(float(offset), "audio-match", "Using a verified audio match.")
    return PlaybackTiming(
        0.0, "original",
        "Original timing preserved. Automatic alignment could not verify a recording offset.",
    )

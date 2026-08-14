from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from vocalika.analysis.cleaning import clean_pitch_track
from vocalika.analysis.pitch import PitchTrack, PyinPitchExtractor
from vocalika.cache.manager import CacheManager


@dataclass(frozen=True)
class CachedPitchTrack:
    track: PitchTrack
    cache_hit: bool


def extract_clean_pitch(
    *,
    audio_path: Path,
    content_hash: str,
    cache: CacheManager,
    extractor: PyinPitchExtractor,
    cleaning_parameters: dict[str, Any],
    pipeline_version: str,
    refresh: bool = False,
) -> CachedPitchTrack:
    parameters = {
        "pipeline_version": pipeline_version,
        "extractor": "librosa.pyin",
        "hop_length": extractor.hop_length,
        "frame_length": extractor.frame_length,
        "fmin_midi": extractor.fmin_midi,
        "fmax_midi": extractor.fmax_midi,
        "concert_pitch_hz": extractor.concert_pitch_hz,
        "cleaning": cleaning_parameters,
    }
    path = cache.pitch_path(content_hash, parameters)
    if path.is_file() and not refresh:
        with np.load(path) as arrays:
            return CachedPitchTrack(
                PitchTrack(
                    times=arrays["times"],
                    raw_frequency_hz=arrays["raw_frequency_hz"],
                    raw_midi=arrays["raw_midi"],
                    midi=arrays["midi"],
                    confidence=arrays["confidence"],
                    voiced=arrays["voiced"],
                    extractor=str(arrays["extractor"].item()),
                    sample_rate=int(arrays["sample_rate"].item()),
                    hop_length=int(arrays["hop_length"].item()),
                ),
                cache_hit=True,
            )

    track = clean_pitch_track(extractor.extract(audio_path), **cleaning_parameters)
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        path,
        times=track.times,
        raw_frequency_hz=track.raw_frequency_hz,
        raw_midi=track.raw_midi,
        midi=track.midi,
        confidence=track.confidence,
        voiced=track.voiced,
        extractor=track.extractor,
        sample_rate=track.sample_rate,
        hop_length=track.hop_length,
    )
    return CachedPitchTrack(track, cache_hit=False)

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from vocalika.audio.decode import decode_for_analysis
from vocalika.audio.sources.base import AudioAsset
from vocalika.cache.manager import CacheManager


@dataclass(frozen=True)
class NormalizedAudio:
    path: Path
    sample_rate: int
    cache_hit: bool


def normalize_for_analysis(
    asset: AudioAsset,
    cache: CacheManager,
    sample_rate: int,
    refresh: bool = False,
) -> NormalizedAudio:
    parameters = {
        "pipeline": "ffmpeg-mono-float32-v1",
        "sample_rate": sample_rate,
    }
    destination = cache.normalized_path(asset.content_hash, parameters)
    if destination.is_file() and not refresh:
        return NormalizedAudio(destination, sample_rate, cache_hit=True)
    decode_for_analysis(asset.path, destination, sample_rate=sample_rate)
    return NormalizedAudio(destination, sample_rate, cache_hit=False)

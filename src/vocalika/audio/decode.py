from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import soundfile as sf
from numpy.typing import NDArray

from vocalika.audio import media
from vocalika.audio.media import AudioDecodeError

__all__ = [
    "AudioDecodeError",
    "AudioInfo",
    "decode_for_analysis",
    "hash_file",
    "load_audio",
    "probe_audio",
]


@dataclass(frozen=True)
class AudioInfo:
    path: str
    content_hash: str
    format_name: str
    duration_seconds: float
    sample_rate: int
    channels: int
    extension: str

    def to_dict(self) -> dict[str, str | float | int]:
        return asdict(self)


def hash_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def probe_audio(path: Path) -> AudioInfo:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise AudioDecodeError(f"Audio file does not exist: {resolved}")
    info = media.probe(resolved)
    return AudioInfo(
        path=str(resolved),
        content_hash=hash_file(resolved),
        format_name=info.format_name,
        duration_seconds=info.duration_seconds,
        sample_rate=info.sample_rate,
        channels=info.channels,
        extension=resolved.suffix.lower(),
    )


def decode_for_analysis(source: Path, destination: Path, sample_rate: int = 16_000) -> Path:
    """Write `source` as a mono float32 WAV at `sample_rate`."""
    samples, rate = media.decode(source.expanduser().resolve(), sample_rate=sample_rate, mono=True)
    destination.parent.mkdir(parents=True, exist_ok=True)
    sf.write(destination, samples[:, 0], rate, subtype="FLOAT")
    return destination


def load_audio(path: Path) -> tuple[NDArray[np.float32], int]:
    samples, sample_rate = sf.read(path, dtype="float32", always_2d=False)
    if samples.ndim != 1:
        samples = np.mean(samples, axis=1, dtype=np.float32)
    return np.asarray(samples, dtype=np.float32), int(sample_rate)

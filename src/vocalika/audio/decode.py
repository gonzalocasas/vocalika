from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf
from numpy.typing import NDArray


class AudioDecodeError(RuntimeError):
    """Raised when ffmpeg or ffprobe cannot process an input."""


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

    command = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "a:0",
        "-show_entries",
        "format=format_name,duration:stream=sample_rate,channels",
        "-of",
        "json",
        str(resolved),
    ]
    try:
        result = subprocess.run(command, check=True, capture_output=True, text=True)
    except (FileNotFoundError, subprocess.CalledProcessError) as error:
        detail = getattr(error, "stderr", "") or str(error)
        raise AudioDecodeError(f"Unable to inspect {resolved.name}: {detail.strip()}") from error

    payload: dict[str, Any] = json.loads(result.stdout)
    streams = payload.get("streams", [])
    if not streams:
        raise AudioDecodeError(f"No audio stream found in {resolved.name}")
    stream = streams[0]
    format_data = payload.get("format", {})
    return AudioInfo(
        path=str(resolved),
        content_hash=hash_file(resolved),
        format_name=str(format_data.get("format_name", "unknown")),
        duration_seconds=float(format_data.get("duration", 0.0)),
        sample_rate=int(stream["sample_rate"]),
        channels=int(stream["channels"]),
        extension=resolved.suffix.lower(),
    )


def decode_for_analysis(source: Path, destination: Path, sample_rate: int = 16_000) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "ffmpeg",
        "-v",
        "error",
        "-y",
        "-i",
        str(source.expanduser().resolve()),
        "-map",
        "0:a:0",
        "-ac",
        "1",
        "-ar",
        str(sample_rate),
        "-c:a",
        "pcm_f32le",
        str(destination),
    ]
    try:
        subprocess.run(command, check=True, capture_output=True, text=True)
    except (FileNotFoundError, subprocess.CalledProcessError) as error:
        detail = getattr(error, "stderr", "") or str(error)
        raise AudioDecodeError(f"Unable to decode {source.name}: {detail.strip()}") from error
    return destination


def load_audio(path: Path) -> tuple[NDArray[np.float32], int]:
    samples, sample_rate = sf.read(path, dtype="float32", always_2d=False)
    if samples.ndim != 1:
        samples = np.mean(samples, axis=1, dtype=np.float32)
    return np.asarray(samples, dtype=np.float32), int(sample_rate)

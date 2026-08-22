from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import numpy as np
from numpy.typing import NDArray

from vocalika.audio.decode import decode_for_analysis, load_audio


def _load_waveform_audio(path: Path) -> tuple[NDArray[np.float32], int]:
    try:
        return load_audio(path)
    except (OSError, RuntimeError):
        with TemporaryDirectory(prefix="vocalika-waveform-") as raw:
            decoded = decode_for_analysis(path, Path(raw) / "decoded.wav")
            return load_audio(decoded)


def _normalized_rms_envelope(
    path: Path,
    times: NDArray[np.float64],
    *,
    window_seconds: float = 0.04,
) -> NDArray[np.float64]:
    samples, sample_rate = _load_waveform_audio(path)
    squared = np.square(samples.astype(np.float64, copy=False))
    cumulative = np.concatenate(([0.0], np.cumsum(squared)))
    centers = np.rint(times * sample_rate).astype(np.int64)
    half_window = max(1, round(window_seconds * sample_rate / 2))
    starts = np.clip(centers - half_window, 0, samples.size)
    ends = np.clip(centers + half_window, 0, samples.size)
    lengths = np.maximum(1, ends - starts)
    rms = np.sqrt((cumulative[ends] - cumulative[starts]) / lengths)
    scale = float(np.percentile(rms, 95)) if rms.size else 0.0
    if scale <= np.finfo(np.float64).eps:
        return np.zeros_like(rms)
    return np.asarray(np.clip(rms / scale, 0.0, 1.0), dtype=np.float64)


def build_aligned_waveforms(
    artifact: dict[str, Any],
    *,
    maximum_points: int = 3_000,
) -> dict[str, list[float]]:
    frames = artifact["comparison"]["frames"]
    reference_times = np.asarray(frames["reference_time"], dtype=np.float64)
    performance_times = np.asarray(frames["performance_time"], dtype=np.float64)
    if reference_times.shape != performance_times.shape:
        raise ValueError("Aligned reference and performance times have different lengths.")
    if reference_times.size > maximum_points:
        indices = np.linspace(0, reference_times.size - 1, maximum_points, dtype=np.int64)
        reference_times = reference_times[indices]
        performance_times = performance_times[indices]

    reference = artifact["reference"]
    performance = artifact["performance"]
    reference_path = Path(reference.get("analysis_audio") or reference["source"]["path"])
    performance_path = Path(performance.get("analysis_audio") or performance["source"]["path"])
    return {
        "time": reference_times.tolist(),
        "reference_amplitude": _normalized_rms_envelope(
            reference_path,
            reference_times,
        ).tolist(),
        "performance_amplitude": _normalized_rms_envelope(
            performance_path,
            performance_times,
        ).tolist(),
    }


def build_waveform_envelope(
    path: Path,
    duration_seconds: float,
    *,
    maximum_points: int = 320,
) -> dict[str, list[float]]:
    if duration_seconds <= 0:
        raise ValueError("Audio duration must be positive")
    times = np.linspace(0.0, duration_seconds, maximum_points, dtype=np.float64)
    return {
        "time": times.tolist(),
        "amplitude": _normalized_rms_envelope(path, times).tolist(),
    }

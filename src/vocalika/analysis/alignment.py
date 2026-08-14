from __future__ import annotations

from dataclasses import dataclass

import librosa
import numpy as np
from numpy.typing import NDArray

from vocalika.analysis.pitch import PitchTrack

FloatArray = NDArray[np.float64]


class AlignmentError(RuntimeError):
    """Raised when pitch tracks do not contain enough information to align."""


@dataclass(frozen=True)
class SampledTrack:
    times: FloatArray
    midi: FloatArray
    confidence: FloatArray
    voiced: NDArray[np.bool_]


@dataclass(frozen=True)
class AlignmentResult:
    reference_indices: NDArray[np.int64]
    performance_indices: NDArray[np.int64]
    reference: SampledTrack
    performance: SampledTrack
    frames_per_second: float


def _sample_track(track: PitchTrack, frames_per_second: float) -> SampledTrack:
    step = 1.0 / frames_per_second
    times = np.arange(0.0, track.duration_seconds + step / 2.0, step, dtype=np.float64)
    valid = np.isfinite(track.midi)
    if np.count_nonzero(valid) < 10:
        raise AlignmentError("Pitch track contains too few reliable voiced frames")
    midi = np.interp(times, track.times[valid], track.midi[valid])
    confidence = np.interp(times, track.times, track.confidence)
    voiced_numeric = np.interp(times, track.times, track.voiced.astype(np.float64))
    voiced = voiced_numeric >= 0.5
    confidence = confidence * voiced
    return SampledTrack(times=times, midi=midi, confidence=confidence, voiced=voiced)


def _features(track: SampledTrack) -> FloatArray:
    voiced_pitch = track.midi[track.voiced]
    center = float(np.median(voiced_pitch)) if voiced_pitch.size else float(np.median(track.midi))
    relative_pitch = np.clip(track.midi - center, -24.0, 24.0)
    derivative = np.gradient(relative_pitch)
    confidence_weight = 0.2 + 0.8 * track.confidence
    return np.vstack(
        (
            relative_pitch * confidence_weight / 6.0,
            np.clip(derivative, -6.0, 6.0) / 3.0,
            track.confidence * 2.0,
        )
    )


def align_pitch_tracks(
    reference: PitchTrack,
    performance: PitchTrack,
    frames_per_second: float = 10.0,
    band_radius: float = 0.2,
) -> AlignmentResult:
    sampled_reference = _sample_track(reference, frames_per_second)
    sampled_performance = _sample_track(performance, frames_per_second)
    _, path = librosa.sequence.dtw(
        X=_features(sampled_reference),
        Y=_features(sampled_performance),
        metric="euclidean",
        global_constraints=True,
        band_rad=band_radius,
        backtrack=True,
    )
    path = np.asarray(path[::-1], dtype=np.int64)
    return AlignmentResult(
        reference_indices=path[:, 0],
        performance_indices=path[:, 1],
        reference=sampled_reference,
        performance=sampled_performance,
        frames_per_second=frames_per_second,
    )

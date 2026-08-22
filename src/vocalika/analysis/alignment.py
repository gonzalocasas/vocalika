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
    global_offset_seconds: float | None = None
    effective_temporal_consistency_weight: float = 0.0
    used_subsequence: bool = False


def _sample_track(
    track: PitchTrack,
    frames_per_second: float,
    *,
    start_time: float = 0.0,
) -> SampledTrack:
    step = 1.0 / frames_per_second
    times = np.arange(
        start_time,
        track.duration_seconds + step / 2.0,
        step,
        dtype=np.float64,
    )
    valid = np.isfinite(track.midi)
    if np.count_nonzero(valid) < 10:
        raise AlignmentError("Pitch track contains too few reliable voiced frames")
    midi = np.interp(times, track.times[valid], track.midi[valid])
    confidence = np.interp(times, track.times, track.confidence)
    voiced_numeric = np.interp(times, track.times, track.voiced.astype(np.float64))
    voiced = voiced_numeric >= 0.5
    return SampledTrack(times=times, midi=midi, confidence=confidence, voiced=voiced)


def _features(track: SampledTrack) -> FloatArray:
    voiced_pitch = track.midi[track.voiced]
    center = float(np.median(voiced_pitch)) if voiced_pitch.size else float(np.median(track.midi))
    relative_pitch = np.clip(track.midi - center, -24.0, 24.0)
    derivative = np.gradient(relative_pitch)
    confidence_weight = np.clip(track.confidence, 0.0, 1.0) * track.voiced
    # Melodic movement is transposition-invariant and is the strongest cue for
    # pairing corresponding notes. Static pitch position remains a weaker cue
    # so differing note durations cannot pull DTW toward a neighboring note.
    # Interpolated values in unvoiced gaps are a sampling implementation detail
    # and must contribute no pitch or movement evidence to the warp path.
    return np.vstack(
        (
            relative_pitch * confidence_weight / 12.0,
            np.clip(derivative, -6.0, 6.0) * confidence_weight,
            confidence_weight * 2.0,
        )
    )


def align_pitch_tracks(
    reference: PitchTrack,
    performance: PitchTrack,
    frames_per_second: float = 10.0,
    band_radius: float = 0.2,
    global_offset_seconds: float | None = None,
    temporal_consistency_weight: float = 0.1,
    allow_subsequence: bool = False,
) -> AlignmentResult:
    reference_start = max(0.0, -(global_offset_seconds or 0.0))
    performance_start = max(0.0, global_offset_seconds or 0.0)
    sampled_reference = _sample_track(
        reference,
        frames_per_second,
        start_time=reference_start,
    )
    sampled_performance = _sample_track(
        performance,
        frames_per_second,
        start_time=performance_start,
    )
    reference_features = _features(sampled_reference)
    performance_features = _features(sampled_performance)
    shared_duration = min(
        float(sampled_reference.times[-1] - sampled_reference.times[0]),
        float(sampled_performance.times[-1] - sampled_performance.times[0]),
    )
    # Short phrases need freedom to express tempo differences. Ramp this cue
    # in only for longer material, where small local ambiguities can otherwise
    # accumulate into large whole-song timing errors.
    long_form_scale = float(np.clip((shared_duration - 30.0) / 90.0, 0.0, 1.0))
    effective_temporal_weight = temporal_consistency_weight * long_form_scale
    if effective_temporal_weight > 0.0:
        # A weak absolute-time cue prevents sparse or inaccurate contours from
        # accumulating implausible multi-second warps. Compensate a trusted
        # global offset so delayed but otherwise identical tracks still pair.
        offset = global_offset_seconds or 0.0
        reference_features = np.vstack(
            (
                reference_features,
                sampled_reference.times * effective_temporal_weight,
            )
        )
        performance_features = np.vstack(
            (
                performance_features,
                (sampled_performance.times - offset) * effective_temporal_weight,
            )
        )
    # A substantially shorter performance can be only a portion of the
    # reference. Subsequence DTW consumes it completely while allowing its
    # match to end before the reference does. Similar-length tracks retain
    # endpoint-constrained DTW so modest tempo differences do not lose notes.
    length_ratio = max(reference_features.shape[1], performance_features.shape[1]) / min(
        reference_features.shape[1], performance_features.shape[1]
    )
    use_subsequence = allow_subsequence and length_ratio >= 1.5
    if not use_subsequence:
        _, raw_path = librosa.sequence.dtw(
            X=reference_features,
            Y=performance_features,
            metric="euclidean",
            global_constraints=True,
            band_rad=band_radius,
            backtrack=True,
        )
        path = np.asarray(raw_path[::-1], dtype=np.int64)
    elif reference_features.shape[1] <= performance_features.shape[1]:
        _, raw_path = librosa.sequence.dtw(
            X=reference_features,
            Y=performance_features,
            metric="euclidean",
            subseq=True,
            backtrack=True,
        )
        path = np.asarray(raw_path[::-1], dtype=np.int64)
    else:
        _, raw_path = librosa.sequence.dtw(
            X=performance_features,
            Y=reference_features,
            metric="euclidean",
            subseq=True,
            backtrack=True,
        )
        path = np.asarray(raw_path[::-1], dtype=np.int64)[:, ::-1]
    return AlignmentResult(
        reference_indices=path[:, 0],
        performance_indices=path[:, 1],
        reference=sampled_reference,
        performance=sampled_performance,
        frames_per_second=frames_per_second,
        global_offset_seconds=global_offset_seconds,
        effective_temporal_consistency_weight=effective_temporal_weight,
        used_subsequence=use_subsequence,
    )

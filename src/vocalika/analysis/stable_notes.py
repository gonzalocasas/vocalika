from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
from numpy.typing import NDArray

from vocalika.analysis.alignment import AlignmentResult
from vocalika.analysis.comparison import ComparisonResult

FloatArray = NDArray[np.float64]


@dataclass(frozen=True)
class StablePitchRegion:
    reference_start: float
    reference_end: float
    performance_start: float
    performance_end: float
    duration_seconds: float
    reference_center_midi: float
    performance_center_midi: float
    error_cents: float
    relative_error_cents: float
    reference_span_cents: float
    confidence: float

    def to_dict(self) -> dict[str, float]:
        return asdict(self)


@dataclass(frozen=True)
class StablePitchSummary:
    regions: tuple[StablePitchRegion, ...]
    pitch_center_mae_cents: float | None
    relative_pitch_center_mae_cents: float | None
    duration_weighted_mae_cents: float | None
    relative_duration_weighted_mae_cents: float | None
    total_stable_seconds: float


def _stable_frame_mask(
    times: FloatArray,
    pitch: FloatArray,
    available: NDArray[np.bool_],
    *,
    frames_per_second: float,
    window_seconds: float,
    max_span_cents: float,
    max_slope_cents_per_second: float,
    minimum_voiced_fraction: float,
) -> NDArray[np.bool_]:
    radius = max(2, round(window_seconds * frames_per_second / 2.0))
    minimum_points = radius + 2
    stable = np.zeros(times.size, dtype=np.bool_)
    for index in range(times.size):
        start = max(0, index - radius)
        end = min(times.size, index + radius + 1)
        local_available = available[start:end]
        if np.mean(local_available) < minimum_voiced_fraction:
            continue
        local_times = times[start:end][local_available]
        local_pitch = pitch[start:end][local_available]
        if local_times.size < minimum_points:
            continue
        expected_step = 1.0 / frames_per_second
        if np.max(np.diff(local_times)) > expected_step * 2.6:
            continue
        span_cents = 100.0 * (np.percentile(local_pitch, 90.0) - np.percentile(local_pitch, 10.0))
        slope_midi_per_second, _ = np.polyfit(local_times, local_pitch, deg=1)
        if (
            span_cents <= max_span_cents
            and abs(100.0 * slope_midi_per_second) <= max_slope_cents_per_second
        ):
            stable[index] = True
    return stable


def analyze_stable_pitch_centers(
    alignment: AlignmentResult,
    comparison: ComparisonResult,
    *,
    frames_per_second: float,
    window_seconds: float = 0.7,
    max_span_cents: float = 120.0,
    max_slope_cents_per_second: float = 60.0,
    minimum_duration_seconds: float = 0.5,
    minimum_voiced_window_fraction: float = 0.7,
    minimum_matched_region_fraction: float = 0.4,
    minimum_alignment_duration_ratio: float = 0.35,
    maximum_alignment_duration_ratio: float = 2.5,
    confidence_threshold: float = 0.55,
) -> StablePitchSummary:
    reference = alignment.reference
    reference_times = reference.times
    reference_midi = reference.midi
    reference_available = reference.voiced & (reference.confidence >= confidence_threshold)
    stable = _stable_frame_mask(
        reference_times,
        reference_midi,
        reference_available,
        frames_per_second=frames_per_second,
        window_seconds=window_seconds,
        max_span_cents=max_span_cents,
        max_slope_cents_per_second=max_slope_cents_per_second,
        minimum_voiced_fraction=minimum_voiced_window_fraction,
    )
    stable_indices = np.flatnonzero(stable)
    if stable_indices.size == 0:
        return StablePitchSummary((), None, None, None, None, 0.0)

    expected_step = 1.0 / frames_per_second
    split_points = np.flatnonzero(
        (np.diff(stable_indices) > 1)
        | (np.diff(reference_times[stable_indices]) > expected_step * 1.6)
    )
    groups = np.split(stable_indices, split_points + 1)
    regions: list[StablePitchRegion] = []
    for indices in groups:
        duration = float(reference_times[indices[-1]] - reference_times[indices[0]] + expected_step)
        if duration < minimum_duration_seconds:
            continue
        reference_start = float(reference_times[indices[0]])
        reference_end = float(reference_times[indices[-1]] + expected_step)
        matched = (
            comparison.valid
            & (comparison.reference_times >= reference_start)
            & (comparison.reference_times < reference_end)
        )
        matched_reference_times = np.unique(comparison.reference_times[matched])
        if matched_reference_times.size / indices.size < minimum_matched_region_fraction:
            continue
        performance_times = comparison.performance_times[matched]
        performance_midi = comparison.performance_midi[matched]
        confidence = comparison.confidence[matched]
        performance_duration = float(
            np.max(performance_times) - np.min(performance_times) + expected_step
        )
        duration_ratio = performance_duration / duration
        if not (
            minimum_alignment_duration_ratio <= duration_ratio <= maximum_alignment_duration_ratio
        ):
            continue
        reference_center = float(np.median(reference_midi[indices]))
        performance_center = float(np.median(performance_midi))
        error_cents = 100.0 * (performance_center - reference_center)
        regions.append(
            StablePitchRegion(
                reference_start=reference_start,
                reference_end=reference_end,
                performance_start=float(np.min(performance_times)),
                performance_end=float(np.max(performance_times) + expected_step),
                duration_seconds=duration,
                reference_center_midi=reference_center,
                performance_center_midi=performance_center,
                error_cents=error_cents,
                relative_error_cents=error_cents - comparison.global_bias_cents,
                reference_span_cents=float(
                    100.0
                    * (
                        np.percentile(reference_midi[indices], 90.0)
                        - np.percentile(reference_midi[indices], 10.0)
                    )
                ),
                confidence=float(np.median(confidence)),
            )
        )

    if not regions:
        return StablePitchSummary((), None, None, None, None, 0.0)
    errors = np.asarray([abs(region.error_cents) for region in regions])
    relative_errors = np.asarray([abs(region.relative_error_cents) for region in regions])
    durations = np.asarray([region.duration_seconds for region in regions])
    return StablePitchSummary(
        regions=tuple(regions),
        pitch_center_mae_cents=float(np.mean(errors)),
        relative_pitch_center_mae_cents=float(np.mean(relative_errors)),
        duration_weighted_mae_cents=float(np.average(errors, weights=durations)),
        relative_duration_weighted_mae_cents=float(np.average(relative_errors, weights=durations)),
        total_stable_seconds=float(np.sum(durations)),
    )

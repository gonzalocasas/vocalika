from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from vocalika.analysis.alignment import AlignmentResult

FloatArray = NDArray[np.float64]


@dataclass(frozen=True)
class ComparisonResult:
    reference_times: FloatArray
    performance_times: FloatArray
    reference_midi: FloatArray
    performance_midi: FloatArray
    confidence: FloatArray
    valid: NDArray[np.bool_]
    absolute_error_cents: FloatArray
    relative_error_cents: FloatArray
    global_bias_cents: float
    mean_absolute_error_cents: float
    within_25_percent: float
    within_50_percent: float


def compare_alignment(
    alignment: AlignmentResult,
    confidence_threshold: float = 0.55,
) -> ComparisonResult:
    ref = alignment.reference
    perf = alignment.performance
    ref_indices = alignment.reference_indices
    perf_indices = alignment.performance_indices
    ref_midi = ref.midi[ref_indices]
    perf_midi = perf.midi[perf_indices]
    confidence = np.minimum(ref.confidence[ref_indices], perf.confidence[perf_indices])
    valid = (
        ref.voiced[ref_indices] & perf.voiced[perf_indices] & (confidence >= confidence_threshold)
    )
    signed_error = 100.0 * (perf_midi - ref_midi)
    if not np.any(valid):
        raise ValueError("No mutually voiced, confident frames remain after alignment")
    bias = float(np.median(signed_error[valid]))
    relative_error = signed_error - bias
    absolute_values = np.abs(signed_error[valid])
    return ComparisonResult(
        reference_times=ref.times[ref_indices],
        performance_times=perf.times[perf_indices],
        reference_midi=ref_midi,
        performance_midi=perf_midi,
        confidence=confidence,
        valid=valid,
        absolute_error_cents=signed_error,
        relative_error_cents=relative_error,
        global_bias_cents=bias,
        mean_absolute_error_cents=float(np.mean(absolute_values)),
        within_25_percent=float(100.0 * np.mean(absolute_values <= 25.0)),
        within_50_percent=float(100.0 * np.mean(absolute_values <= 50.0)),
    )

from __future__ import annotations

import numpy as np

from vocalika.analysis.alignment import align_pitch_tracks
from vocalika.analysis.comparison import compare_alignment
from vocalika.analysis.pitch import PitchTrack


def make_track(*, pitch_shift: float = 0.0, delay: float = 0.0) -> PitchTrack:
    frame_rate = 100
    duration = 8.0 + delay
    times = np.arange(0.0, duration, 1.0 / frame_rate)
    phrase_time = times - delay
    voiced = (phrase_time >= 0.0) & (phrase_time < 8.0)
    midi = np.full(times.shape, np.nan)
    phrase = np.select(
        [phrase_time < 2.0, phrase_time < 4.0, phrase_time < 6.0],
        [60.0, 64.0, 67.0],
        default=65.0,
    )
    midi[voiced] = phrase[voiced] + pitch_shift
    confidence = voiced.astype(np.float64) * 0.99
    frequency = np.full(times.shape, np.nan)
    frequency[voiced] = 440.0 * 2.0 ** ((midi[voiced] - 69.0) / 12.0)
    return PitchTrack(
        times=times,
        raw_frequency_hz=frequency,
        raw_midi=midi.copy(),
        midi=midi,
        confidence=confidence,
        voiced=voiced,
        extractor="synthetic",
        sample_rate=16_000,
        hop_length=160,
    )


def test_recovers_global_pitch_shift() -> None:
    reference = make_track()
    performance = make_track(pitch_shift=0.5)

    comparison = compare_alignment(align_pitch_tracks(reference, performance))

    assert comparison.global_bias_cents == 50.0
    assert np.max(np.abs(comparison.relative_error_cents[comparison.valid])) < 0.01


def test_alignment_recovers_start_delay() -> None:
    reference = make_track()
    performance = make_track(delay=0.15)

    comparison = compare_alignment(align_pitch_tracks(reference, performance))
    mapping_offset = comparison.performance_times - comparison.reference_times
    interior = comparison.valid & (comparison.reference_times > 0.5)

    np.testing.assert_allclose(np.median(mapping_offset[interior]), 0.15, atol=0.06)

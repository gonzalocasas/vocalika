from __future__ import annotations

import numpy as np
import pytest

from vocalika.analysis.alignment import align_pitch_tracks
from vocalika.analysis.cleaning import clean_pitch_track
from vocalika.analysis.comparison import compare_alignment
from vocalika.analysis.pitch import PitchTrack


def make_track(
    *,
    pitch_shift: float = 0.0,
    delay: float = 0.0,
    time_stretch: float = 1.0,
    local_shift: float = 0.0,
    drift: float = 0.0,
) -> PitchTrack:
    frame_rate = 100
    duration = 8.0 * time_stretch + delay
    times = np.arange(0.0, duration, 1.0 / frame_rate)
    phrase_time = (times - delay) / time_stretch
    voiced = (phrase_time >= 0.0) & (phrase_time < 8.0)
    midi = np.full(times.shape, np.nan)
    phrase = np.select(
        [phrase_time < 2.0, phrase_time < 4.0, phrase_time < 6.0],
        [60.0, 64.0, 67.0],
        default=65.0,
    )
    midi[voiced] = phrase[voiced] + pitch_shift
    local_region = voiced & (phrase_time >= 2.0) & (phrase_time < 4.0)
    midi[local_region] += local_shift
    drift_region = voiced & (phrase_time >= 6.0)
    midi[drift_region] += drift * (phrase_time[drift_region] - 6.0) / 2.0
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


@pytest.mark.parametrize("pitch_shift", [0.5, -0.25])
def test_recovers_global_pitch_shift(pitch_shift: float) -> None:
    reference = make_track()
    performance = make_track(pitch_shift=pitch_shift)

    comparison = compare_alignment(align_pitch_tracks(reference, performance))

    assert comparison.global_bias_cents == pytest.approx(pitch_shift * 100.0)
    assert np.max(np.abs(comparison.relative_error_cents[comparison.valid])) < 0.01


def test_alignment_recovers_start_delay() -> None:
    reference = make_track()
    performance = make_track(delay=0.15)

    comparison = compare_alignment(align_pitch_tracks(reference, performance))
    mapping_offset = comparison.performance_times - comparison.reference_times
    interior = comparison.valid & (comparison.reference_times > 0.5)

    np.testing.assert_allclose(np.median(mapping_offset[interior]), 0.15, atol=0.06)


def test_recovers_local_semitone_shift() -> None:
    comparison = compare_alignment(align_pitch_tracks(make_track(), make_track(local_shift=1.0)))
    region = (
        comparison.valid & (comparison.reference_times >= 2.2) & (comparison.reference_times < 3.8)
    )

    assert np.median(comparison.absolute_error_cents[region]) == pytest.approx(100.0, abs=5.0)


def test_recovers_gradual_pitch_drift() -> None:
    comparison = compare_alignment(align_pitch_tracks(make_track(), make_track(drift=-0.5)))
    region = (
        comparison.valid & (comparison.reference_times >= 6.2) & (comparison.reference_times < 7.8)
    )
    slope, _ = np.polyfit(
        comparison.reference_times[region],
        comparison.absolute_error_cents[region],
        deg=1,
    )

    assert slope == pytest.approx(-25.0, abs=5.0)


def test_recovers_modest_time_stretch() -> None:
    comparison = compare_alignment(align_pitch_tracks(make_track(), make_track(time_stretch=1.05)))
    region = (
        comparison.valid & (comparison.reference_times >= 0.5) & (comparison.reference_times < 7.5)
    )
    slope, _ = np.polyfit(
        comparison.reference_times[region],
        comparison.performance_times[region],
        deg=1,
    )

    assert slope == pytest.approx(1.05, abs=0.02)


def test_repairs_brief_octave_detector_error() -> None:
    track = make_track()
    glitch = slice(300, 303)
    track.raw_midi[glitch] += 12.0
    track.raw_frequency_hz[glitch] *= 2.0

    cleaned = clean_pitch_track(track)

    np.testing.assert_allclose(cleaned.midi[glitch], 64.0, atol=0.01)

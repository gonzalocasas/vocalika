from __future__ import annotations

import numpy as np
import pytest

from vocalika.analysis.alignment import align_pitch_tracks
from vocalika.analysis.cleaning import clean_pitch_track
from vocalika.analysis.comparison import compare_alignment
from vocalika.analysis.pitch import PitchTrack
from vocalika.analysis.stable_notes import analyze_stable_pitch_centers


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


def make_variable_duration_track(
    notes: list[float],
    durations: list[int],
    *,
    pitch_shift: float = 0.0,
) -> PitchTrack:
    midi = np.repeat(np.asarray(notes, dtype=np.float64), durations) + pitch_shift
    times = np.arange(midi.size, dtype=np.float64) / 10.0
    frequency = 440.0 * 2.0 ** ((midi - 69.0) / 12.0)
    return PitchTrack(
        times=times,
        raw_frequency_hz=frequency,
        raw_midi=midi.copy(),
        midi=midi,
        confidence=np.ones(midi.size, dtype=np.float64),
        voiced=np.ones(midi.size, dtype=np.bool_),
        extractor="synthetic",
        sample_rate=100,
        hop_length=10,
    )


def make_sparse_long_track(
    duration: float,
    *,
    seed: int,
    is_reference: bool,
) -> PitchTrack:
    random = np.random.default_rng(seed)
    frame_rate = 10
    frame_count = round(duration * frame_rate)
    times = np.arange(frame_count, dtype=np.float64) / frame_rate
    note_count = (frame_count + frame_rate - 1) // frame_rate
    notes = np.repeat(
        random.choice([57.0, 59.0, 60.0, 62.0, 64.0, 65.0, 67.0], note_count),
        frame_rate,
    )[:frame_count]
    phrase_activity = (
        (np.mod(times, 8.0) < 6.0) & ~((times >= 85.0) & (times < 100.0)) & (times < 185.0)
    )
    retention_probability = 0.16 if is_reference else 0.55
    voiced = phrase_activity & (random.random(frame_count) < retention_probability)
    if is_reference:
        voiced |= (times >= 195.0) & (times < 203.0) & (random.random(frame_count) < 0.2)
    midi = np.full(frame_count, np.nan)
    midi[voiced] = notes[voiced]
    frequency = np.full(frame_count, np.nan)
    frequency[voiced] = 440.0 * 2.0 ** ((midi[voiced] - 69.0) / 12.0)
    return PitchTrack(
        times=times,
        raw_frequency_hz=frequency,
        raw_midi=midi.copy(),
        midi=midi,
        confidence=voiced.astype(np.float64),
        voiced=voiced,
        extractor="synthetic",
        sample_rate=100,
        hop_length=10,
    )


@pytest.mark.parametrize("pitch_shift", [0.5, -0.25])
def test_recovers_global_pitch_shift(pitch_shift: float) -> None:
    reference = make_track()
    performance = make_track(pitch_shift=pitch_shift)

    comparison = compare_alignment(align_pitch_tracks(reference, performance))

    assert comparison.global_bias_cents == pytest.approx(pitch_shift * 100.0)
    assert np.max(np.abs(comparison.relative_error_cents[comparison.valid])) < 0.01
    assert comparison.relative_mean_absolute_error_cents < 0.01
    assert comparison.relative_within_15_percent == 100.0


def test_melodic_movement_prevents_neighboring_notes_from_being_paired() -> None:
    notes = [57.0, 58.0, 61.0, 62.0, 63.0, 60.0, 61.0, 59.0, 57.0]
    reference = make_variable_duration_track(
        notes,
        [11, 11, 10, 7, 15, 4, 7, 4, 7],
    )
    performance = make_variable_duration_track(
        notes,
        [15, 7, 14, 9, 12, 8, 6, 12, 15],
        pitch_shift=12.0,
    )

    comparison = compare_alignment(align_pitch_tracks(reference, performance))

    assert comparison.relative_mean_absolute_error_cents < 5.0
    assert comparison.relative_within_50_percent > 95.0


def test_sparse_long_tracks_do_not_accumulate_warp_before_an_unmatched_tail() -> None:
    reference = make_sparse_long_track(234.0, seed=0, is_reference=True)
    performance = make_sparse_long_track(197.0, seed=1, is_reference=False)

    alignment = align_pitch_tracks(reference, performance)
    reference_times = alignment.reference.times[alignment.reference_indices]
    performance_times = alignment.performance.times[alignment.performance_indices]

    for anchor in (30.0, 60.0, 80.0, 100.0, 120.0, 150.0, 180.0):
        nearby = np.abs(reference_times - anchor) <= 0.5
        assert np.median(performance_times[nearby]) == pytest.approx(anchor, abs=2.0)


def test_partial_performance_does_not_stretch_across_reference_tail() -> None:
    notes = [60.0, 62.0, 65.0, 61.0, 67.0, 64.0, 69.0, 63.0, 58.0, 66.0]
    reference = make_variable_duration_track(notes, [10] * len(notes))
    performance = make_variable_duration_track(notes[:5], [10] * 5)

    alignment = align_pitch_tracks(reference, performance, allow_subsequence=True)
    aligned_reference_times = alignment.reference.times[alignment.reference_indices]
    aligned_performance_times = alignment.performance.times[alignment.performance_indices]

    assert aligned_performance_times[-1] == pytest.approx(4.9, abs=0.2)
    assert aligned_reference_times[-1] == pytest.approx(4.0, abs=0.3)
    assert aligned_reference_times[-1] < reference.duration_seconds - 4.0
    assert alignment.used_subsequence is True


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


def test_stable_pitch_centers_recover_global_shift() -> None:
    alignment = align_pitch_tracks(make_track(), make_track(pitch_shift=0.5))
    comparison = compare_alignment(alignment)

    stable = analyze_stable_pitch_centers(alignment, comparison, frames_per_second=10.0)

    assert len(stable.regions) >= 4
    assert stable.pitch_center_mae_cents == pytest.approx(50.0, abs=2.0)
    assert stable.relative_pitch_center_mae_cents == pytest.approx(0.0, abs=2.0)


def test_stable_pitch_center_metric_excludes_transition_only_errors() -> None:
    reference = make_track()
    performance = make_track()
    for boundary in (2.0, 4.0, 6.0):
        transition = np.abs(performance.times - boundary) <= 0.2
        performance.midi[transition] += 1.5
        performance.raw_midi[transition] += 1.5
    alignment = align_pitch_tracks(reference, performance)
    comparison = compare_alignment(alignment)

    stable = analyze_stable_pitch_centers(alignment, comparison, frames_per_second=10.0)

    assert stable.pitch_center_mae_cents is not None
    assert stable.pitch_center_mae_cents < comparison.mean_absolute_error_cents

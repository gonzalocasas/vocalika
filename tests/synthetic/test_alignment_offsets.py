from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from vocalika.analysis.alignment import align_pitch_tracks
from vocalika.analysis.comparison import compare_alignment
from vocalika.analysis.offset import (
    GlobalOffsetEstimate,
    estimate_global_offset,
    estimate_spectral_change_offset,
    estimate_vocal_envelope_offset,
    select_global_offset,
)
from vocalika.analysis.pitch import PitchTrack


def _melody_audio(sample_rate: int) -> np.ndarray:
    parts: list[np.ndarray] = []
    for midi in (60.0, 62.0, 64.0, 67.0):
        times = np.arange(round(0.75 * sample_rate), dtype=np.float64) / sample_rate
        frequency = 440.0 * 2.0 ** ((midi - 69.0) / 12.0)
        tone = 0.24 * np.sin(2.0 * np.pi * frequency * times)
        tone += 0.07 * np.sin(4.0 * np.pi * frequency * times)
        fade_frames = round(0.03 * sample_rate)
        tone[:fade_frames] *= np.linspace(0.0, 1.0, fade_frames)
        tone[-fade_frames:] *= np.linspace(1.0, 0.0, fade_frames)
        parts.extend((tone, np.zeros(round(0.08 * sample_rate))))
    return np.concatenate(parts).astype(np.float32)


def _write_delayed_audio_pair(
    directory: Path,
    offset_seconds: float,
) -> tuple[Path, Path]:
    sample_rate = 4_000
    melody = _melody_audio(sample_rate)
    silence = np.zeros(round(abs(offset_seconds) * sample_rate), dtype=np.float32)
    if offset_seconds >= 0:
        reference = melody
        performance = np.concatenate((silence, melody))
        assert np.array_equal(reference, performance[silence.size :])
    else:
        reference = np.concatenate((silence, melody))
        performance = melody
        assert np.array_equal(reference[silence.size :], performance)
    reference_path = directory / "reference.wav"
    performance_path = directory / "performance.wav"
    sf.write(reference_path, reference, sample_rate, subtype="FLOAT")
    sf.write(performance_path, performance, sample_rate, subtype="FLOAT")
    return reference_path, performance_path


def _pitch_track(delay_seconds: float) -> PitchTrack:
    frame_rate = 100
    phrase_duration = 4 * (0.75 + 0.08)
    times = np.arange(0.0, phrase_duration + delay_seconds, 1.0 / frame_rate)
    phrase_time = times - delay_seconds
    note_index = np.floor(phrase_time / 0.83).astype(np.int64)
    within_note = np.mod(phrase_time, 0.83)
    voiced = (
        (phrase_time >= 0.0)
        & (phrase_time < phrase_duration)
        & (note_index < 4)
        & (within_note < 0.75)
    )
    notes = np.asarray((60.0, 62.0, 64.0, 67.0))
    midi = np.full(times.shape, np.nan)
    midi[voiced] = notes[note_index[voiced]]
    frequency = np.full(times.shape, np.nan)
    frequency[voiced] = 440.0 * 2.0 ** ((midi[voiced] - 69.0) / 12.0)
    return PitchTrack(
        times=times,
        raw_frequency_hz=frequency,
        raw_midi=midi.copy(),
        midi=midi,
        confidence=voiced.astype(np.float64) * 0.99,
        voiced=voiced,
        extractor="synthetic",
        sample_rate=16_000,
        hop_length=160,
    )


def test_vocal_envelope_locates_a_partial_take_inside_a_full_reference(tmp_path: Path) -> None:
    sample_rate = 4_000
    times = np.arange(12 * sample_rate, dtype=np.float64) / sample_rate
    envelope = np.zeros_like(times)
    for start, duration, amplitude in (
        (1.0, 0.8, 0.3),
        (3.0, 1.4, 0.8),
        (5.5, 0.6, 0.5),
        (7.0, 1.8, 1.0),
        (10.0, 0.7, 0.4),
    ):
        active = (times >= start) & (times < start + duration)
        envelope[active] = amplitude
    reference = envelope * np.sin(2.0 * np.pi * 220.0 * times)
    partial_start = 4.0
    partial_duration = 6.0
    partial_slice = slice(
        round(partial_start * sample_rate),
        round((partial_start + partial_duration) * sample_rate),
    )
    performance_times = np.arange(round(partial_duration * sample_rate)) / sample_rate
    performance = envelope[partial_slice] * np.sin(2.0 * np.pi * 330.0 * performance_times)
    reference_path = tmp_path / "reference.wav"
    performance_path = tmp_path / "partial.wav"
    sf.write(reference_path, reference.astype(np.float32), sample_rate, subtype="FLOAT")
    sf.write(performance_path, performance.astype(np.float32), sample_rate, subtype="FLOAT")

    estimate = estimate_vocal_envelope_offset(reference_path, performance_path)

    assert estimate.seconds == pytest.approx(-partial_start, abs=0.3)
    assert estimate.confidence > 0.9
    assert estimate.method == "smoothed-vocal-envelope-correlation"


def test_spectral_changes_distinguish_repeated_energy_patterns(tmp_path: Path) -> None:
    sample_rate = 4_000

    def phrase(frequencies: tuple[float, ...]) -> np.ndarray:
        parts: list[np.ndarray] = []
        for frequency in frequencies:
            times = np.arange(round(0.75 * sample_rate)) / sample_rate
            tone = 0.3 * np.sin(2.0 * np.pi * frequency * times)
            tone += 0.1 * np.sin(4.0 * np.pi * frequency * times)
            fade_frames = round(0.02 * sample_rate)
            tone[:fade_frames] *= np.linspace(0.0, 1.0, fade_frames)
            tone[-fade_frames:] *= np.linspace(1.0, 0.0, fade_frames)
            parts.extend((tone, np.zeros(round(0.25 * sample_rate))))
        return np.concatenate(parts).astype(np.float32)

    performance = phrase((220.0, 330.0, 440.0, 275.0))
    repeated_energy_decoy = phrase((220.0, 440.0, 330.0, 275.0))
    reference = np.concatenate(
        (
            np.zeros(sample_rate),
            performance,
            np.zeros(2 * sample_rate),
            repeated_energy_decoy,
            np.zeros(sample_rate),
        )
    ).astype(np.float32)
    reference_path = tmp_path / "reference-with-repeated-pattern.wav"
    performance_path = tmp_path / "performance.wav"
    sf.write(reference_path, reference, sample_rate, subtype="FLOAT")
    sf.write(performance_path, performance, sample_rate, subtype="FLOAT")

    estimate = estimate_spectral_change_offset(reference_path, performance_path)

    assert estimate.seconds == pytest.approx(-1.0, abs=0.2)
    assert estimate.confidence > 0.9
    assert estimate.method == "spectral-change-correlation"


def test_spectral_match_wins_over_a_later_repeated_melody_envelope() -> None:
    candidates = [
        GlobalOffsetEstimate(0.01, 0.02, "pcm-cross-correlation"),
        GlobalOffsetEstimate(-2.7, 0.96, "spectral-change-correlation"),
        GlobalOffsetEstimate(-90.6, 0.99, "smoothed-vocal-envelope-correlation"),
    ]

    selected = select_global_offset(candidates, minimum_confidence=0.9)

    assert selected is candidates[1]


@pytest.mark.parametrize("expected_offset", [0.1, 0.25, 0.5, -0.25])
def test_known_audio_offset_is_removed_before_pitch_comparison(
    tmp_path: Path,
    expected_offset: float,
) -> None:
    reference_path, performance_path = _write_delayed_audio_pair(tmp_path, expected_offset)
    estimate = estimate_global_offset(reference_path, performance_path)
    if expected_offset >= 0:
        reference_track = _pitch_track(0.0)
        performance_track = _pitch_track(expected_offset)
    else:
        reference_track = _pitch_track(-expected_offset)
        performance_track = _pitch_track(0.0)

    alignment = align_pitch_tracks(
        reference_track,
        performance_track,
        global_offset_seconds=estimate.seconds,
    )
    comparison = compare_alignment(alignment)
    paired_offset = np.median(
        comparison.performance_times[comparison.valid]
        - comparison.reference_times[comparison.valid]
    )

    assert estimate.seconds == pytest.approx(expected_offset, abs=0.02)
    assert estimate.confidence > 0.95
    assert paired_offset == pytest.approx(expected_offset, abs=0.02)
    assert comparison.global_bias_cents == pytest.approx(0.0, abs=5.0)
    assert comparison.mean_absolute_error_cents < 5.0
    assert comparison.within_25_percent > 95.0
    assert comparison.within_50_percent > 95.0

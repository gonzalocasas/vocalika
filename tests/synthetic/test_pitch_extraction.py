from __future__ import annotations

from pathlib import Path

import librosa
import numpy as np
import pytest
import soundfile as sf

from vocalika.analysis.cleaning import clean_pitch_track
from vocalika.analysis.pitch import PyinPitchExtractor


def write_harmonic_tone(path: Path, midi: float, sample_rate: int = 16_000) -> None:
    duration = 2.0
    times = np.arange(round(duration * sample_rate), dtype=np.float64) / sample_rate
    frequency = float(librosa.midi_to_hz(midi))
    phase = 2.0 * np.pi * frequency * times
    signal = 0.28 * np.sin(phase) + 0.10 * np.sin(2.0 * phase) + 0.04 * np.sin(3.0 * phase)
    fade_frames = round(0.05 * sample_rate)
    envelope = np.ones_like(signal)
    envelope[:fade_frames] = np.linspace(0.0, 1.0, fade_frames)
    envelope[-fade_frames:] = np.linspace(1.0, 0.0, fade_frames)
    sf.write(path, (signal * envelope).astype(np.float32), sample_rate)


@pytest.mark.parametrize("shift_cents", [50.0, -25.0])
def test_pyin_recovers_known_cent_shift(tmp_path: Path, shift_cents: float) -> None:
    reference_path = tmp_path / "reference.wav"
    performance_path = tmp_path / "performance.wav"
    write_harmonic_tone(reference_path, midi=60.0)
    write_harmonic_tone(performance_path, midi=60.0 + shift_cents / 100.0)
    extractor = PyinPitchExtractor()

    reference = clean_pitch_track(extractor.extract(reference_path))
    performance = clean_pitch_track(extractor.extract(performance_path))
    reference_center = np.nanmedian(reference.midi)
    performance_center = np.nanmedian(performance.midi)
    recovered_cents = 100.0 * (performance_center - reference_center)

    assert recovered_cents == pytest.approx(shift_cents, abs=6.0)

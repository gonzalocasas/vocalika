from __future__ import annotations

from pathlib import Path

import librosa
import numpy as np
import pytest
import soundfile as sf

from vocalika.analysis.cleaning import clean_pitch_track
from vocalika.analysis.pitch import RmvpePitchExtractor

SAMPLE_RATE = 16_000


def harmonic_tone(midi: float, level: float = 1.0, duration: float = 2.0) -> np.ndarray:
    """A voice-like tone: a few decaying partials, faded in and out."""
    times = np.arange(round(duration * SAMPLE_RATE), dtype=np.float64) / SAMPLE_RATE
    phase = 2.0 * np.pi * float(librosa.midi_to_hz(midi)) * times
    signal = sum(0.28 / harmonic * np.sin(harmonic * phase) for harmonic in range(1, 9))
    fade = round(0.05 * SAMPLE_RATE)
    envelope = np.ones_like(signal)
    envelope[:fade] = np.linspace(0.0, 1.0, fade)
    envelope[-fade:] = np.linspace(1.0, 0.0, fade)
    return np.asarray(level * signal * envelope, dtype=np.float32)


def write(path: Path, audio: np.ndarray) -> Path:
    sf.write(path, audio, SAMPLE_RATE)
    return path


@pytest.mark.parametrize("shift_cents", [50.0, -25.0, 7.0])
def test_recovers_a_known_cent_shift(tmp_path: Path, shift_cents: float) -> None:
    extractor = RmvpePitchExtractor()
    reference = clean_pitch_track(extractor.extract(write(tmp_path / "r.wav", harmonic_tone(60.0))))
    performance = clean_pitch_track(
        extractor.extract(write(tmp_path / "p.wav", harmonic_tone(60.0 + shift_cents / 100.0)))
    )

    recovered_cents = 100.0 * (np.nanmedian(performance.midi) - np.nanmedian(reference.midi))

    assert recovered_cents == pytest.approx(shift_cents, abs=3.0)


def test_concert_pitch_is_configurable(tmp_path: Path) -> None:
    times = np.arange(2 * SAMPLE_RATE, dtype=np.float64) / SAMPLE_RATE
    path = write(
        tmp_path / "a4-442.wav", (0.3 * np.sin(2.0 * np.pi * 442.0 * times)).astype(np.float32)
    )

    track = clean_pitch_track(RmvpePitchExtractor(concert_pitch_hz=442.0).extract(path))

    assert np.nanmedian(track.midi) == pytest.approx(69.0, abs=0.06)


def test_a_quiet_recording_measures_the_same_as_a_loud_one(tmp_path: Path) -> None:
    """A take recorded at low gain must not be read differently for it.

    Not bit-identical: at 2% of full scale the 16-bit file itself carries
    quantization noise only 50 dB below the tone, which moves a few frames
    by a few cents.
    """
    extractor = RmvpePitchExtractor()
    loud = extractor.extract(write(tmp_path / "loud.wav", harmonic_tone(57.0)))
    quiet = extractor.extract(write(tmp_path / "quiet.wav", harmonic_tone(57.0, level=0.02)))

    np.testing.assert_allclose(quiet.midi, loud.midi, atol=0.06, equal_nan=True)


def duet(upper_level: float, lower_level: float) -> np.ndarray:
    """E4 over C4 -- a major third, as a harmony line sits under a melody."""
    return harmonic_tone(64.0, upper_level) + harmonic_tone(60.0, lower_level)


@pytest.mark.parametrize(
    ("voice", "upper_level", "lower_level", "expected_midi"),
    [
        ("louder", 1.0, 0.4, 64.0),
        ("louder", 0.4, 1.0, 60.0),
        ("upper", 0.4, 1.0, 64.0),
        ("lower", 1.0, 0.4, 60.0),
    ],
)
def test_follows_the_chosen_voice_of_a_duet(
    tmp_path: Path, voice: str, upper_level: float, lower_level: float, expected_midi: float
) -> None:
    path = write(tmp_path / "duet.wav", duet(upper_level, lower_level))

    track = clean_pitch_track(RmvpePitchExtractor(voice=voice).extract(path))  # type: ignore[arg-type]

    assert np.nanmedian(track.midi) == pytest.approx(expected_midi, abs=0.15)
    assert np.mean(np.abs(track.midi[np.isfinite(track.midi)] - expected_midi) < 0.5) > 0.9


def test_a_solo_voice_is_unchanged_by_second_voice_search(tmp_path: Path) -> None:
    """With nobody else singing, every voice choice is just the singer."""
    path = write(tmp_path / "solo.wav", harmonic_tone(62.0))
    single = RmvpePitchExtractor().extract(path)

    for voice in ("louder", "upper", "lower"):
        chosen = RmvpePitchExtractor(voice=voice).extract(path)  # type: ignore[arg-type]
        np.testing.assert_allclose(chosen.midi, single.midi, atol=1e-9, equal_nan=True)

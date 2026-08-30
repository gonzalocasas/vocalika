from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import soundfile as sf

from vocalika.practice.scoring import (
    STEADINESS_LIMIT_CENTS,
    score_held_note,
    score_interval,
    verdict_for,
)

SAMPLE_RATE = 16_000


def midi_to_hz(midi: float) -> float:
    return 440.0 * math.pow(2.0, (midi - 69.0) / 12.0)


def tone(path: Path, segments: list[tuple[float, float | None]], vibrato_cents: float = 0.0):
    """Render a sequence of (seconds, midi) segments; midi None is silence."""
    parts = []
    phase = 0.0
    for seconds, midi in segments:
        count = int(SAMPLE_RATE * seconds)
        if midi is None:
            parts.append(np.zeros(count, dtype=np.float32))
            continue
        times = np.arange(count) / SAMPLE_RATE
        # Must stay an array: a scalar here collapses the cumsum below to one sample.
        cents = vibrato_cents * np.sin(2 * np.pi * 5.0 * times)
        frequency = midi_to_hz(midi) * np.power(2.0, cents / 1200.0)
        increment = 2 * np.pi * frequency / SAMPLE_RATE
        angles = phase + np.cumsum(increment)
        phase = float(angles[-1]) if count else phase
        # A couple of harmonics so pyin sees a voice-like spectrum.
        wave = 0.5 * np.sin(angles) + 0.2 * np.sin(2 * angles) + 0.1 * np.sin(3 * angles)
        parts.append(wave.astype(np.float32))
    sf.write(path, np.concatenate(parts), SAMPLE_RATE)
    return path


def test_a_note_held_on_pitch_scores_on_pitch(tmp_path: Path) -> None:
    path = tone(tmp_path / "a.wav", [(2.0, 60.0)])
    score = score_held_note(path, 60.0)
    assert score.verdict == "on-pitch"
    assert abs(score.centre_cents) < 15
    assert score.sung_note == "C4"
    assert score.coverage > 0.8


def test_a_flat_note_reports_how_flat_and_in_which_direction(tmp_path: Path) -> None:
    path = tone(tmp_path / "flat.wav", [(2.0, 59.5)])
    score = score_held_note(path, 60.0)
    assert score.centre_cents < 0, "flat must be negative"
    assert 30 < abs(score.centre_cents) < 70
    assert score.verdict in {"off", "close"}


def test_a_wrong_note_is_called_wrong_rather_than_merely_off(tmp_path: Path) -> None:
    path = tone(tmp_path / "wrong.wav", [(2.0, 62.0)])
    assert score_held_note(path, 60.0).verdict == "wrong-note"


def test_landing_on_the_note_but_wobbling_is_reported_as_unsteady(tmp_path: Path) -> None:
    # Centred correctly, so it is not a tuning fault; the fault is not staying.
    # A full semitone either way is a wobble, not vibrato.
    path = tone(tmp_path / "wobble.wav", [(2.0, 60.0)], vibrato_cents=130.0)
    score = score_held_note(path, 60.0)
    assert abs(score.centre_cents) < 30, "centre should still be right"
    assert score.steadiness_cents > STEADINESS_LIMIT_CENTS
    assert score.verdict == "unsteady"


def test_a_healthy_vibrato_is_not_called_a_fault(tmp_path: Path) -> None:
    """Expressive vibrato must not be trained out of a singer."""
    for amplitude in (20.0, 40.0, 60.0):
        path = tone(tmp_path / f"vib{amplitude}.wav", [(2.0, 60.0)], vibrato_cents=amplitude)
        score = score_held_note(path, 60.0)
        assert score.verdict == "on-pitch", f"+-{amplitude} cents was called {score.verdict}"


def test_silence_is_not_heard_rather_than_scored(tmp_path: Path) -> None:
    sf.write(tmp_path / "quiet.wav", np.zeros(SAMPLE_RATE * 2, dtype=np.float32), SAMPLE_RATE)
    score = score_held_note(tmp_path / "quiet.wav", 60.0)
    assert score.verdict == "not-heard"
    assert score.centre_cents is None


def test_the_scoop_into_a_note_is_not_counted_against_the_singer(tmp_path: Path) -> None:
    # Arriving from below is normal; only the held portion should be scored.
    path = tone(tmp_path / "scoop.wav", [(0.35, 57.0), (2.0, 60.0)])
    score = score_held_note(path, 60.0)
    assert abs(score.centre_cents) < 40, f"scoop leaked into the score: {score.centre_cents}"


def test_an_accurate_leap_scores_the_interval_not_just_the_pitches(tmp_path: Path) -> None:
    path = tone(tmp_path / "fifth.wav", [(1.2, 55.0), (1.2, 62.0)])
    result = score_interval(path, 55.0, 62.0)
    assert result["sung_semitones"] is not None
    assert abs(result["sung_semitones"] - 7) < 0.5
    assert abs(result["interval_error_cents"]) < 40
    assert result["verdict"] in {"on-pitch", "close"}


def test_a_correct_leap_sung_flat_throughout_still_scores_the_leap(tmp_path: Path) -> None:
    """Good relative pitch with poor tuning must not read as a bad interval."""
    path = tone(tmp_path / "flat-fifth.wav", [(1.2, 54.0), (1.2, 61.0)])
    result = score_interval(path, 55.0, 62.0)
    assert abs(result["interval_error_cents"]) < 40, "the leap itself was correct"
    assert result["first"]["centre_cents"] < -50, "but both notes sat low"


def test_a_leap_of_the_wrong_size_is_reported_as_off(tmp_path: Path) -> None:
    path = tone(tmp_path / "narrow.wav", [(1.2, 55.0), (1.2, 60.0)])
    result = score_interval(path, 55.0, 62.0)
    assert result["interval_error_cents"] < -100
    assert result["verdict"] == "off"


def test_verdicts_separate_tuning_from_steadiness() -> None:
    assert verdict_for(0.0, 5.0) == "on-pitch"
    assert verdict_for(30.0, 5.0) == "close"
    assert verdict_for(80.0, 5.0) == "off"
    assert verdict_for(400.0, 5.0) == "wrong-note"
    assert verdict_for(5.0, 90.0) == "unsteady"
    assert verdict_for(5.0, 12.0) == "on-pitch", "healthy vibrato is not a fault"
    assert verdict_for(None, None) == "not-heard"


def test_a_browser_webm_recording_can_be_scored(tmp_path: Path) -> None:
    """MediaRecorder produces WebM/Opus, which soundfile cannot read directly.

    Attempts must be decoded first, exactly as a take is, or every attempt
    recorded in the browser fails with "Format not recognised".
    """
    import subprocess

    from vocalika.api.practice import score_attempt

    source = tone(tmp_path / "source.wav", [(2.0, 60.0)])
    webm = tmp_path / "attempt.webm"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-i", str(source), "-c:a", "libopus", str(webm)],
        check=True,
    )

    score = score_attempt(webm, "sustained", 60.0, None)
    assert score["verdict"] == "on-pitch"
    assert abs(score["centre_cents"]) < 20


def test_a_browser_webm_interval_attempt_can_be_scored(tmp_path: Path) -> None:
    import subprocess

    from vocalika.api.practice import score_attempt

    source = tone(tmp_path / "leap.wav", [(1.2, 55.0), (1.2, 62.0)])
    webm = tmp_path / "leap.webm"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-i", str(source), "-c:a", "libopus", str(webm)],
        check=True,
    )

    score = score_attempt(webm, "interval", 55.0, 62.0)
    assert score["sung_semitones"] is not None
    assert abs(score["interval_error_cents"]) < 60


def test_an_over_wide_descending_leap_is_reported_as_wide_not_flat(tmp_path: Path) -> None:
    """A descending leap that goes too far is too wide, not flat.

    The signed error is negative here, which the pitch vocabulary would call
    "flat" -- but the singer over-jumped, which is the opposite impression.
    """
    # Asked for -5 (down a fourth); sings roughly -7 (down a fifth).
    path = tone(tmp_path / "wide-down.wav", [(1.2, 62.0), (1.2, 55.0)])
    result = score_interval(path, 62.0, 57.0)
    assert result["interval_error_cents"] < 0, "signed error is negative descending"
    assert result["width_error_cents"] > 100, "but the leap was too wide"
    assert result["wrong_direction"] is False


def test_a_too_narrow_ascending_leap_reports_negative_width(tmp_path: Path) -> None:
    path = tone(tmp_path / "narrow-up.wav", [(1.2, 55.0), (1.2, 59.0)])
    result = score_interval(path, 55.0, 62.0)
    assert result["width_error_cents"] < -100
    assert result["wrong_direction"] is False


def test_leaping_the_wrong_way_is_flagged_as_such(tmp_path: Path) -> None:
    # Asked to go up a fifth; goes down a fifth instead. The sizes match, so
    # width alone would call this correct.
    path = tone(tmp_path / "wrong-way.wav", [(1.2, 62.0), (1.2, 55.0)])
    result = score_interval(path, 62.0, 69.0)
    assert result["wrong_direction"] is True
    assert abs(result["width_error_cents"]) < 100, "the size was about right"
    assert result["verdict"] == "off", "but it still has to fail"

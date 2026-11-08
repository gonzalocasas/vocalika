from __future__ import annotations

import numpy as np

from vocalika.analysis import voices

SAMPLE_RATE = 16_000
HOP = 160
SECONDS = 2.0


def _voice(frequency: float, partials: int = 10) -> np.ndarray:
    """A steady voice-like tone: ``partials`` harmonics falling off as 1/k."""
    times = np.arange(int(SECONDS * SAMPLE_RATE)) / SAMPLE_RATE
    wave = sum(np.sin(2 * np.pi * k * frequency * times) / k for k in range(1, partials + 1))
    return np.asarray(0.2 * wave, dtype=np.float32)


def _frames() -> int:
    return int(SECONDS * SAMPLE_RATE) // HOP + 1


def _steady(frequency: float) -> np.ndarray:
    return np.full(_frames(), frequency)


def _separate(audio: np.ndarray, first_hz: float, second_hz: float, use_residual: bool):
    first = _steady(first_hz)
    residual = voices.cancel_harmonics(audio, first, SAMPLE_RATE, HOP)
    confident = np.full(_frames(), 0.9)
    return voices.separate_two_voices(
        first,
        confident,
        _steady(second_hz),
        confident,
        audio,
        SAMPLE_RATE,
        HOP,
        residual=residual if use_residual else None,
    )


def test_cancelling_a_voice_removes_almost_all_of_its_energy() -> None:
    audio = _voice(110.0)
    residual = voices.cancel_harmonics(audio, _steady(110.0), SAMPLE_RATE, HOP)
    assert np.sqrt(np.mean(residual**2)) < 0.05 * np.sqrt(np.mean(audio**2))


def test_a_real_second_singer_survives_the_level_test() -> None:
    # A bass on A2 and a tenor a major tenth above: most partials distinct.
    audio = _voice(110.0) + _voice(110.0 * 2.5)
    two = _separate(audio, 110.0, 275.0, use_residual=True)
    assert two.both.mean() > 0.9
    assert np.allclose(two.upper[two.both], 275.0)
    assert np.allclose(two.lower[two.both], 110.0)


def test_a_phantom_on_the_first_voices_partials_is_not_a_second_singer() -> None:
    """A solo bass, and a "second voice" a fifth above it that is not there.

    Every other partial of the phantom falls on one of the bass's, so in the
    original audio it measures nearly as loud as the bass and used to pass
    as a harmony part. Cancelling the bass takes those partials with it.
    """
    audio = _voice(110.0)
    fooled = _separate(audio, 110.0, 165.0, use_residual=False)
    assert fooled.both.mean() > 0.9, "the original audio alone cannot tell"
    two = _separate(audio, 110.0, 165.0, use_residual=True)
    assert not two.both.any()
    assert np.allclose(two.upper, 110.0)


def test_the_chosen_voice_is_the_only_voice_where_one_sings() -> None:
    upper = np.array([220.0, 220.0, 220.0])
    lower = np.array([0.0, 165.0, 0.0])
    two = voices.TwoVoices(upper, lower, np.ones(3), np.array([0.0, 1.0, 0.0]))
    chosen, _ = voices.choose_voice(two, use_upper=False)
    assert chosen.tolist() == [220.0, 165.0, 220.0]

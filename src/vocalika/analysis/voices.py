"""Finding the second singer, and choosing which voice is the melody.

RMVPE follows one voice and suppresses everything else: in a duet its
posterior at the other singer's pitch is essentially zero, and it tends to
latch onto the lower voice even when the upper one is the louder melody. So
the second voice is recovered by cancellation -- the found voice's harmonics
are masked out of the spectrum and RMVPE runs again on what is left
(iterative estimation and cancellation, after de Cheveigne 1993 and Klapuri
2003).

The two voices are then ordered by pitch, since "upper" and "lower" stay the
same singer through a harmonised passage while "first found" and "second
found" swap freely. Which of them is the melody is the louder one over the
whole song, unless the singer chooses otherwise: with two voices at the
same level there is no acoustic answer, only a musical one.

On the Choral Singing Dataset (bench/pitch) this took a melody sung 6 dB
over a lower harmony from 55% of frames within 50 cents to 86%, without
costing anything where the melody sits below (96%).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import librosa
import numpy as np
from numpy.typing import NDArray

FloatArray = NDArray[np.float64]
BoolArray = NDArray[np.bool_]
FloatAudio = NDArray[np.float32]

ReferenceVoice = Literal["louder", "upper", "lower"]
REFERENCE_VOICES: tuple[ReferenceVoice, ...] = ("louder", "upper", "lower")

_N_FFT = 2048


@dataclass(frozen=True)
class TwoVoices:
    upper: FloatArray  # Hz, 0 where no voice; the only voice where there is one
    lower: FloatArray  # Hz, 0 unless a second voice sings below the upper
    upper_confidence: FloatArray
    lower_confidence: FloatArray

    @property
    def both(self) -> BoolArray:
        return np.asarray((self.upper > 0) & (self.lower > 0), dtype=bool)


def cancel_harmonics(
    audio: FloatAudio,
    f0: FloatArray,
    sample_rate: int,
    hop_length: int,
    width_cents: float = 70.0,
) -> FloatAudio:
    """``audio`` with the harmonic series of ``f0`` masked out of its spectrum."""
    stft = librosa.stft(audio, n_fft=_N_FFT, hop_length=hop_length)
    freqs = librosa.fft_frequencies(sr=sample_rate, n_fft=_N_FFT)
    frames = np.flatnonzero(f0[: stft.shape[1]] > 0)
    if frames.size == 0:
        return audio
    fundamental = f0[frames]
    bin_hz = float(freqs[1])
    # A Hann window smears a pure partial over +-2 bins, whatever its frequency.
    min_half_width = 2.0 * bin_hz
    # Mark each partial's band as +1 at its first bin and -1 past its last;
    # a cumulative sum down the bins then covers every band in one pass.
    edges = np.zeros((freqs.size + 1, frames.size), dtype=np.int32)
    columns = np.arange(frames.size)
    for harmonic in range(1, int(sample_rate / 2 / fundamental.min()) + 1):
        centre = fundamental * harmonic
        audible = centre < sample_rate / 2
        half = np.maximum(centre * (2 ** (width_cents / 1200) - 1), min_half_width)
        low = np.clip(np.ceil((centre - half) / bin_hz), 0, freqs.size).astype(int)
        high = np.clip(np.floor((centre + half) / bin_hz) + 1, 0, freqs.size).astype(int)
        np.add.at(edges, (low[audible], columns[audible]), 1)
        np.add.at(edges, (high[audible], columns[audible]), -1)
    covered = np.cumsum(edges, axis=0)[: freqs.size] > 0
    stft[:, frames] *= ~covered
    out: FloatAudio = librosa.istft(stft, hop_length=hop_length, length=audio.size).astype(
        np.float32
    )
    return out


def harmonic_level_db(
    audio: FloatAudio,
    f0: FloatArray,
    sample_rate: int,
    hop_length: int,
    harmonics: int = 8,
) -> FloatArray:
    """Per-frame energy (dB) on the first ``harmonics`` partials of ``f0``."""
    power = np.abs(librosa.stft(audio, n_fft=_N_FFT, hop_length=hop_length)) ** 2
    bins, total_frames = power.shape
    level = np.full(f0.size, -np.inf)
    frames = np.flatnonzero(f0[:total_frames] > 0)
    if frames.size == 0:
        return level
    bin_hz = sample_rate / _N_FFT
    total = np.zeros(frames.size)
    for harmonic in range(1, harmonics + 1):
        centre = np.rint(f0[frames] * harmonic / bin_hz).astype(int)
        for offset in (-1, 0, 1):
            index = np.clip(centre + offset, 0, bins - 1)
            total += np.where(centre < bins - 1, power[index, frames], 0.0)
    level[frames] = 10.0 * np.log10(total + 1e-12)
    return level


def separate_two_voices(
    first: FloatArray,
    first_confidence: FloatArray,
    second: FloatArray,
    second_confidence: FloatArray,
    audio: FloatAudio,
    sample_rate: int,
    hop_length: int,
    minimum_seconds: float = 0.15,
    maximum_level_gap_db: float = 20.0,
    minimum_confidence: float = 0.2,
) -> TwoVoices:
    """Order the two estimates by pitch, discarding a second voice that isn't one.

    What cancellation leaves behind is not always a singer: reverb tails,
    breath, imperfectly removed partials of the first voice and the band's
    residue in a separated stem come back as pitch. A second voice is kept
    only where RMVPE is at least ``minimum_confidence`` sure of it, it sits
    more than a semitone from the first and off its octave, it is no more
    than ``maximum_level_gap_db`` below it, and it holds for at least
    ``minimum_seconds``.

    Confidence does most of the work. On the benchmark, residue found in
    solo recordings mixed into a band and separated had a median confidence
    of 0.14; real second singers had 0.87. Without a floor, that residue cost
    solo-in-band references 1.4 points of pitch accuracy (96.4% -> 95.0%);
    the 0.2 floor wins back all but 0.1 of them while costing real harmony
    1.4 points (87.3% -> 85.9%), where a 0.5 floor would cost it 4.
    """
    frames = min(first.size, second.size)
    first, second = first[:frames], second[:frames]
    first_confidence, second_confidence = first_confidence[:frames], second_confidence[:frames]
    both = (first > 0) & (second > 0)
    interval = np.zeros(frames)
    interval[both] = np.abs(1200.0 * np.log2(second[both] / first[both]))
    distinct = (
        both
        & (second_confidence >= minimum_confidence)
        & (interval >= 100.0)
        & (np.abs(interval - 1200.0) >= 100.0)
    )
    gap = harmonic_level_db(audio, first, sample_rate, hop_length) - harmonic_level_db(
        audio, np.where(distinct, second, 0.0), sample_rate, hop_length
    )
    distinct &= gap <= maximum_level_gap_db
    distinct = _drop_short_runs(distinct, max(1, round(minimum_seconds * sample_rate / hop_length)))

    second_is_upper = distinct & (second > first)
    upper = np.where(second_is_upper, second, first)
    upper_confidence = np.where(second_is_upper, second_confidence, first_confidence)
    lower = np.where(distinct, np.where(second_is_upper, first, second), 0.0)
    lower_confidence = np.where(
        distinct, np.where(second_is_upper, first_confidence, second_confidence), 0.0
    )
    return TwoVoices(upper, lower, upper_confidence, lower_confidence)


def louder_is_upper(
    voices: TwoVoices, audio: FloatAudio, sample_rate: int, hop_length: int
) -> bool:
    """Whether the upper voice carries more harmonic energy where both sing."""
    both = voices.both
    if not both.any():
        return True
    upper = harmonic_level_db(audio, np.where(both, voices.upper, 0.0), sample_rate, hop_length)
    lower = harmonic_level_db(audio, voices.lower, sample_rate, hop_length)
    return bool(np.median(upper[both] - lower[both]) >= 0.0)


def choose_voice(voices: TwoVoices, use_upper: bool) -> tuple[FloatArray, FloatArray]:
    """The chosen voice where two sing, and the only voice everywhere else."""
    both = voices.both
    if use_upper:
        return voices.upper, voices.upper_confidence
    return (
        np.where(both, voices.lower, voices.upper),
        np.where(both, voices.lower_confidence, voices.upper_confidence),
    )


def _drop_short_runs(mask: BoolArray, minimum: int) -> BoolArray:
    edges = np.flatnonzero(np.diff(np.concatenate(([0], mask.astype(np.int8), [0]))))
    kept = np.zeros(mask.size, dtype=bool)
    for start, end in zip(edges[::2], edges[1::2], strict=True):
        if end - start >= minimum:
            kept[start:end] = True
    return kept

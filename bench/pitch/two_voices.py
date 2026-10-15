"""Second-voice recovery by harmonic cancellation, and lead-voice selection.

RMVPE follows one voice and suppresses the rest: in a duet its posterior at
the other singer's pitch is near zero. To get the other voice, the found
voice's harmonics are masked out of the spectrum and RMVPE runs again on the
residual -- iterative estimation and cancellation (Klapuri 2003, de
Cheveigne 1993) with RMVPE as the single-pitch estimator.

The lead is then the voice with more harmonic energy, decided per stretch
rather than per frame, since a melody does not hop between singers every
10 ms.
"""

from __future__ import annotations

import numpy as np
import librosa

import trackers

SR = 16_000
N_FFT = 2048
HOP = 160


def cancel(audio: np.ndarray, f0: np.ndarray, width_cents: float = 70.0, harmonics: int = 40) -> np.ndarray:
    """Remove the harmonic series of ``f0`` (10 ms frames, 0 = none) from ``audio``."""
    stft = librosa.stft(audio, n_fft=N_FFT, hop_length=HOP)
    freqs = librosa.fft_frequencies(sr=SR, n_fft=N_FFT)
    frames = min(stft.shape[1], f0.size)
    mask = np.ones(stft.shape, dtype=np.float32)
    # A Hann window's main lobe spans +-2 bins; harmonics are never narrower than that.
    min_half_width = 2.0 * SR / N_FFT
    for i in np.flatnonzero(f0[:frames] > 0):
        for h in range(1, harmonics + 1):
            centre = f0[i] * h
            if centre > SR / 2:
                break
            half = max(centre * (2 ** (width_cents / 1200) - 1), min_half_width)
            mask[np.abs(freqs - centre) <= half, i] = 0.0
    return librosa.istft(stft * mask, hop_length=HOP, length=audio.size).astype(np.float32)


def harmonic_energy(audio: np.ndarray, f0: np.ndarray, harmonics: int = 20) -> np.ndarray:
    """Per-frame energy (dB) on the harmonics of ``f0``; -inf where f0 is 0."""
    spectrum = np.abs(librosa.stft(audio, n_fft=N_FFT, hop_length=HOP)) ** 2
    freqs = librosa.fft_frequencies(sr=SR, n_fft=N_FFT)
    frames = min(spectrum.shape[1], f0.size)
    energy = np.full(f0.size, -np.inf)
    for i in np.flatnonzero(f0[:frames] > 0):
        total = 0.0
        for h in range(1, harmonics + 1):
            centre = f0[i] * h
            if centre > SR / 2:
                break
            k = int(round(centre / freqs[1]))
            total += spectrum[max(0, k - 1) : k + 2, i].sum()
        energy[i] = 10 * np.log10(total + 1e-12)
    return energy


def two_voices(audio: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    first = trackers.rmvpe(audio).f0_hz
    residual = cancel(audio, first)
    second = trackers.rmvpe(residual).f0_hz
    n = min(first.size, second.size)
    first, second = first[:n], second[:n]
    # A "second voice" within a semitone of the first, or at its octave, is
    # leftover of the first voice, not another singer.
    interval = np.abs(1200 * np.log2(np.maximum(second, 1) / np.maximum(first, 1)))
    leftover = (first > 0) & (second > 0) & ((interval < 100) | (np.abs(interval - 1200) < 100))
    second[leftover] = 0.0
    return first, second


def lead(audio: np.ndarray, segment_seconds: float = 1.0) -> np.ndarray:
    """The louder of the two voices, decided per segment."""
    a, b = two_voices(audio)
    ea, eb = harmonic_energy(audio, a), harmonic_energy(audio, b)
    out = a.copy()
    step = int(segment_seconds / 0.01)
    for start in range(0, a.size, step):
        seg = slice(start, start + step)
        both = (a[seg] > 0) & (b[seg] > 0)
        if both.sum() < 10:
            continue
        if np.median(eb[seg][both] - ea[seg][both]) > 0:
            out[seg] = np.where(b[seg] > 0, b[seg], a[seg])
    return out

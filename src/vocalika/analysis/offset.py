from __future__ import annotations

from dataclasses import dataclass
from math import gcd
from pathlib import Path

import librosa
import numpy as np
from numpy.typing import NDArray
from scipy import signal
from scipy.ndimage import gaussian_filter1d

from vocalika.audio.decode import load_audio

FloatArray = NDArray[np.float64]


@dataclass(frozen=True)
class GlobalOffsetEstimate:
    seconds: float
    confidence: float
    method: str = "pcm-cross-correlation"
    raw_correlation: float | None = None
    peak_margin: float | None = None


def select_global_offset(
    estimates: list[GlobalOffsetEstimate],
    minimum_confidence: float,
) -> GlobalOffsetEstimate | None:
    """Select the first trustworthy estimate from identity-specific to generic."""
    if not estimates:
        return None
    return next(
        (estimate for estimate in estimates if estimate.confidence >= minimum_confidence),
        max(estimates, key=lambda estimate: estimate.confidence),
    )


def _resample(
    samples: NDArray[np.float32],
    source_rate: int,
    target_rate: int,
) -> FloatArray:
    if source_rate == target_rate:
        return np.asarray(samples, dtype=np.float64)
    divisor = gcd(source_rate, target_rate)
    return np.asarray(
        signal.resample_poly(samples, target_rate // divisor, source_rate // divisor),
        dtype=np.float64,
    )


def _overlapping_segments(
    reference: FloatArray,
    performance: FloatArray,
    lag: int,
) -> tuple[FloatArray, FloatArray]:
    if lag >= 0:
        length = min(reference.size, performance.size - lag)
        return reference[:length], performance[lag : lag + length]
    length = min(reference.size + lag, performance.size)
    return reference[-lag : -lag + length], performance[:length]


def estimate_global_offset(
    reference_path: Path,
    performance_path: Path,
    *,
    maximum_offset_seconds: float = 5.0,
    correlation_sample_rate: int = 2_000,
) -> GlobalOffsetEstimate:
    reference, reference_rate = load_audio(reference_path)
    performance, performance_rate = load_audio(performance_path)
    reference_resampled = _resample(reference, reference_rate, correlation_sample_rate)
    performance_resampled = _resample(performance, performance_rate, correlation_sample_rate)
    reference_resampled -= np.mean(reference_resampled)
    performance_resampled -= np.mean(performance_resampled)
    if not np.any(reference_resampled) or not np.any(performance_resampled):
        raise ValueError("Cannot estimate an offset from silent audio.")

    correlation = signal.correlate(
        performance_resampled,
        reference_resampled,
        mode="full",
        method="fft",
    )
    lags = signal.correlation_lags(
        performance_resampled.size,
        reference_resampled.size,
        mode="full",
    )
    maximum_lag = round(maximum_offset_seconds * correlation_sample_rate)
    allowed = np.abs(lags) <= maximum_lag
    if not np.any(allowed):
        raise ValueError("No cross-correlation lags fall inside the configured offset range.")
    allowed_indices = np.flatnonzero(allowed)
    best_index = int(allowed_indices[np.argmax(correlation[allowed])])
    best_lag = int(lags[best_index])

    reference_overlap, performance_overlap = _overlapping_segments(
        reference_resampled,
        performance_resampled,
        best_lag,
    )
    denominator = float(np.linalg.norm(reference_overlap) * np.linalg.norm(performance_overlap))
    correlation_confidence = (
        float(np.dot(reference_overlap, performance_overlap) / denominator)
        if denominator > np.finfo(np.float64).eps
        else 0.0
    )
    overlap_fraction = reference_overlap.size / min(
        reference_resampled.size,
        performance_resampled.size,
    )
    confidence = correlation_confidence * overlap_fraction
    return GlobalOffsetEstimate(
        seconds=best_lag / correlation_sample_rate,
        confidence=float(np.clip(confidence, -1.0, 1.0)),
        raw_correlation=correlation_confidence,
    )


def _rms_envelope(
    path: Path,
    frames_per_second: int,
    smoothing_seconds: float,
) -> FloatArray:
    audio, sample_rate = load_audio(path)
    frame_length = max(1, round(sample_rate / frames_per_second))
    frame_count = audio.size // frame_length
    if frame_count < frames_per_second:
        raise ValueError("Audio is too short for vocal-envelope alignment.")
    framed = np.asarray(
        audio[: frame_count * frame_length].reshape(frame_count, frame_length),
        dtype=np.float64,
    )
    rms = np.sqrt(np.mean(np.square(framed), axis=1))
    compressed = np.log1p(rms * 100.0)
    sigma = max(0.0, smoothing_seconds * frames_per_second)
    return (
        np.asarray(gaussian_filter1d(compressed, sigma=sigma), dtype=np.float64)
        if sigma
        else compressed
    )


def _correlation(left: FloatArray, right_centered: FloatArray) -> float:
    left_centered = left - np.mean(left)
    denominator = float(np.linalg.norm(left_centered) * np.linalg.norm(right_centered))
    if denominator <= np.finfo(np.float64).eps:
        return 0.0
    return float(np.dot(left_centered, right_centered) / denominator)


def estimate_vocal_envelope_offset(
    reference_path: Path,
    performance_path: Path,
    *,
    frames_per_second: int = 10,
    smoothing_seconds: float = 1.0,
    uniqueness_window_seconds: float = 5.0,
) -> GlobalOffsetEstimate:
    """Locate the shorter recording inside the longer one from vocal energy."""
    reference = _rms_envelope(reference_path, frames_per_second, smoothing_seconds)
    performance = _rms_envelope(performance_path, frames_per_second, smoothing_seconds)
    reference_is_longer = reference.size >= performance.size
    longer = reference if reference_is_longer else performance
    shorter = performance if reference_is_longer else reference
    shorter_centered = shorter - np.mean(shorter)
    if np.linalg.norm(shorter_centered) <= np.finfo(np.float64).eps:
        raise ValueError("Cannot estimate a vocal-envelope offset from constant audio.")

    scores = np.asarray(
        [
            _correlation(longer[start : start + shorter.size], shorter_centered)
            for start in range(longer.size - shorter.size + 1)
        ],
        dtype=np.float64,
    )
    best_index = int(np.argmax(scores))
    best_correlation = float(scores[best_index])
    exclusion = max(1, round(uniqueness_window_seconds * frames_per_second))
    remote = np.concatenate(
        (
            scores[: max(0, best_index - exclusion)],
            scores[min(scores.size, best_index + exclusion + 1) :],
        )
    )
    second_correlation = float(np.max(remote)) if remote.size else 0.0
    peak_margin = best_correlation - second_correlation
    uniqueness = float(np.clip(peak_margin / 0.1, 0.0, 1.0))
    confidence = max(0.0, best_correlation) * uniqueness
    start_seconds = best_index / frames_per_second
    offset_seconds = -start_seconds if reference_is_longer else start_seconds
    return GlobalOffsetEstimate(
        seconds=offset_seconds,
        confidence=float(np.clip(confidence, 0.0, 1.0)),
        method="smoothed-vocal-envelope-correlation",
        raw_correlation=best_correlation,
        peak_margin=peak_margin,
    )


def _spectral_change_features(
    path: Path,
    frames_per_second: int,
    sample_rate: int,
    mel_band_count: int,
) -> FloatArray:
    audio, source_rate = load_audio(path)
    resampled = _resample(audio, source_rate, sample_rate)
    hop_length = max(1, round(sample_rate / frames_per_second))
    mel_power = librosa.feature.melspectrogram(
        y=resampled,
        sr=sample_rate,
        n_fft=2_048,
        hop_length=hop_length,
        n_mels=mel_band_count,
    )
    log_mel = librosa.power_to_db(mel_power + np.finfo(np.float64).eps)
    changes = np.diff(log_mel, axis=1, prepend=log_mel[:, :1])
    return np.asarray(changes.T, dtype=np.float64)


def _standardized_feature_correlation(left: FloatArray, right: FloatArray) -> float:
    left_scale = np.std(left, axis=0)
    right_scale = np.std(right, axis=0)
    usable = (left_scale > 1e-6) & (right_scale > 1e-6)
    if not np.any(usable):
        return 0.0
    normalized_left = (left[:, usable] - np.mean(left[:, usable], axis=0)) / left_scale[usable]
    normalized_right = (right[:, usable] - np.mean(right[:, usable], axis=0)) / right_scale[
        usable
    ]
    return float(np.mean(normalized_left * normalized_right))


def estimate_spectral_change_offset(
    reference_path: Path,
    performance_path: Path,
    *,
    frames_per_second: int = 10,
    sample_rate: int = 16_000,
    mel_band_count: int = 40,
    uniqueness_window_seconds: float = 5.0,
) -> GlobalOffsetEstimate:
    """Locate matching phonetic/spectral changes without relying on melody alone."""
    reference = _spectral_change_features(
        reference_path,
        frames_per_second,
        sample_rate,
        mel_band_count,
    )
    performance = _spectral_change_features(
        performance_path,
        frames_per_second,
        sample_rate,
        mel_band_count,
    )
    reference_is_longer = reference.shape[0] >= performance.shape[0]
    longer = reference if reference_is_longer else performance
    shorter = performance if reference_is_longer else reference
    if shorter.shape[0] < frames_per_second:
        raise ValueError("Audio is too short for spectral-change alignment.")

    scores = np.asarray(
        [
            _standardized_feature_correlation(
                longer[start : start + shorter.shape[0]],
                shorter,
            )
            for start in range(longer.shape[0] - shorter.shape[0] + 1)
        ],
        dtype=np.float64,
    )
    best_index = int(np.argmax(scores))
    best_correlation = float(scores[best_index])
    exclusion = max(1, round(uniqueness_window_seconds * frames_per_second))
    remote = np.concatenate(
        (
            scores[: max(0, best_index - exclusion)],
            scores[min(scores.size, best_index + exclusion + 1) :],
        )
    )
    second_correlation = float(np.max(remote)) if remote.size else float(np.median(scores))
    peak_margin = best_correlation - second_correlation
    median = float(np.median(scores))
    robust_scale = max(
        1.4826 * float(np.median(np.abs(scores - median))),
        float(np.finfo(np.float64).eps),
    )
    height_strength = (best_correlation - median) / (5.0 * robust_scale)
    uniqueness_strength = peak_margin / (1.25 * robust_scale)
    confidence = float(np.clip(min(height_strength, uniqueness_strength), 0.0, 1.0))
    start_seconds = best_index / frames_per_second
    offset_seconds = -start_seconds if reference_is_longer else start_seconds
    return GlobalOffsetEstimate(
        seconds=offset_seconds,
        confidence=confidence,
        method="spectral-change-correlation",
        raw_correlation=best_correlation,
        peak_margin=peak_margin,
    )

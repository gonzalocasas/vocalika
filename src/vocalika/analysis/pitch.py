from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import librosa
import numpy as np
from numpy.typing import NDArray

from vocalika.audio.decode import load_audio

FloatArray = NDArray[np.float64]
BoolArray = NDArray[np.bool_]


@dataclass
class PitchTrack:
    times: FloatArray
    raw_frequency_hz: FloatArray
    raw_midi: FloatArray
    midi: FloatArray
    confidence: FloatArray
    voiced: BoolArray
    extractor: str
    sample_rate: int
    hop_length: int

    @property
    def duration_seconds(self) -> float:
        return float(self.times[-1]) if self.times.size else 0.0


class PitchExtractor(Protocol):
    def extract(self, audio_path: Path) -> PitchTrack: ...


@dataclass(frozen=True)
class PyinPitchExtractor:
    hop_length: int = 256
    frame_length: int = 2048
    fmin_midi: float = 36.0  # C2
    fmax_midi: float = 84.0  # C6
    concert_pitch_hz: float = 440.0
    harmonic_margin: float = 1.0

    def _midi_to_hz(self, midi: float) -> float:
        return self.concert_pitch_hz * math.pow(2.0, (midi - 69.0) / 12.0)

    def extract(self, audio_path: Path) -> PitchTrack:
        audio, sample_rate = load_audio(audio_path)
        analysis_audio = (
            librosa.effects.harmonic(audio, margin=self.harmonic_margin)
            if self.harmonic_margin > 0.0
            else audio
        )
        frequency, voiced, probability = librosa.pyin(
            analysis_audio,
            fmin=self._midi_to_hz(self.fmin_midi),
            fmax=self._midi_to_hz(self.fmax_midi),
            sr=sample_rate,
            frame_length=self.frame_length,
            hop_length=self.hop_length,
            fill_na=np.nan,
        )
        frequency = np.asarray(frequency, dtype=np.float64)
        raw_midi = np.full_like(frequency, np.nan)
        valid = np.isfinite(frequency) & (frequency > 0)
        raw_midi[valid] = 69.0 + 12.0 * np.log2(frequency[valid] / self.concert_pitch_hz)
        times = librosa.times_like(frequency, sr=sample_rate, hop_length=self.hop_length)
        return PitchTrack(
            times=np.asarray(times, dtype=np.float64),
            raw_frequency_hz=frequency,
            raw_midi=raw_midi,
            midi=raw_midi.copy(),
            confidence=np.nan_to_num(np.asarray(probability, dtype=np.float64)),
            voiced=np.asarray(voiced, dtype=np.bool_),
            extractor=(
                f"librosa.pyin+hpss-harmonic-{self.harmonic_margin:g}"
                if self.harmonic_margin > 0.0
                else "librosa.pyin"
            ),
            sample_rate=sample_rate,
            hop_length=self.hop_length,
        )

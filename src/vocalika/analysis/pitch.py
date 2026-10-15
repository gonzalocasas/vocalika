from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Literal, Protocol

import librosa
import numpy as np
from numpy.typing import NDArray

from vocalika.analysis import rmvpe, voices
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
    # Frame loudness in dBFS, on the same frames as the pitch. Pitch trackers
    # judge whether a frame is pitched, not whether it is loud enough to be the
    # singer, so cleaning needs this to tell a voice from faint accompaniment
    # that separation left behind. None for tracks not measured from audio.
    level_db: FloatArray | None = None

    @property
    def duration_seconds(self) -> float:
        return float(self.times[-1]) if self.times.size else 0.0


class PitchExtractor(Protocol):
    def extract(self, audio_path: Path) -> PitchTrack: ...


PitchVoice = Literal["single", "louder", "upper", "lower"]


@dataclass(frozen=True)
class RmvpePitchExtractor:
    """Vocal pitch every 10 ms with RMVPE; see analysis/rmvpe.py for why RMVPE.

    ``voice`` picks what to follow when more than one person sings. A take is
    one singer, so it is read as it comes ("single"). A reference may carry
    harmony, and there the second voice is recovered by cancellation and the
    melody chosen as the louder, upper or lower one (analysis/voices.py).
    """

    voice: PitchVoice = "single"
    fmin_midi: float = 36.0  # C2
    fmax_midi: float = 84.0  # C6
    concert_pitch_hz: float = 440.0
    voicing_threshold: float = 0.03
    # Every input is scaled to this peak first, so a quietly recorded take
    # is measured exactly as it would be at full level.
    peak_level: float = 0.9

    @property
    def name(self) -> str:
        return "rmvpe" if self.voice == "single" else f"rmvpe+second-voice-{self.voice}"

    def cache_parameters(self) -> dict[str, Any]:
        return {
            "extractor": self.name,
            "weights_sha256": rmvpe.WEIGHTS_SHA256,
            "fmin_midi": self.fmin_midi,
            "fmax_midi": self.fmax_midi,
            "concert_pitch_hz": self.concert_pitch_hz,
            "voicing_threshold": self.voicing_threshold,
            "peak_level": self.peak_level,
        }

    def _track(self, audio: NDArray[np.float32]) -> tuple[FloatArray, FloatArray]:
        frequency, confidence = rmvpe.decode(
            rmvpe.load_rmvpe().salience(audio), self.voicing_threshold
        )
        low = self.concert_pitch_hz * 2.0 ** ((self.fmin_midi - 69.0) / 12.0)
        high = self.concert_pitch_hz * 2.0 ** ((self.fmax_midi - 69.0) / 12.0)
        frequency[(frequency < low) | (frequency > high)] = 0.0
        return frequency, confidence

    def extract(self, audio_path: Path) -> PitchTrack:
        audio, sample_rate = load_audio(audio_path)
        if sample_rate != rmvpe.SAMPLE_RATE:
            audio = librosa.resample(audio, orig_sr=sample_rate, target_sr=rmvpe.SAMPLE_RATE)
            sample_rate = rmvpe.SAMPLE_RATE
        peak = float(np.max(np.abs(audio))) if audio.size else 0.0
        if peak > 0.0:
            audio = (audio * (self.peak_level / peak)).astype(np.float32)
        hop = rmvpe.HOP_LENGTH

        frequency, confidence = self._track(audio)
        if self.voice != "single":
            residual = voices.cancel_harmonics(audio, frequency, sample_rate, hop)
            second, second_confidence = self._track(residual)
            two = voices.separate_two_voices(
                frequency, confidence, second, second_confidence, audio, sample_rate, hop
            )
            use_upper = (
                voices.louder_is_upper(two, audio, sample_rate, hop)
                if self.voice == "louder"
                else self.voice == "upper"
            )
            frequency, confidence = voices.choose_voice(two, use_upper)

        frequency = np.where(frequency > 0.0, frequency, np.nan)
        raw_midi = 69.0 + 12.0 * np.log2(frequency / self.concert_pitch_hz)
        times = np.arange(frequency.size, dtype=np.float64) * hop / sample_rate
        rms = librosa.feature.rms(
            y=audio, frame_length=rmvpe.WINDOW_LENGTH, hop_length=hop, center=True
        )[0]
        rms = np.pad(rms, (0, max(0, frequency.size - rms.size)))[: frequency.size]
        level_db = 20.0 * np.log10(np.maximum(np.asarray(rms, dtype=np.float64), 1e-10))
        return PitchTrack(
            times=times,
            raw_frequency_hz=frequency,
            raw_midi=raw_midi,
            midi=raw_midi.copy(),
            confidence=np.asarray(confidence, dtype=np.float64),
            voiced=np.isfinite(frequency),
            extractor=self.name,
            sample_rate=sample_rate,
            hop_length=hop,
            level_db=level_db,
        )


def transpose_track(track: PitchTrack, semitones: float) -> PitchTrack:
    """``track`` as it would read ``semitones`` higher, exactly.

    A transposed reference is measured this way rather than by re-extracting
    pitch from transposed audio: time-stretching smears note transitions, and
    on "Rasguna las piedras" re-extraction put 8-11% of frames more than 100
    cents away from the exact transposition.
    """
    if semitones == 0:
        return track
    factor = 2.0 ** (semitones / 12.0)
    return replace(
        track,
        raw_frequency_hz=track.raw_frequency_hz * factor,
        raw_midi=track.raw_midi + semitones,
        midi=track.midi + semitones,
    )

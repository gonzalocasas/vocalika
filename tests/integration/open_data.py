"""Shared plumbing for the tests backed by optional, locally fetched open datasets.

Each dataset is installed by ``scripts/fetch_open_datasets.py``, which writes a
marker file once the pinned archive has been verified and extracted. Tests ask
for a dataset through :func:`dataset_root`, which skips them when it is absent.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import librosa
import numpy as np
import pytest
import soundfile as sf
from numpy.typing import NDArray

from vocalika.analysis.cleaning import clean_pitch_track
from vocalika.analysis.pitch import PitchTrack, PitchVoice
from vocalika.config import AnalysisConfig

FloatArray = NDArray[np.float64]

DEFAULT_DATA_ROOT = Path(__file__).parents[1] / "external-data"
DATA_ROOT = Path(os.environ.get("VOCALIKA_OPEN_DATA_DIR", DEFAULT_DATA_ROOT))
FETCH_COMMAND = "uv run python scripts/fetch_open_datasets.py"
ANALYSIS_SAMPLE_RATE = AnalysisConfig().analysis_sample_rate


def dataset_root(key: str) -> Path:
    root = DATA_ROOT / key
    if not (root / ".vocalika-dataset.json").is_file():
        pytest.skip(f"optional dataset {key!r} is absent; fetch it with: {FETCH_COMMAND} {key}")
    return root


def load_mono(path: Path) -> NDArray[np.float32]:
    """``path`` as mono float32 at the analysis rate, the way the app reads audio."""
    audio, _ = librosa.load(path, sr=ANALYSIS_SAMPLE_RATE, mono=True)
    return np.asarray(audio, dtype=np.float32)


def extract_clean(audio: NDArray[np.float32], voice: PitchVoice | None = None) -> PitchTrack:
    """Run the production extractor and cleaning on analysis-rate ``audio``.

    ``voice=None`` is the reference path (second-voice search, the configured
    voice); ``"single"`` is the path a take goes through.
    """
    config = AnalysisConfig()
    extractor = config.reference_extractor() if voice is None else config.pitch_extractor(voice)
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "audio.wav"
        sf.write(path, audio, ANALYSIS_SAMPLE_RATE)
        return clean_pitch_track(extractor.extract(path), **config.cleaning_parameters())


def nearest(annotation_times: FloatArray, values: FloatArray, times: FloatArray) -> FloatArray:
    """The annotation value nearest each of ``times``; never interpolates across voicing."""
    right = np.clip(np.searchsorted(annotation_times, times), 1, annotation_times.size - 1)
    left_gap = np.abs(annotation_times[right - 1] - times)
    use_left = left_gap <= np.abs(annotation_times[right] - times)
    return values[right - use_left]


def hz_to_midi(frequency: FloatArray) -> FloatArray:
    """MIDI note numbers at A4 = 440 Hz; NaN wherever ``frequency`` is not positive."""
    frequency = np.asarray(frequency, dtype=np.float64)
    midi = np.full(frequency.shape, np.nan)
    positive = frequency > 0.0
    midi[positive] = 69.0 + 12.0 * np.log2(frequency[positive] / 440.0)
    return midi


def frame_errors(
    track: PitchTrack, annotation_times: FloatArray, annotation_hz: FloatArray
) -> tuple[FloatArray, float]:
    """Absolute cents error on frames both voiced, and the share of sung frames reported.

    The second value is voicing recall: of the frames the annotation calls
    sung, how many the track reports a pitch for.
    """
    expected = nearest(annotation_times, annotation_hz, track.times)
    reported = np.isfinite(track.midi)
    both = reported & (expected > 0.0)
    errors = np.abs(100.0 * (track.midi[both] - hz_to_midi(expected[both])))
    sung = expected > 0.0
    recall = float(np.mean(reported[sung])) if np.any(sung) else float("nan")
    return errors, recall


def octave_error_share(errors: FloatArray) -> float:
    """Share of frames about an octave from the truth."""
    return float(np.mean(np.abs(errors - 1200.0) < 100.0)) if errors.size else 0.0

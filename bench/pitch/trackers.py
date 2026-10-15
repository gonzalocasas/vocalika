"""Pitch trackers under test, behind one interface.

Every tracker takes mono 16 kHz audio and returns an ``Estimate`` on its own
frame grid: times, f0 in Hz (0 where it declares the frame unvoiced), and a
per-frame confidence on whatever scale the tracker has. The runner resamples
everything onto a common 10 ms grid before scoring, the way mir_eval does.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import numpy as np
import soundfile as sf

REPO = Path(__file__).resolve().parents[2]
SAMPLE_RATE = 16_000
FMIN_HZ = 65.4  # C2, Vocalika's pitch floor
FMAX_HZ = 1046.5  # C6, Vocalika's pitch ceiling


@dataclass
class Estimate:
    times: np.ndarray
    f0_hz: np.ndarray
    confidence: np.ndarray


def _clip_range(f0: np.ndarray) -> np.ndarray:
    f0 = np.where(np.isfinite(f0), f0, 0.0)
    f0[(f0 < FMIN_HZ) | (f0 > FMAX_HZ)] = 0.0
    return f0


def pyin_vocalika(audio: np.ndarray) -> Estimate:
    """Vocalika's production path today: pyin with HPSS, then clean_pitch_track."""
    from vocalika.analysis.cleaning import clean_pitch_track
    from vocalika.analysis.pitch import PyinPitchExtractor
    from vocalika.config import AnalysisConfig

    config = AnalysisConfig()
    extractor = PyinPitchExtractor(
        hop_length=config.pitch_hop_length,
        frame_length=config.pitch_frame_length,
        fmin_midi=config.pitch_min_midi,
        fmax_midi=config.pitch_max_midi,
        concert_pitch_hz=config.concert_pitch_hz,
        harmonic_margin=config.pitch_harmonic_margin,
    )
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "audio.wav"
        sf.write(path, audio, SAMPLE_RATE)
        track = clean_pitch_track(extractor.extract(path), **config.cleaning_parameters())
    f0 = 440.0 * 2.0 ** ((track.midi - 69.0) / 12.0)
    return Estimate(track.times, _clip_range(f0), track.confidence)


@cache
def _rmvpe():
    sys.path.insert(0, str(Path(__file__).parent))
    from rmvpe import Rmvpe

    return Rmvpe(REPO / "tests" / "external-data" / "models" / "rmvpe.pt")


def rmvpe(audio: np.ndarray, threshold: float = 0.03) -> Estimate:
    model = _rmvpe()
    salience = model.salience(audio)
    f0, peak = model.decode(salience, threshold)
    times = np.arange(f0.size) * 0.01
    return Estimate(times, _clip_range(f0), peak)


def crepe(audio: np.ndarray, model: str = "full", periodicity_threshold: float = 0.21) -> Estimate:
    import torch
    import torchcrepe

    tensor = torch.from_numpy(np.ascontiguousarray(audio, dtype=np.float32)).unsqueeze(0)
    f0, periodicity = torchcrepe.predict(
        tensor, SAMPLE_RATE, hop_length=160, fmin=FMIN_HZ, fmax=FMAX_HZ, model=model,
        decoder=torchcrepe.decode.viterbi, return_periodicity=True, batch_size=512,
    )
    # torchcrepe's recommended post-processing: smooth periodicity, then gate.
    periodicity = torchcrepe.filter.median(periodicity, 3)
    f0 = f0[0].numpy().astype(np.float64)
    periodicity = periodicity[0].numpy().astype(np.float64)
    f0[periodicity < periodicity_threshold] = 0.0
    return Estimate(np.arange(f0.size) * 0.01, _clip_range(f0), periodicity)


@cache
def _fcpe():
    from torchfcpe import spawn_bundled_infer_model

    return spawn_bundled_infer_model(device="cpu")


def fcpe(audio: np.ndarray, threshold: float = 0.006) -> Estimate:
    import torch

    model = _fcpe()
    wav = torch.from_numpy(np.ascontiguousarray(audio, dtype=np.float32))[None, :, None]
    frames = audio.size // 160 + 1
    with torch.no_grad():
        f0 = model.infer(
            wav, sr=SAMPLE_RATE, decoder_mode="local_argmax", threshold=threshold,
            f0_min=FMIN_HZ, f0_max=FMAX_HZ, interp_uv=False, output_interp_target_length=frames,
        )
    f0 = f0[0, :, 0].numpy().astype(np.float64)
    return Estimate(np.arange(f0.size) * 0.01, _clip_range(f0), (f0 > 0).astype(np.float64))


BASIC_PITCH_PYTHON = Path(
    os.environ.get("BASIC_PITCH_PYTHON", "")
)


def basic_pitch(audio: np.ndarray, threshold: float = 0.3) -> Estimate:
    """basic-pitch's contour posteriorgram, read as a melody: the strongest bin.

    basic-pitch is a polyphonic transcriber, not a melody tracker. It runs in
    its own environment (it brings TensorFlow/CoreML), so this shells out.
    """
    if not BASIC_PITCH_PYTHON.is_file():
        raise RuntimeError("set BASIC_PITCH_PYTHON to the basic-pitch environment's python")
    with tempfile.TemporaryDirectory() as directory:
        source = Path(directory) / "audio.wav"
        target = Path(directory) / "contour.npz"
        sf.write(source, audio, SAMPLE_RATE)
        subprocess.run(
            [str(BASIC_PITCH_PYTHON), "-I", str(Path(__file__).parent / "basic_pitch_worker.py"),
             str(source), str(target)],
            check=True, capture_output=True,
        )
        with np.load(target) as data:
            contour, times, freqs = data["contour"], data["times"], data["freqs"]
    peak_bin = np.argmax(contour, axis=1)
    peak = contour[np.arange(contour.shape[0]), peak_bin]
    # Refine the 1/3-semitone bin with a weighted average over its neighbours.
    log_f = np.log2(freqs)
    lo = np.clip(peak_bin - 1, 0, contour.shape[1] - 1)
    hi = np.clip(peak_bin + 1, 0, contour.shape[1] - 1)
    w = np.stack([contour[np.arange(len(lo)), lo], peak, contour[np.arange(len(hi)), hi]], axis=1)
    lf = np.stack([log_f[lo], log_f[peak_bin], log_f[hi]], axis=1)
    f0 = 2.0 ** ((w * lf).sum(1) / np.maximum(w.sum(1), 1e-9))
    f0[peak < threshold] = 0.0
    return Estimate(times, _clip_range(f0), peak)


TRACKERS = {
    "pyin (vocalika)": pyin_vocalika,
    "rmvpe": rmvpe,
    "crepe-full": crepe,
    "fcpe": fcpe,
    "basic-pitch": basic_pitch,
}


def describe() -> str:
    return json.dumps(sorted(TRACKERS))

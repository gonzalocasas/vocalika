"""Benchmark clips: audio plus the ground-truth f0 of the voice to be followed.

Conditions:

- ``vocadito``: 40 solo a cappella tracks, as recorded.
- ``vocadito-band-demucs``: each Vocadito vocal mixed at 0 dB into a real
  band instrumental, then separated with htdemucs -- the path every song and
  every full-mix take actually takes through Vocalika. Scored against the
  original annotation, so separation bleed and artifacts count against the
  tracker.
- ``csd-*``: Choral Singing Dataset, where each section was recorded alone
  and annotated by hand. Mixing them builds harmony with a known answer:
  ``lead6`` puts the soprano 6 dB over the alto; ``lowlead6`` puts the alto
  6 dB over the soprano (the melody below the harmony); ``duet0`` mixes the
  two at equal level, as in "Rasguña las piedras"; ``satb6`` puts the soprano
  6 dB over the other three sections.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

import librosa
import numpy as np
import soundfile as sf

REPO = Path(__file__).resolve().parents[2]
DATA = REPO / "tests" / "external-data"
CACHE = DATA / "pitch-bench-cache"
SAMPLE_RATE = 16_000


@dataclass
class Clip:
    name: str
    audio: np.ndarray
    ref_times: np.ndarray
    ref_f0: np.ndarray  # Hz, 0 where unvoiced
    # Other voices present in the mix, for "followed some voice" scoring.
    other_f0: list[tuple[np.ndarray, np.ndarray]] = field(default_factory=list)


def _load(path: Path) -> np.ndarray:
    audio, _ = librosa.load(path, sr=SAMPLE_RATE, mono=True)
    return audio.astype(np.float32)


def _rms(audio: np.ndarray, f0_times: np.ndarray, f0: np.ndarray) -> float:
    """RMS over the voiced stretches only, so long rests don't skew the balance."""
    voiced = np.zeros(audio.size, dtype=bool)
    hop = int(round(np.median(np.diff(f0_times)) * SAMPLE_RATE))
    for t in f0_times[f0 > 0]:
        i = int(t * SAMPLE_RATE)
        voiced[i : i + hop] = True
    sample = audio[voiced] if voiced.any() else audio
    return float(np.sqrt(np.mean(sample**2)) + 1e-12)


def _normalize(audio: np.ndarray) -> np.ndarray:
    return (0.9 * audio / (np.max(np.abs(audio)) + 1e-12)).astype(np.float32)


def vocadito() -> Iterator[Clip]:
    root = DATA / "vocadito"
    for track in range(1, 41):
        ann = np.loadtxt(root / "Annotations" / "F0" / f"vocadito_{track}_f0.csv", delimiter=",")
        yield Clip(f"vocadito_{track}", _load(root / "Audio" / f"vocadito_{track}.wav"), ann[:, 0], ann[:, 1])


def _instrumentals() -> list[Path]:
    projects = REPO / "analysis-output" / "projects"
    paths = []
    for project in sorted(projects.glob("*/project.json")):
        data = json.loads(project.read_text())
        path = Path(data["reference"]["instrumental_path"])
        if path.is_file():
            paths.append(path)
    return paths


def _separate(audio: np.ndarray, key: str) -> np.ndarray:
    """htdemucs vocal stem of ``audio``, cached on disk by content."""
    target = CACHE / "demucs" / f"{key}.wav"
    if target.is_file():
        return _load(target)
    import torch
    from demucs.apply import apply_model
    from demucs.pretrained import get_model

    model = _demucs_model()
    stereo = librosa.resample(audio, orig_sr=SAMPLE_RATE, target_sr=model.samplerate)
    wav = torch.from_numpy(np.stack([stereo, stereo]))[None].float()
    with torch.no_grad():
        sources = apply_model(model, wav, device="cpu", progress=False)[0]
    vocals = sources[model.sources.index("vocals")].mean(0).numpy()
    target.parent.mkdir(parents=True, exist_ok=True)
    sf.write(target, vocals, model.samplerate)
    return _load(target)


_DEMUCS = None


def _demucs_model():
    global _DEMUCS
    if _DEMUCS is None:
        from demucs.pretrained import get_model

        _DEMUCS = get_model("htdemucs")
        _DEMUCS.eval()
    return _DEMUCS


def vocadito_band_demucs() -> Iterator[Clip]:
    instrumentals = _instrumentals()
    if not instrumentals:
        raise RuntimeError("no project instrumentals found to mix Vocadito into")
    for clip in vocadito():
        index = int(clip.name.split("_")[1])
        source = instrumentals[index % len(instrumentals)]
        band = _load(source)
        start = (30 + 7 * index) * SAMPLE_RATE % max(1, band.size - clip.audio.size)
        band = band[start : start + clip.audio.size]
        band = np.pad(band, (0, clip.audio.size - band.size))
        vocal_rms = _rms(clip.audio, clip.ref_times, clip.ref_f0)
        band_rms = float(np.sqrt(np.mean(band**2)) + 1e-12)
        mix = _normalize(clip.audio + band * (vocal_rms / band_rms))
        key = hashlib.sha256(mix.tobytes()).hexdigest()[:16]
        yield Clip(f"{clip.name}+{source.parent.parent.name[:6]}", _separate(mix, key), clip.ref_times, clip.ref_f0)


def _csd(piece: str, section: str, singer: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    root = DATA / "csd" / "ChoralSingingDataset"
    ann = np.loadtxt(root / f"CSD_{piece}_{section}_{singer}.f0")
    return _load(root / f"CSD_{piece}_{section}_{singer}.wav"), ann[:, 0], ann[:, 1]


def _csd_mix(lead: str, others: list[str], others_db: float, singer: int = 1) -> Iterator[Clip]:
    for piece in ("ER", "LI", "ND"):
        lead_audio, lead_t, lead_f0 = _csd(piece, lead, singer)
        mix = lead_audio.copy()
        lead_rms = _rms(lead_audio, lead_t, lead_f0)
        voices = []
        for section in others:
            audio, t, f0 = _csd(piece, section, singer)
            n = min(mix.size, audio.size)
            gain = lead_rms / _rms(audio, t, f0) * 10 ** (others_db / 20)
            mix = mix[:n] + gain * audio[:n]
            voices.append((t, f0))
        tag = f"{lead}+{'+'.join(others)}@{others_db:+g}dB"
        yield Clip(f"CSD_{piece}_{tag}", _normalize(mix), lead_t, lead_f0, voices)


CONDITIONS = {
    "vocadito": vocadito,
    "vocadito-band-demucs": vocadito_band_demucs,
    "csd-lead6": lambda: _csd_mix("soprano", ["alto"], -6.0),
    "csd-lowlead6": lambda: _csd_mix("alto", ["soprano"], -6.0),
    "csd-duet0": lambda: _csd_mix("soprano", ["alto"], 0.0),
    "csd-satb6": lambda: _csd_mix("soprano", ["alto", "tenor", "bass"], -6.0),
}

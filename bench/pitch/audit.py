"""Ground-truth-free audit of trackers on real songs (the project library).

Real songs have no annotated f0, but three things can still be checked:

1. Coverage -- of the frames inside sung lyric lines where the vocal stem is
   clearly audible, how many get a pitch? (Lyric timing is imperfect, so this
   is an upper-bound-ish target, not a truth: breaths and consonants are
   inside lines too.)
2. Off-lyric pitch -- pitch reported outside any line, with its level.
3. Harmonic support -- does the spectrum actually contain a harmonic series
   on the reported f0? For each frame, harmonic-sum salience is computed
   over a semitone-spaced candidate grid; a reported f0 is "supported" when
   its salience is at least half the frame's best candidate. Octave errors
   and pitches latched onto noise score low. Two simultaneous voices both
   score high, so following either singer in a duet passes.

Also renders CQT spectrograms with every tracker drawn over them, for
looking at by eye.

    python bench/pitch/audit.py [--projects id,id] [--plot-seconds start-end] [--trackers ...]
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import librosa
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
import datasets  # noqa: E402
import trackers  # noqa: E402
from run import _grid  # noqa: E402

RESULTS = Path(__file__).parent / "results"
PROJECTS = datasets.REPO / "analysis-output" / "projects"


def harmonic_salience(audio: np.ndarray, grid: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(candidates_hz, salience[candidate, frame]) on a 10 ms grid, 1/4-semitone candidates."""
    n_fft, hop = 4096, 160
    spectrum = np.abs(librosa.stft(audio, n_fft=n_fft, hop_length=hop, center=True))
    spectrum = np.log1p(spectrum / (spectrum.max() + 1e-12) * 1000)  # compress dynamics
    freqs = librosa.fft_frequencies(sr=datasets.SAMPLE_RATE, n_fft=n_fft)
    candidates = librosa.midi_to_hz(np.arange(36.0, 84.25, 0.25))
    salience = np.zeros((candidates.size, spectrum.shape[1]))
    bin_hz = freqs[1]
    for i, f0 in enumerate(candidates):
        for h in range(1, 11):
            centre = f0 * h
            if centre > 5000:
                break
            # max within +-30 cents of the harmonic
            lo = int(np.floor(centre * 2 ** (-30 / 1200) / bin_hz))
            hi = int(np.ceil(centre * 2 ** (30 / 1200) / bin_hz)) + 1
            salience[i] += 0.84 ** (h - 1) * spectrum[lo:hi].max(axis=0)
    frames = np.minimum((grid * datasets.SAMPLE_RATE / hop).astype(int), salience.shape[1] - 1)
    return candidates, salience[:, frames]


def support(f0: np.ndarray, candidates: np.ndarray, salience: np.ndarray) -> np.ndarray:
    """Salience at each reported f0 relative to the frame's best candidate (nan if unvoiced)."""
    out = np.full(f0.size, np.nan)
    voiced = f0 > 0
    index = np.abs(np.log2(candidates[:, None] / np.where(voiced, f0, 1.0)[None, :])).argmin(0)
    best = salience.max(axis=0) + 1e-12
    out[voiced] = salience[index[voiced], np.flatnonzero(voiced)] / best[voiced]
    return out


def project_audio(project: dict) -> np.ndarray:
    return datasets._load(Path(project["reference"]["vocal_path"]))


def lyric_mask(project_id: str, grid: np.ndarray) -> np.ndarray | None:
    from vocalika.api.lyrics import build_lyrics_timing
    from vocalika.cache.manager import CacheManager
    from vocalika.projects.repository import ProjectRepository

    project = ProjectRepository(PROJECTS.resolve()).load(project_id)
    if not project.lyrics.strip():
        return None
    mask = np.zeros(grid.size, dtype=bool)
    for line in build_lyrics_timing(project, CacheManager.default())["lines"]:
        if line["start"] is not None:
            mask |= (grid >= line["start"]) & (grid <= line["end"])
    return mask


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--projects", default="")
    parser.add_argument("--trackers", default=",".join(trackers.TRACKERS))
    parser.add_argument("--plot", default="", help="project_id:start-end[,...] spectrogram overlays")
    args = parser.parse_args()
    from run import estimate_cached

    ids = args.projects.split(",") if args.projects else sorted(p.name for p in PROJECTS.iterdir() if (p / "project.json").is_file())
    names = args.trackers.split(",")
    rows = []
    for project_id in ids:
        project = json.loads((PROJECTS / project_id / "project.json").read_text())
        audio = project_audio(project)
        clip = datasets.Clip(f"library_{project_id}", audio, np.array([0.0]), np.array([0.0]))
        grid = np.arange(0.0, audio.size / datasets.SAMPLE_RATE, 0.01)
        frame = (grid * datasets.SAMPLE_RATE).astype(int)
        level = np.array([20 * np.log10(np.sqrt(np.mean(audio[max(0, i - 368) : i + 368] ** 2)) + 1e-12) for i in frame])
        loudest = np.percentile(level, 95)
        audible = level > loudest - 25
        sung = lyric_mask(project_id, grid)
        candidates, salience = harmonic_salience(audio, grid)
        for name in names:
            estimate, elapsed = estimate_cached(name, clip)
            f0 = _grid(estimate.times, estimate.f0_hz, grid)
            voiced = f0 > 0
            sup = support(f0, candidates, salience)
            row = {
                "project": project["title"], "tracker": name,
                "coverage_in_lines": float(np.mean(voiced[sung & audible])) if sung is not None else None,
                "voiced_s_outside_lines": float(np.sum(voiced & ~sung) * 0.01) if sung is not None else None,
                "voiced_s_outside_lines_quiet": float(np.sum(voiced & ~sung & ~audible) * 0.01) if sung is not None else None,
                "harmonic_support_median": float(np.nanmedian(sup)) if voiced.any() else None,
                "weakly_supported_share": float(np.mean(sup[voiced] < 0.5)) if voiced.any() else None,
                "realtime_factor": audio.size / datasets.SAMPLE_RATE / max(elapsed, 1e-9),
            }
            rows.append(row)
            print(json.dumps({k: (round(v, 3) if isinstance(v, float) else v) for k, v in row.items()}), flush=True)
    if rows:
        RESULTS.mkdir(exist_ok=True)
        with (RESULTS / "library_audit.csv").open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    for spec in filter(None, args.plot.split(",")):
        plot(spec, names)


def plot(spec: str, names: list[str]) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from run import estimate_cached

    project_id, span = spec.split(":")
    start, end = (float(x) for x in span.split("-"))
    project = json.loads((PROJECTS / project_id / "project.json").read_text())
    audio = project_audio(project)
    clip = datasets.Clip(f"library_{project_id}", audio, np.array([0.0]), np.array([0.0]))
    segment = audio[int(start * datasets.SAMPLE_RATE) : int(end * datasets.SAMPLE_RATE)]
    cqt = librosa.amplitude_to_db(
        np.abs(librosa.cqt(segment, sr=datasets.SAMPLE_RATE, hop_length=160, fmin=librosa.note_to_hz("C2"), n_bins=72)),
        ref=np.max,
    )
    fig, axes = plt.subplots(len(names), 1, figsize=(14, 3.2 * len(names)), sharex=True)
    for ax, name in zip(np.atleast_1d(axes), names):
        ax.imshow(cqt, origin="lower", aspect="auto", cmap="magma", vmin=-60,
                  extent=(start, end, 36 - 0.5, 36 + 72 - 0.5))
        estimate, _ = estimate_cached(name, clip)
        keep = (estimate.times >= start) & (estimate.times <= end)
        midi = np.where(estimate.f0_hz[keep] > 0, librosa.hz_to_midi(np.maximum(estimate.f0_hz[keep], 1e-6)), np.nan)
        ax.plot(estimate.times[keep], midi, color="cyan", linewidth=1.6)
        ax.set_ylabel("MIDI")
        ax.set_title(f"{project['title']} — {name}", fontsize=10)
    np.atleast_1d(axes)[-1].set_xlabel("seconds")
    fig.tight_layout()
    out = RESULTS / f"overlay_{project_id[:8]}_{int(start)}-{int(end)}.png"
    fig.savefig(out, dpi=70)
    print("wrote", out)


if __name__ == "__main__":
    main()

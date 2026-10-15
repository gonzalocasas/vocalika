"""Score every tracker on every condition.

    BASIC_PITCH_PYTHON=... python bench/pitch/run.py [--conditions a,b] [--trackers x,y]

Estimates are cached per (tracker, clip) so a rerun only scores. Results go
to bench/pitch/results/<condition>.csv (per clip) and summary.csv.

Metrics, on a 10 ms grid (mir_eval conventions):
- voicing recall / false alarm: did it say "singing" where the lead sings / doesn't.
- RPA: raw pitch accuracy, voiced reference frames within 50 cents.
- RPA25: the same within 25 cents -- closer to what Vocalika's feedback needs.
- RCA: raw chroma accuracy (octave errors forgiven); RCA - RPA = octave errors.
- median cents: median |error| on frames where both are voiced and within 100 c.
- either-voice: frames within 50 c of *any* voice in the mix (harmony conditions),
  i.e. it followed a real singer, just maybe not the lead.
- OA: overall accuracy (voicing and pitch together).
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from pathlib import Path

import mir_eval
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
import datasets  # noqa: E402
import trackers  # noqa: E402

RESULTS = Path(__file__).parent / "results"


def _grid(times: np.ndarray, f0: np.ndarray, grid: np.ndarray) -> np.ndarray:
    """Nearest-frame resampling; never interpolates across voicing changes."""
    index = np.clip(np.searchsorted(times, grid), 1, len(times) - 1)
    left = np.abs(times[index - 1] - grid) <= np.abs(times[index] - grid)
    return f0[index - left]


def score(clip: datasets.Clip, estimate: trackers.Estimate) -> dict[str, float]:
    duration = min(clip.ref_times[-1], len(clip.audio) / datasets.SAMPLE_RATE)
    grid = np.arange(0.0, duration, 0.01)
    ref = _grid(clip.ref_times, clip.ref_f0, grid)
    est = _grid(estimate.times, estimate.f0_hz, grid)
    ref_v, ref_c, est_v, est_c = mir_eval.melody.to_cent_voicing(grid, ref, grid, est, hop=0.01)
    both = (ref > 0) & (est > 0)
    cents = np.abs(1200 * np.log2(est[both] / ref[both]))
    either = np.zeros(ref.size, dtype=bool)
    either[both] = cents <= 50
    for times, f0 in clip.other_f0:
        other = _grid(times, f0, grid)
        ok = (other > 0) & (est > 0)
        either[ok] |= np.abs(1200 * np.log2(est[ok] / other[ok])) <= 50
    voiced_ref = ref > 0
    return {
        "voicing_recall": mir_eval.melody.voicing_recall(ref_v, est_v),
        "voicing_false_alarm": mir_eval.melody.voicing_false_alarm(ref_v, est_v),
        "rpa": mir_eval.melody.raw_pitch_accuracy(ref_v, ref_c, est_v, est_c, cent_tolerance=50),
        "rpa25": mir_eval.melody.raw_pitch_accuracy(ref_v, ref_c, est_v, est_c, cent_tolerance=25),
        "rca": mir_eval.melody.raw_chroma_accuracy(ref_v, ref_c, est_v, est_c),
        "oa": mir_eval.melody.overall_accuracy(ref_v, ref_c, est_v, est_c),
        "median_cents": float(np.median(cents[cents <= 100])) if np.any(cents <= 100) else float("nan"),
        "either_voice": float(np.mean(either[voiced_ref])) if voiced_ref.any() else float("nan"),
        "seconds": float(voiced_ref.sum() * 0.01),
    }


def estimate_cached(tracker: str, clip: datasets.Clip) -> tuple[trackers.Estimate, float]:
    safe = tracker.replace(" ", "_").replace("(", "").replace(")", "")
    path = datasets.CACHE / "estimates" / safe / f"{clip.name}.npz"
    if path.is_file():
        with np.load(path) as data:
            return trackers.Estimate(data["times"], data["f0"], data["confidence"]), float(data["elapsed"])
    started = time.perf_counter()
    estimate = trackers.TRACKERS[tracker](clip.audio)
    elapsed = time.perf_counter() - started
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez(path, times=estimate.times, f0=estimate.f0_hz, confidence=estimate.confidence, elapsed=elapsed)
    return estimate, elapsed


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--conditions", default=",".join(datasets.CONDITIONS))
    parser.add_argument("--trackers", default=",".join(trackers.TRACKERS))
    args = parser.parse_args()
    RESULTS.mkdir(exist_ok=True)
    summary_rows = []
    for condition in args.conditions.split(","):
        rows = []
        for clip in datasets.CONDITIONS[condition]():
            audio_seconds = clip.audio.size / datasets.SAMPLE_RATE
            for tracker in args.trackers.split(","):
                estimate, elapsed = estimate_cached(tracker, clip)
                row = {"condition": condition, "clip": clip.name, "tracker": tracker,
                       "realtime_factor": audio_seconds / max(elapsed, 1e-9), **score(clip, estimate)}
                rows.append(row)
                print(f"{condition:22} {clip.name:40} {tracker:16} RPA {row['rpa']:.3f} "
                      f"VR {row['voicing_recall']:.3f} VFA {row['voicing_false_alarm']:.3f}", flush=True)
        with (RESULTS / f"{condition}.csv").open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        for tracker in args.trackers.split(","):
            mine = [r for r in rows if r["tracker"] == tracker]
            weights = np.array([r["seconds"] for r in mine])
            summary = {"condition": condition, "tracker": tracker, "clips": len(mine)}
            for key in ("voicing_recall", "voicing_false_alarm", "rpa", "rpa25", "rca", "oa",
                        "median_cents", "either_voice", "realtime_factor"):
                values = np.array([r[key] for r in mine], dtype=float)
                ok = np.isfinite(values)
                summary[key] = round(float(np.average(values[ok], weights=weights[ok])), 4) if ok.any() else None
            summary_rows.append(summary)
    path = RESULTS / "summary.csv"
    existing = []
    if path.is_file():
        done = {(r["condition"], r["tracker"]) for r in summary_rows}
        with path.open() as handle:
            existing = [r for r in csv.DictReader(handle) if (r["condition"], r["tracker"]) not in done]
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(summary_rows[0]))
        writer.writeheader()
        writer.writerows(existing + summary_rows)


if __name__ == "__main__":
    main()

from __future__ import annotations

import csv
import os
import tempfile
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import librosa
import numpy as np
import pytest
import soundfile as sf

from vocalika.analysis.alignment import align_pitch_tracks
from vocalika.analysis.comparison import ComparisonResult, compare_alignment
from vocalika.analysis.pitch import PitchTrack, PyinPitchExtractor

DEFAULT_DATA_ROOT = Path(__file__).parents[1] / "external-data"
DATA_ROOT = Path(os.environ.get("VOCALIKA_OPEN_DATA_DIR", DEFAULT_DATA_ROOT))
FETCH_COMMAND = "uv run python scripts/fetch_open_datasets.py"

pytestmark = pytest.mark.open_data


def _dataset_root(key: str) -> Path:
    root = DATA_ROOT / key
    if not (root / ".vocalika-dataset.json").is_file():
        pytest.skip(f"optional dataset {key!r} is absent; fetch it with: {FETCH_COMMAND} {key}")
    return root


VOCADITO_BASELINE_PATH = Path(__file__).parent / "vocadito_pitch_baseline.csv"
with VOCADITO_BASELINE_PATH.open(newline="", encoding="utf-8") as _source:
    VOCADITO_BASELINE = {int(row["track_id"]): row for row in csv.DictReader(_source)}

# Tolerances applied to the recorded per-track baseline. They are wide enough to
# absorb a faithful reimplementation of pyin -- which will not be bit-exact,
# because a different FFT shifts results in the last decimal places -- while
# still failing on a genuine accuracy regression.
CENTS_TOLERANCE_FACTOR = 1.5
CENTS_TOLERANCE_FLOOR = 3.0
WITHIN_50_TOLERANCE = 0.08
FRAMES_TOLERANCE_FACTOR = 0.8
# The mean is only stable on tracks free of octave errors, so it carries a
# looser factor and is asserted only for those. It exists to catch a regression
# in the error tail, which the median cannot see.
MEAN_CENTS_TOLERANCE_FACTOR = 1.4

# pyin drops an octave on a handful of tracks. The error is confined to a small
# fraction of frames -- median accuracy on these tracks stays in single-digit
# cents -- but it inflates the mean badly, which is why per-track bars below key
# off the median. Tracked explicitly so a fix or a regression is visible.
VOCADITO_OCTAVE_ERROR_TRACKS = {17, 18, 29, 34}


@dataclass(frozen=True)
class VocaditoMeasurement:
    track_id: int
    frames: int
    median_cents: float
    mean_cents: float
    within_50: float
    within_25: float
    octave_errors: float
    voicing_recall: float


def _measure_vocadito_track(arguments: tuple[Path, int]) -> VocaditoMeasurement:
    """Extract one track and score it against the published frame-level F0."""
    root, track_id = arguments
    audio, sample_rate = librosa.load(
        root / "Audio" / f"vocadito_{track_id}.wav", sr=16_000, mono=True
    )
    with tempfile.TemporaryDirectory() as directory:
        resampled_path = Path(directory) / f"vocadito_{track_id}.wav"
        sf.write(resampled_path, audio, sample_rate)
        estimate = PyinPitchExtractor().extract(resampled_path)

    annotation = np.loadtxt(
        root / "Annotations" / "F0" / f"vocadito_{track_id}_f0.csv", delimiter=","
    )
    right_indices = np.searchsorted(annotation[:, 0], estimate.times)
    right_indices = np.clip(right_indices, 1, annotation.shape[0] - 1)
    use_left = np.abs(annotation[right_indices - 1, 0] - estimate.times) < np.abs(
        annotation[right_indices, 0] - estimate.times
    )
    expected_frequency = annotation[right_indices - use_left, 1]
    confident = estimate.voiced & (estimate.confidence >= 0.55)
    valid = confident & np.isfinite(estimate.raw_frequency_hz) & (expected_frequency > 0.0)
    cents_error = np.abs(
        1200.0 * np.log2(estimate.raw_frequency_hz[valid] / expected_frequency[valid])
    )
    annotated_voiced = expected_frequency > 0.0
    return VocaditoMeasurement(
        track_id=track_id,
        frames=int(np.count_nonzero(valid)),
        median_cents=float(np.median(cents_error)),
        mean_cents=float(np.mean(cents_error)),
        within_50=float(np.mean(cents_error <= 50.0)),
        within_25=float(np.mean(cents_error <= 25.0)),
        # An octave error lands ~1200 cents away from the annotation.
        octave_errors=float(np.mean(np.abs(cents_error - 1200.0) < 100.0)),
        voicing_recall=float(np.mean(confident[annotated_voiced])),
    )


@pytest.fixture(scope="session")
def vocadito_measurements() -> dict[int, VocaditoMeasurement]:
    """Score every vocadito track once and share the result across the module.

    Extraction dominates the cost (roughly two minutes of pyin over the full
    13.6 minutes of audio), so tracks are measured in parallel.
    """
    root = _dataset_root("vocadito")
    track_ids = sorted(VOCADITO_BASELINE)
    workers = min(8, os.cpu_count() or 1)
    with ProcessPoolExecutor(max_workers=workers) as pool:
        measurements = pool.map(_measure_vocadito_track, [(root, i) for i in track_ids])
        return {measurement.track_id: measurement for measurement in measurements}


@pytest.mark.parametrize("track_id", sorted(VOCADITO_BASELINE))
def test_vocadito_pyin_matches_frame_level_f0(
    track_id: int,
    vocadito_measurements: dict[int, VocaditoMeasurement],
) -> None:
    """Every track must stay within tolerance of its recorded accuracy.

    Keying off the median rather than the mean keeps the bar meaningful on the
    tracks where a few octave errors dominate the average.
    """
    measured = vocadito_measurements[track_id]
    baseline = VOCADITO_BASELINE[track_id]

    frames_floor = int(float(baseline["frames"]) * FRAMES_TOLERANCE_FACTOR)
    cents_ceiling = float(baseline["median_cents"]) * CENTS_TOLERANCE_FACTOR + CENTS_TOLERANCE_FLOOR
    within_50_floor = float(baseline["within_50"]) - WITHIN_50_TOLERANCE

    assert measured.frames >= frames_floor
    assert measured.median_cents <= cents_ceiling
    assert measured.within_50 >= within_50_floor
    if track_id not in VOCADITO_OCTAVE_ERROR_TRACKS:
        assert measured.mean_cents <= float(baseline["mean_cents"]) * MEAN_CENTS_TOLERANCE_FACTOR


def test_vocadito_accuracy_holds_across_the_whole_dataset(
    vocadito_measurements: dict[int, VocaditoMeasurement],
) -> None:
    """Dataset-wide bars over 40 tracks, 29 singers, and 9 languages."""
    measurements = list(vocadito_measurements.values())
    median_cents = np.array([m.median_cents for m in measurements])
    within_50 = np.array([m.within_50 for m in measurements])
    within_25 = np.array([m.within_25 for m in measurements])

    # Bars sit roughly 20% off the recorded baseline: far outside the drift a
    # faithful reimplementation would produce, well inside a real regression.
    assert len(measurements) == 40
    assert float(np.median(median_cents)) < 12.0
    assert float(np.max(median_cents)) < 20.0
    assert float(np.median(within_50)) > 0.91
    assert float(np.min(within_50)) > 0.80
    assert float(np.median(within_25)) > 0.78
    # Every track must contribute enough confident frames to be meaningful.
    assert min(m.frames for m in measurements) >= 250


def test_vocadito_octave_errors_stay_confined_to_known_tracks(
    vocadito_measurements: dict[int, VocaditoMeasurement],
) -> None:
    """Pin the octave-halving weakness so it cannot spread silently.

    Track 34 is the worst case: pyin tracks a sub-harmonic for part of the
    performance, which collapses its voicing recall and inflates its mean error
    to roughly 87 cents even though its median stays near 8.
    """
    affected = {
        track_id
        for track_id, measurement in vocadito_measurements.items()
        if measurement.octave_errors > 0.0
    }
    assert affected <= VOCADITO_OCTAVE_ERROR_TRACKS, (
        f"octave errors appeared on new tracks: {sorted(affected - VOCADITO_OCTAVE_ERROR_TRACKS)}"
    )
    for track_id in affected:
        assert vocadito_measurements[track_id].octave_errors < 0.10
    unaffected = [
        measurement
        for track_id, measurement in vocadito_measurements.items()
        if track_id not in VOCADITO_OCTAVE_ERROR_TRACKS
    ]
    assert max(measurement.mean_cents for measurement in unaffected) < 30.0


def _mast_track(root: Path, stem: str) -> PitchTrack:
    f0_path = root / "f0data_crepe" / "MAST_melody_f0" / f"{stem}.f0.npy"
    frequency = np.asarray(np.load(f0_path, allow_pickle=False), dtype=np.float64)
    voiced = np.isfinite(frequency) & (frequency > 0.0)
    midi = np.full_like(frequency, np.nan)
    midi[voiced] = 69.0 + 12.0 * np.log2(frequency[voiced] / 440.0)
    return PitchTrack(
        times=np.arange(frequency.size, dtype=np.float64) * 0.01,
        raw_frequency_hz=frequency,
        raw_midi=midi.copy(),
        midi=midi,
        confidence=voiced.astype(np.float64),
        voiced=voiced,
        extractor="MAST-published-CREPE",
        sample_rate=8_000,
        hop_length=80,
    )


def _mast_comparison(root: Path, performance_stem: str) -> ComparisonResult:
    reference_stem = performance_stem.replace("_per", "_ref", 1)
    alignment = align_pitch_tracks(
        _mast_track(root, reference_stem),
        _mast_track(root, performance_stem),
    )
    return compare_alignment(alignment)


def _mast_unanimous_score(root: Path, performance_stem: str) -> float:
    annotations = root / "annotations" / "annotations.csv"
    with annotations.open(newline="", encoding="utf-8") as source:
        for row in csv.DictReader(source):
            if Path(row["file"]).stem == performance_stem:
                assert row["fullAgree"] == "True"
                return float(row["fullAgree_score"])
    raise AssertionError(f"MAST annotation is missing for {performance_stem}")


def test_mast_expert_ratings_separate_perfect_and_completely_off_performances() -> None:
    root = _dataset_root("mast-melody")
    completely_off_stem = "59_mel1_per160759"
    perfect_stem = "55_mel1_per172159"

    assert _mast_unanimous_score(root, completely_off_stem) == 1.0
    assert _mast_unanimous_score(root, perfect_stem) == 4.0

    completely_off = _mast_comparison(root, completely_off_stem)
    perfect = _mast_comparison(root, perfect_stem)

    assert perfect.relative_mean_absolute_error_cents < 50.0
    assert perfect.relative_within_50_percent > 75.0
    assert completely_off.relative_mean_absolute_error_cents > 100.0
    assert perfect.relative_mean_absolute_error_cents < (
        completely_off.relative_mean_absolute_error_cents / 3.0
    )


def test_mast_unanimous_ratings_rank_across_the_paired_dataset() -> None:
    root = _dataset_root("mast-melody")
    f0_root = root / "f0data_crepe" / "MAST_melody_f0"
    annotations = root / "annotations" / "annotations.csv"
    scores: dict[int, list[float]] = {1: [], 4: []}

    with annotations.open(newline="", encoding="utf-8") as source:
        for row in csv.DictReader(source):
            if row["fullAgree_score"] not in {"1.0", "4.0"}:
                continue
            performance_stem = Path(row["file"]).stem
            if "_per" not in performance_stem:
                continue
            reference_stem = performance_stem.replace("_per", "_ref", 1)
            if not (f0_root / f"{reference_stem}.f0.npy").is_file():
                continue
            score = int(float(row["fullAgree_score"]))
            comparison = _mast_comparison(root, performance_stem)
            scores[score].append(comparison.relative_mean_absolute_error_cents)

    completely_off = np.asarray(scores[1])
    perfect = np.asarray(scores[4])
    pairwise_ranking_accuracy = float(
        np.mean(perfect[:, np.newaxis] < completely_off[np.newaxis, :])
    )

    assert completely_off.size == 197
    assert perfect.size == 192
    assert np.median(perfect) < 40.0
    assert np.median(completely_off) > 120.0
    assert pairwise_ranking_accuracy > 0.96


def test_mast_melodic_motion_regression_case_aligns_correctly() -> None:
    root = _dataset_root("mast-melody")

    comparison = _mast_comparison(root, "55_mel2_per161659")

    assert comparison.relative_mean_absolute_error_cents < 50.0
    assert comparison.relative_within_50_percent > 75.0

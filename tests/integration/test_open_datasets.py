from __future__ import annotations

import csv
import os
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


@pytest.mark.parametrize("track_id", [1, 6])
def test_vocadito_pyin_matches_frame_level_f0(
    track_id: int,
    tmp_path: Path,
) -> None:
    root = _dataset_root("vocadito")
    audio_path = root / "Audio" / f"vocadito_{track_id}.wav"
    annotation_path = root / "Annotations" / "F0" / f"vocadito_{track_id}_f0.csv"

    audio, sample_rate = librosa.load(audio_path, sr=16_000, mono=True, duration=8.0)
    excerpt_path = tmp_path / f"vocadito_{track_id}.wav"
    sf.write(excerpt_path, audio, sample_rate)
    estimate = PyinPitchExtractor().extract(excerpt_path)
    annotation = np.loadtxt(annotation_path, delimiter=",")

    right_indices = np.searchsorted(annotation[:, 0], estimate.times)
    right_indices = np.clip(right_indices, 1, annotation.shape[0] - 1)
    use_left = np.abs(annotation[right_indices - 1, 0] - estimate.times) < np.abs(
        annotation[right_indices, 0] - estimate.times
    )
    annotation_indices = right_indices - use_left
    expected_frequency = annotation[annotation_indices, 1]
    valid = (
        estimate.voiced
        & (estimate.confidence >= 0.55)
        & np.isfinite(estimate.raw_frequency_hz)
        & (expected_frequency > 0.0)
    )
    cents_error = np.abs(
        1200.0 * np.log2(estimate.raw_frequency_hz[valid] / expected_frequency[valid])
    )

    # Harmonic preprocessing should retain most annotated vocal frames without
    # relaxing the 0.55 confidence gate.
    assert np.count_nonzero(valid) >= 250
    assert np.mean(cents_error) < 25.0
    assert np.mean(cents_error <= 50.0) > 0.90


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

"""Pin the pipeline's full output against checked-in golden artifacts.

These exist so an alternative backend can be held to the numbers the current
implementation produces. A diff here means the analysis changed -- intentionally
or not. When it is intentional, regenerate with:

    uv run python scripts/regenerate_golden_artifacts.py
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import pytest

from vocalika.models.artifact import compare_artifacts, load_artifact, normalize_artifact
from vocalika.pipeline import run_analysis

FIXTURE_DIRECTORY = Path(__file__).parents[1] / "fixtures" / "pitch_validation_samples"
GOLDEN_DIRECTORY = Path(__file__).parents[1] / "golden"
REGENERATE_COMMAND = "uv run python scripts/regenerate_golden_artifacts.py"

with (FIXTURE_DIRECTORY / "README.csv").open(newline="", encoding="utf-8") as _source:
    CASES = list(csv.DictReader(_source))

# Every number in the artifact is derived deterministically from the audio, so
# on one platform the only slack needed is for floating-point summation order.
RELATIVE_TOLERANCE = 1e-9
ABSOLUTE_TOLERANCE = 1e-12

# Across platforms it is not: torch's CPU kernels differ between Apple Silicon
# and x86, so RMVPE's pitch and confidence move in the fourth decimal, and
# everything computed from them follows. These bounds sit about five times
# above the worst drift measured between macOS arm64 and Linux x86-64
# (pitch 0.0006 semitones, cents 0.09, confidence 0.001; one frame of 150
# crossing a percentage threshold). Frame pairing can also break a near-tie
# at a note onset the other way, pairing a frame with its neighbour: one
# 20 ms step, and that neighbour's confidence, which can differ by 0.01.
# Everything else discrete stays strict -- which frames are voiced and
# valid, every stable region's boundaries, the chosen offset and how it was
# chosen -- so a real change still fails.
FRAME_STEP_SECONDS = 0.02
PATH_TOLERANCES: dict[str, float] = {
    "comparison.frames.reference_time": FRAME_STEP_SECONDS + 1e-9,
    "comparison.frames.performance_time": FRAME_STEP_SECONDS + 1e-9,
    "comparison.frames.confidence": 0.02,
    "comparison.frames.performance_confidence": 0.02,
    "comparison.frames.reference_confidence": 0.02,
    "comparison.frames.performance_midi": 3e-3,
    "comparison.frames.reference_midi": 3e-3,
    "comparison.frames.absolute_error_cents": 0.5,
    "comparison.frames.relative_error_cents": 0.5,
    "comparison.stable_pitch_regions.confidence": 2e-3,
    "comparison.stable_pitch_regions.performance_center_midi": 2e-3,
    "comparison.stable_pitch_regions.reference_center_midi": 2e-3,
    "comparison.stable_pitch_regions.reference_span_cents": 0.02,
    "comparison.stable_pitch_regions.error_cents": 0.25,
    "comparison.stable_pitch_regions.relative_error_cents": 0.25,
    "comparison.summary.global_bias_cents": 0.25,
    "comparison.summary.mean_absolute_error_cents": 0.25,
    "comparison.summary.median_absolute_error_cents": 0.25,
    "comparison.summary.relative_mean_absolute_error_cents": 0.25,
    "comparison.summary.relative_median_absolute_error_cents": 0.25,
    "comparison.summary.stable_note_": 0.25,
    "comparison.summary.relative_stable_note_": 0.25,
    # One frame crossing a threshold moves a share by 100/frames points.
    "comparison.summary.within_": 1.0,
    "comparison.summary.relative_within_": 1.0,
    # Diagnostic scores of the offsets considered; the choice stays strict.
    "alignment.global_offset_candidates.raw_correlation": 1e-4,
    "alignment.global_offset_candidates.peak_margin": 1e-5,
    "alignment.global_offset_candidates.confidence": 1e-6,
}


@pytest.fixture(scope="module")
def generated_artifacts(tmp_path_factory: pytest.TempPathFactory) -> dict[str, dict[str, Any]]:
    """Run the pipeline once per fixture and share the normalized results."""
    working_directory = tmp_path_factory.mktemp("golden")
    cache_directory = working_directory / "cache"
    artifacts: dict[str, dict[str, Any]] = {}
    for case in CASES:
        name = Path(case["test_file"]).stem
        artifact_path = run_analysis(
            FIXTURE_DIRECTORY / case["reference_file"],
            FIXTURE_DIRECTORY / case["test_file"],
            working_directory / name,
            reference_is_vocal=True,
            cache_directory=cache_directory,
        )
        artifacts[name] = normalize_artifact(load_artifact(artifact_path))
    return artifacts


def test_every_fixture_has_a_golden_artifact() -> None:
    expected = {Path(case["test_file"]).stem for case in CASES}
    available = {path.stem for path in GOLDEN_DIRECTORY.glob("*.json")}
    assert expected == available, f"golden set is stale; regenerate with: {REGENERATE_COMMAND}"


@pytest.mark.parametrize("name", sorted(Path(case["test_file"]).stem for case in CASES))
def test_pipeline_output_matches_the_golden_artifact(
    name: str,
    generated_artifacts: dict[str, dict[str, Any]],
) -> None:
    with (GOLDEN_DIRECTORY / f"{name}.json").open(encoding="utf-8") as source:
        expected = json.load(source)

    differences = list(
        compare_artifacts(
            expected,
            generated_artifacts[name],
            relative_tolerance=RELATIVE_TOLERANCE,
            absolute_tolerance=ABSOLUTE_TOLERANCE,
            path_tolerances=PATH_TOLERANCES,
        )
    )
    assert not differences, "\n".join(
        [f"{len(differences)} difference(s) against the golden artifact:", *differences[:20]]
    )


def test_goldens_cover_the_measurements_a_backend_must_reproduce(
    generated_artifacts: dict[str, dict[str, Any]],
) -> None:
    """Guard the goldens' own value: they must pin real numbers, not just shape."""
    artifact = generated_artifacts["05_test_one_wrong_note_E4_to_F4"]
    summary = artifact["comparison"]["summary"]
    frames = artifact["comparison"]["frames"]

    for key in (
        "global_bias_cents",
        "mean_absolute_error_cents",
        "relative_mean_absolute_error_cents",
        "within_50_percent",
        "valid_frame_count",
        "matched_seconds",
    ):
        assert key in summary, f"summary lost {key}"
    for key in ("reference_midi", "performance_midi", "absolute_error_cents", "valid"):
        assert len(frames[key]) > 0, f"frame array {key} is empty"
    assert artifact["alignment"]["point_count"] > 0
    # The goldens are backend-agnostic: any implementation must record which
    # extractor produced the track, but the harness does not care which one.
    assert artifact["pitch"]["extractor"]


def test_a_field_tolerance_covers_every_list_element_and_nothing_else() -> None:
    expected = {"regions": [{"error_cents": 1.0, "start": 2.0}, {"error_cents": 3.0, "start": 4.0}]}
    drifted = {"regions": [{"error_cents": 1.1, "start": 2.0}, {"error_cents": 2.9, "start": 4.0}]}
    moved = {"regions": [{"error_cents": 1.0, "start": 2.1}, {"error_cents": 3.0, "start": 4.0}]}
    tolerances = {"regions.error_cents": 0.25}

    assert not list(compare_artifacts(expected, drifted, path_tolerances=tolerances))
    assert list(compare_artifacts(expected, moved, path_tolerances=tolerances)) == [
        "regions[0].start: 2.0 != 2.1"
    ]

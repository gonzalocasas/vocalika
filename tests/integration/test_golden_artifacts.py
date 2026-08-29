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
# the only slack needed is for floating-point summation order.
RELATIVE_TOLERANCE = 1e-9
ABSOLUTE_TOLERANCE = 1e-12

# The pipeline is deterministic end to end, so the goldens are held to the
# strict tolerance everywhere. If a future backend's resampler shifts the
# offset estimators' correlation scores, loosen only those diagnostic paths
# here -- `global_offset_seconds`, `_method`, and `_applied` should stay
# strict so a drift large enough to change the selection still fails.
PATH_TOLERANCES: dict[str, float] = {}


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

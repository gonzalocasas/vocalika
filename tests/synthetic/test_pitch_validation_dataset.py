from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from vocalika.pipeline import run_analysis

FIXTURE_DIRECTORY = Path(__file__).parents[1] / "fixtures" / "pitch_validation_samples"

with (FIXTURE_DIRECTORY / "README.csv").open(newline="", encoding="utf-8") as source:
    MANIFEST = list(csv.DictReader(source))

GROUND_TRUTH_CASES = [
    row for row in MANIFEST if row["expected_global_bias_cents"] and row["expected_abs_mae_cents"]
]


@pytest.fixture(scope="session")
def pitch_validation_artifacts(
    tmp_path_factory: pytest.TempPathFactory,
) -> dict[str, dict[str, Any]]:
    working_directory = tmp_path_factory.mktemp("pitch-validation")
    cache_directory = working_directory / "cache"
    results: dict[str, dict[str, Any]] = {}
    for row in MANIFEST:
        test_file = row["test_file"]
        artifact_path = run_analysis(
            FIXTURE_DIRECTORY / row["reference_file"],
            FIXTURE_DIRECTORY / test_file,
            working_directory / Path(test_file).stem,
            reference_is_vocal=True,
            cache_directory=cache_directory,
        )
        with artifact_path.open(encoding="utf-8") as artifact_source:
            results[test_file] = json.load(artifact_source)
    return results


def test_manifest_covers_every_audio_fixture() -> None:
    manifested = {row["test_file"] for row in MANIFEST} | {
        row["reference_file"] for row in MANIFEST
    }
    available = {path.name for path in FIXTURE_DIRECTORY.glob("*.wav")}

    assert manifested == available


@pytest.mark.parametrize(
    "case",
    GROUND_TRUTH_CASES,
    ids=[row["test_file"] for row in GROUND_TRUTH_CASES],
)
def test_reported_bias_and_mae_match_manifest_ground_truth(
    pitch_validation_artifacts: dict[str, dict[str, Any]],
    case: dict[str, str],
) -> None:
    summary = pitch_validation_artifacts[case["test_file"]]["comparison"]["summary"]
    expected_bias = float(case["expected_global_bias_cents"])
    expected_mae = float(case["expected_abs_mae_cents"])

    assert summary["global_bias_cents"] == pytest.approx(expected_bias, abs=6.0)
    assert summary["mean_absolute_error_cents"] == pytest.approx(expected_mae, abs=6.0)
    assert summary["relative_mean_absolute_error_cents"] < 5.0


def test_delayed_melody_recovers_250_ms_before_comparison(
    pitch_validation_artifacts: dict[str, dict[str, Any]],
) -> None:
    artifact = pitch_validation_artifacts["03_test_same_melody_plus250ms.wav"]
    alignment = artifact["alignment"]
    summary = artifact["comparison"]["summary"]
    frames = artifact["comparison"]["frames"]
    valid = np.asarray(frames["valid"], dtype=np.bool_)
    paired_offsets = (
        np.asarray(frames["performance_time"])[valid] - np.asarray(frames["reference_time"])[valid]
    )

    assert alignment["global_offset_seconds"] == pytest.approx(0.25, abs=0.02)
    assert alignment["global_offset_confidence"] > 0.95
    assert alignment["global_offset_applied"] is True
    assert np.median(paired_offsets) == pytest.approx(0.25, abs=0.02)
    assert summary["global_bias_cents"] == pytest.approx(0.0, abs=5.0)
    assert summary["mean_absolute_error_cents"] < 5.0
    assert summary["within_25_percent"] > 95.0
    assert summary["within_50_percent"] > 95.0


def test_transposed_melody_does_not_create_a_false_audio_offset(
    pitch_validation_artifacts: dict[str, dict[str, Any]],
) -> None:
    artifact = pitch_validation_artifacts["02_test_plus200c.wav"]

    assert artifact["alignment"]["global_offset_applied"] is False
    assert artifact["comparison"]["summary"]["global_bias_cents"] == pytest.approx(
        200.0,
        abs=5.0,
    )


def test_vibrato_has_neutral_bias_but_nonzero_contour_error(
    pitch_validation_artifacts: dict[str, dict[str, Any]],
) -> None:
    summary = pitch_validation_artifacts["04_test_same_melody_vibrato_pm30c_5Hz.wav"]["comparison"][
        "summary"
    ]

    assert summary["global_bias_cents"] == pytest.approx(0.0, abs=5.0)
    assert 5.0 < summary["mean_absolute_error_cents"] < 20.0
    assert summary["within_25_percent"] > 90.0


def test_one_wrong_note_is_localized_to_one_quarter_of_the_melody(
    pitch_validation_artifacts: dict[str, dict[str, Any]],
) -> None:
    artifact = pitch_validation_artifacts["05_test_one_wrong_note_E4_to_F4.wav"]
    summary = artifact["comparison"]["summary"]
    frames = artifact["comparison"]["frames"]
    valid = np.asarray(frames["valid"], dtype=np.bool_)
    absolute_errors = np.abs(np.asarray(frames["absolute_error_cents"])[valid])

    assert summary["global_bias_cents"] == pytest.approx(0.0, abs=5.0)
    assert summary["mean_absolute_error_cents"] == pytest.approx(25.0, abs=3.0)
    assert 100.0 * np.mean(absolute_errors > 50.0) == pytest.approx(25.0, abs=5.0)


@pytest.mark.xfail(
    reason="The 0.75-second melody notes do not yet survive stable-region qualification.",
)
@pytest.mark.parametrize(
    ("test_file", "expected_center_mae"),
    [
        ("04_test_same_melody_vibrato_pm30c_5Hz.wav", 0.0),
        ("05_test_one_wrong_note_E4_to_F4.wav", 25.0),
    ],
)
def test_short_melody_stable_note_centers(
    pitch_validation_artifacts: dict[str, dict[str, Any]],
    test_file: str,
    expected_center_mae: float,
) -> None:
    center_mae = pitch_validation_artifacts[test_file]["comparison"]["summary"][
        "stable_note_pitch_center_mae_cents"
    ]

    assert center_mae == pytest.approx(expected_center_mae, abs=5.0)

#!/usr/bin/env python3
"""Regenerate the golden analysis artifacts under tests/golden/.

The goldens pin the pipeline's full output for every checked-in audio fixture.
They exist so an alternative backend -- currently the Rust port -- can be held
to the same numbers as the Python implementation, and so an accidental change
in behaviour shows up as a diff rather than as silence.

Run this only when a change to the output is intended, and review the diff.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import tempfile
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from vocalika.models.artifact import load_artifact, normalize_artifact  # noqa: E402
from vocalika.pipeline import run_analysis  # noqa: E402

FIXTURE_DIRECTORY = REPOSITORY_ROOT / "tests" / "fixtures" / "pitch_validation_samples"
GOLDEN_DIRECTORY = REPOSITORY_ROOT / "tests" / "golden"


def cases() -> list[dict[str, str]]:
    with (FIXTURE_DIRECTORY / "README.csv").open(newline="", encoding="utf-8") as source:
        return list(csv.DictReader(source))


def generate(case: dict[str, str], working_directory: Path, cache_directory: Path) -> dict:
    name = Path(case["test_file"]).stem
    artifact_path = run_analysis(
        FIXTURE_DIRECTORY / case["reference_file"],
        FIXTURE_DIRECTORY / case["test_file"],
        working_directory / name,
        reference_is_vocal=True,
        cache_directory=cache_directory,
    )
    return normalize_artifact(load_artifact(artifact_path))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="report what would change without writing anything",
    )
    arguments = parser.parse_args()

    GOLDEN_DIRECTORY.mkdir(parents=True, exist_ok=True)
    changed: list[str] = []
    with tempfile.TemporaryDirectory(prefix="vocalika-golden-") as directory:
        working_directory = Path(directory)
        cache_directory = working_directory / "cache"
        for case in cases():
            name = Path(case["test_file"]).stem
            payload = generate(case, working_directory, cache_directory)
            destination = GOLDEN_DIRECTORY / f"{name}.json"
            serialized = json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n"
            previous = destination.read_text(encoding="utf-8") if destination.is_file() else None
            if previous != serialized:
                changed.append(name)
                if not arguments.check:
                    destination.write_text(serialized, encoding="utf-8")
            print(f"  {'changed' if previous != serialized else 'unchanged'}  {name}")

    if arguments.check and changed:
        print(f"\n{len(changed)} golden artifact(s) would change: {', '.join(changed)}")
        return 1
    print(f"\n{len(changed)} of {len(cases())} golden artifact(s) written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

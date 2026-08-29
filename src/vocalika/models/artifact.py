from __future__ import annotations

import json
import math
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "0.1.0"

# Fields that legitimately differ between two correct runs: wall-clock stamps,
# absolute paths, dependency versions, and whether a cache happened to be warm.
# They are dropped before an artifact is compared against a golden copy.
VOLATILE_KEYS = frozenset(
    {
        "created_at",
        "provenance",
        "path",
        "analysis_audio",
        "arrays",
        "vocals",
        "accompaniment",
        "cache_hit",
        "normalization_cache_hit",
        "reference_cache_hit",
        "performance_cache_hit",
        "separation_cached",
    }
)


def load_artifact(path: Path) -> dict[str, Any]:
    with path.expanduser().resolve().open(encoding="utf-8") as source:
        payload: dict[str, Any] = json.load(source)
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"Unsupported analysis schema: {payload.get('schema_version')!r}")
    return payload


def normalize_artifact(payload: Any) -> Any:
    """Strip the fields that vary between machines, runs, and cache states.

    What survives is the analytical content: configuration, content hashes,
    every derived measurement, and the per-frame arrays.
    """
    if isinstance(payload, dict):
        return {
            key: normalize_artifact(value)
            for key, value in payload.items()
            if key not in VOLATILE_KEYS
        }
    if isinstance(payload, list):
        return [normalize_artifact(item) for item in payload]
    return payload


def _close(left: float, right: float, *, relative: float, absolute: float) -> bool:
    if math.isnan(left) and math.isnan(right):
        return True
    return math.isclose(left, right, rel_tol=relative, abs_tol=absolute)


def _tolerance_for(
    path: str,
    default: float,
    overrides: Mapping[str, float] | None,
) -> float:
    """Absolute tolerance for one field, from any matching path prefix."""
    if not overrides:
        return default
    matches = [value for prefix, value in overrides.items() if path.startswith(prefix)]
    return max(matches) if matches else default


def compare_artifacts(
    expected: Any,
    actual: Any,
    *,
    relative_tolerance: float = 1e-9,
    absolute_tolerance: float = 1e-12,
    path_tolerances: Mapping[str, float] | None = None,
    path: str = "",
) -> Iterator[str]:
    """Yield one human-readable line per difference between two artifacts.

    Numbers compare within tolerance so a different summation order does not
    register; everything else must match exactly. Both sides are expected to
    have been through :func:`normalize_artifact`.

    ``path_tolerances`` maps a dotted path prefix to a looser *absolute*
    tolerance, for the few fields whose value legitimately depends on which
    resampler decoded the audio. Those fields are bounded correlation scores,
    so an absolute bound is the meaningful one -- a relative bound is
    meaningless when the value sits near zero.
    """
    if isinstance(expected, dict) and isinstance(actual, dict):
        for key in sorted(set(expected) | set(actual)):
            location = f"{path}.{key}" if path else key
            if key not in actual:
                yield f"{location}: missing from actual"
            elif key not in expected:
                yield f"{location}: unexpected in actual"
            else:
                yield from compare_artifacts(
                    expected[key],
                    actual[key],
                    relative_tolerance=relative_tolerance,
                    absolute_tolerance=absolute_tolerance,
                    path_tolerances=path_tolerances,
                    path=location,
                )
        return

    if isinstance(expected, list) and isinstance(actual, list):
        if len(expected) != len(actual):
            yield f"{path}: length {len(expected)} != {len(actual)}"
            return
        differing = 0
        for index, (left, right) in enumerate(zip(expected, actual, strict=True)):
            for difference in compare_artifacts(
                left,
                right,
                relative_tolerance=relative_tolerance,
                absolute_tolerance=absolute_tolerance,
                path_tolerances=path_tolerances,
                path=f"{path}[{index}]",
            ):
                differing += 1
                # Long arrays would otherwise bury the report in near-identical
                # lines; the count in the summary keeps the scale visible.
                if differing <= 5:
                    yield difference
        if differing > 5:
            yield f"{path}: {differing} differing elements in total"
        return

    if isinstance(expected, bool) or isinstance(actual, bool):
        if expected is not actual:
            yield f"{path}: {expected!r} != {actual!r}"
        return

    if isinstance(expected, int | float) and isinstance(actual, int | float):
        if not _close(
            float(expected),
            float(actual),
            relative=relative_tolerance,
            absolute=_tolerance_for(path, absolute_tolerance, path_tolerances),
        ):
            yield f"{path}: {expected!r} != {actual!r}"
        return

    if expected != actual:
        yield f"{path}: {expected!r} != {actual!r}"

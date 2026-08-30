from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

FloatArray = NDArray[np.float64]

NOTE_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")


def note_name(midi_value: float) -> str:
    """Nearest named note in scientific pitch notation; MIDI 60 is C4."""
    nearest = int(round(midi_value))
    return f"{NOTE_NAMES[nearest % 12]}{nearest // 12 - 1}"


@dataclass(frozen=True)
class ReferenceNote:
    """One sung note of the reference, as something a singer could practise."""

    start_seconds: float
    end_seconds: float
    midi: float
    span_cents: float

    @property
    def duration_seconds(self) -> float:
        return self.end_seconds - self.start_seconds


def segment_notes(
    times: FloatArray,
    midi: FloatArray,
    *,
    minimum_duration_seconds: float = 0.35,
    maximum_span_cents: float = 90.0,
    maximum_gap_seconds: float = 0.12,
    change_threshold_cents: float = 90.0,
) -> list[ReferenceNote]:
    """Split a reference pitch contour into discrete sung notes.

    This is not the stable-note analysis used for scoring a take, which works
    across an alignment between two performances. Here there is only the
    reference, and the goal is different: find notes a singer could be asked
    to reproduce, which means preferring whole sustained notes over the
    steadiest fragment inside them.

    A note ends when the contour moves away from the note's own centre, when
    the singer stops, or when the pitch wanders too far to be one target.
    """
    if times.size == 0:
        return []

    notes: list[ReferenceNote] = []
    start_index: int | None = None
    collected: list[float] = []
    last_index = 0

    def close(end_index: int) -> None:
        if start_index is None or not collected:
            return
        values = np.asarray(collected, dtype=np.float64)
        duration = float(times[end_index] - times[start_index])
        if duration < minimum_duration_seconds:
            return
        span = 100.0 * float(np.percentile(values, 90) - np.percentile(values, 10))
        if span > maximum_span_cents:
            return
        notes.append(
            ReferenceNote(
                start_seconds=float(times[start_index]),
                end_seconds=float(times[end_index]),
                midi=float(np.median(values)),
                span_cents=span,
            )
        )

    for index in range(times.size):
        value = midi[index]
        voiced = np.isfinite(value)

        if not voiced:
            if start_index is not None and times[index] - times[last_index] > maximum_gap_seconds:
                close(last_index)
                start_index, collected = None, []
            continue

        if start_index is None:
            start_index, collected, last_index = index, [float(value)], index
            continue

        # A gap longer than a breath ends the note even if the pitch matches.
        if times[index] - times[last_index] > maximum_gap_seconds:
            close(last_index)
            start_index, collected, last_index = index, [float(value)], index
            continue

        centre = float(np.median(collected))
        if abs(100.0 * (float(value) - centre)) > change_threshold_cents:
            close(last_index)
            start_index, collected, last_index = index, [float(value)], index
            continue

        collected.append(float(value))
        last_index = index

    close(last_index)
    return notes

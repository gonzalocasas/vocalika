from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, field
from typing import Any

from vocalika.practice.notes import ReferenceNote, note_name

INTERVAL_NAMES = (
    "unison",
    "minor 2nd",
    "major 2nd",
    "minor 3rd",
    "major 3rd",
    "perfect 4th",
    "tritone",
    "perfect 5th",
    "minor 6th",
    "major 6th",
    "minor 7th",
    "major 7th",
    "octave",
)


def interval_name(semitones: int) -> str:
    size = abs(semitones)
    if size < len(INTERVAL_NAMES):
        return INTERVAL_NAMES[size]
    return f"{size} semitones"


@dataclass(frozen=True)
class SustainedExercise:
    """Hold one note of the song steadily."""

    id: str
    midi: float
    note: str
    hold_seconds: float
    source_start: float
    source_end: float
    kind: str = "sustained"


@dataclass(frozen=True)
class IntervalExercise:
    """Leap between two notes the song actually asks you to leap between."""

    id: str
    from_midi: float
    to_midi: float
    from_note: str
    to_note: str
    semitones: int
    name: str
    direction: str
    occurrences: int
    source_start: float
    source_end: float
    kind: str = "interval"


@dataclass(frozen=True)
class WarmupExercise:
    """Walk the song's range before singing it."""

    id: str
    steps_midi: list[float] = field(default_factory=list)
    steps_note: list[str] = field(default_factory=list)
    hold_seconds: float = 2.0
    kind: str = "warmup"


def build_sustained(
    notes: list[ReferenceNote],
    *,
    limit: int = 6,
    minimum_seconds: float = 0.8,
    hold_cap_seconds: float = 4.0,
) -> list[SustainedExercise]:
    """The song's longest notes, one per pitch.

    Duplicated pitches are dropped because holding the same note twice teaches
    nothing the first attempt did not, and the point is to cover the song's
    demands rather than its repetitions.
    """
    # A practice target is a note to be sung, not a measurement of how the
    # reference singer happened to sing it, so pitches are snapped to exact
    # semitones. Without that, two exercises can display the same note names
    # while claiming different intervals.
    candidates = sorted(
        (note for note in notes if note.duration_seconds >= minimum_seconds),
        key=lambda note: note.duration_seconds,
        reverse=True,
    )
    chosen: list[SustainedExercise] = []
    seen: set[int] = set()
    for note in candidates:
        semitone = int(round(note.midi))
        if semitone in seen:
            continue
        seen.add(semitone)
        chosen.append(
            SustainedExercise(
                id=f"sustain-{semitone}",
                midi=float(semitone),
                note=note_name(semitone),
                # Long enough to expose drift, short enough to be repeatable.
                hold_seconds=round(min(hold_cap_seconds, max(1.5, note.duration_seconds)), 1),
                source_start=round(note.start_seconds, 2),
                source_end=round(note.end_seconds, 2),
            )
        )
        if len(chosen) >= limit:
            break
    return sorted(chosen, key=lambda exercise: exercise.midi)


def build_intervals(
    notes: list[ReferenceNote],
    *,
    limit: int = 6,
    minimum_semitones: int = 2,
    maximum_gap_seconds: float = 0.6,
) -> list[IntervalExercise]:
    """The leaps the song actually contains, hardest and most frequent first.

    Only consecutive notes close enough in time to belong to the same phrase
    count: two notes either side of a long rest are not a leap the singer has
    to make in one breath.
    """
    # Both endpoints snap to exact semitones, so the printed notes and the
    # named interval agree by construction.
    pairs: list[tuple[ReferenceNote, ReferenceNote, int, int]] = []
    for first, second in zip(notes, notes[1:], strict=False):
        if second.start_seconds - first.end_seconds > maximum_gap_seconds:
            continue
        low, high = int(round(first.midi)), int(round(second.midi))
        semitones = high - low
        if abs(semitones) < minimum_semitones:
            continue
        pairs.append((first, second, low, semitones))

    counts = Counter(semitones for _, _, _, semitones in pairs)
    best: dict[int, tuple[ReferenceNote, ReferenceNote, int]] = {}
    for first, second, low, semitones in pairs:
        # Keep the clearest example of each leap: the one whose notes are held
        # longest, so the target pitches are unambiguous.
        current = best.get(semitones)
        if current is None or (
            first.duration_seconds + second.duration_seconds
            > current[0].duration_seconds + current[1].duration_seconds
        ):
            best[semitones] = (first, second, low)

    # Wide leaps are the ones that go wrong, so size outranks frequency, with
    # frequency breaking ties toward what the song asks for most.
    ordered = sorted(best, key=lambda s: (abs(s), counts[s]), reverse=True)
    exercises: list[IntervalExercise] = []
    for semitones in ordered[:limit]:
        first, second, low = best[semitones]
        exercises.append(
            IntervalExercise(
                id=f"interval-{semitones:+d}",
                from_midi=float(low),
                to_midi=float(low + semitones),
                from_note=note_name(low),
                to_note=note_name(low + semitones),
                semitones=semitones,
                name=interval_name(semitones),
                direction="up" if semitones > 0 else "down",
                occurrences=counts[semitones],
                source_start=round(first.start_seconds, 2),
                source_end=round(second.end_seconds, 2),
            )
        )
    return exercises


def build_warmup(
    low_midi: float,
    high_midi: float,
    median_midi: float,
    *,
    maximum_steps: int = 9,
    step_semitones: int = 2,
) -> WarmupExercise | None:
    """A ladder across the song's range, to be walked before singing it.

    Built outward from the comfortable middle rather than upward from the
    bottom, so the voice is warm by the time it reaches the extremes -- which
    is where accuracy falls away.
    """
    low, high = int(round(low_midi)), int(round(high_midi))
    if high - low < step_semitones:
        return None
    centre = int(round(median_midi))
    centre = min(max(centre, low), high)

    steps = [centre]
    offset = step_semitones
    while len(steps) < maximum_steps:
        added = False
        for candidate in (centre - offset, centre + offset):
            if low <= candidate <= high and candidate not in steps:
                steps.append(candidate)
                added = True
                if len(steps) >= maximum_steps:
                    break
        if not added and offset > (high - low):
            break
        offset += step_semitones

    for edge in (low, high):
        if edge not in steps:
            steps.append(edge)

    ordered = sorted(steps)
    return WarmupExercise(
        id="warmup",
        steps_midi=[float(value) for value in ordered],
        steps_note=[note_name(value) for value in ordered],
    )


def build_exercises(
    notes: list[ReferenceNote],
    vocal_range: dict[str, Any] | None,
) -> dict[str, Any]:
    warmup = None
    if vocal_range:
        warmup = build_warmup(
            vocal_range["low_midi"], vocal_range["high_midi"], vocal_range["median_midi"]
        )
    return {
        "sustained": [asdict(exercise) for exercise in build_sustained(notes)],
        "intervals": [asdict(exercise) for exercise in build_intervals(notes)],
        "warmup": asdict(warmup) if warmup else None,
        "note_count": len(notes),
    }

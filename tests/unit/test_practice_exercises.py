from __future__ import annotations

import numpy as np

from vocalika.practice.exercises import (
    build_intervals,
    build_sustained,
    build_warmup,
    interval_name,
)
from vocalika.practice.notes import ReferenceNote, note_name, segment_notes


def contour(segments: list[tuple[float, float | None]], step: float = 0.05):
    """Build a contour from (seconds, midi) segments; midi None is a rest."""
    times: list[float] = []
    midi: list[float] = []
    time = 0.0
    for seconds, value in segments:
        for _ in range(round(seconds / step)):
            times.append(time)
            midi.append(np.nan if value is None else value)
            time += step
    return np.asarray(times), np.asarray(midi)


def note(midi: float, start: float, end: float) -> ReferenceNote:
    return ReferenceNote(start_seconds=start, end_seconds=end, midi=midi, span_cents=10.0)


def test_segments_a_contour_into_notes_at_pitch_changes_and_rests() -> None:
    times, midi = contour([(1.0, 60.0), (0.4, None), (1.0, 64.0), (1.0, 67.0)])
    notes = segment_notes(times, midi)
    assert [round(n.midi) for n in notes] == [60, 64, 67]
    assert notes[0].duration_seconds > 0.9


def test_a_note_survives_a_breath_shorter_than_the_gap_threshold() -> None:
    # A momentary dropout inside a held note is not a new note.
    times, midi = contour([(0.8, 62.0), (0.05, None), (0.8, 62.0)])
    assert len(segment_notes(times, midi)) == 1


def test_notes_shorter_than_the_minimum_are_discarded() -> None:
    times, midi = contour([(0.15, 60.0), (0.3, None), (1.0, 64.0)])
    assert [round(n.midi) for n in segment_notes(times, midi)] == [64]


def test_a_slow_slide_is_not_reported_as_one_note() -> None:
    times = np.arange(0, 2.0, 0.05)
    midi = 60.0 + np.linspace(0, 6, times.size)
    notes = segment_notes(times, midi)
    assert all(n.span_cents <= 90.0 for n in notes)


def test_sustained_exercises_take_the_longest_note_per_pitch() -> None:
    notes = [
        note(60.0, 0.0, 1.0),
        note(60.2, 5.0, 3.5 + 5.0),  # same pitch, longer: should win
        note(67.0, 20.0, 21.2),
    ]
    exercises = build_sustained(notes)
    assert [e.note for e in exercises] == ["C4", "G4"]
    assert exercises[0].hold_seconds > 3.0
    # Targets are exact semitones, never the reference singer's median.
    assert all(float(e.midi).is_integer() for e in exercises)


def test_sustained_skips_notes_too_short_to_hold() -> None:
    assert build_sustained([note(60.0, 0.0, 0.4)]) == []


def test_intervals_come_from_consecutive_notes_in_the_same_phrase() -> None:
    notes = [
        note(55.0, 0.0, 1.0),
        note(62.0, 1.1, 2.1),  # +7 within a phrase
        note(48.0, 9.0, 10.0),  # after a long rest: not a leap to practise
    ]
    exercises = build_intervals(notes)
    assert [e.semitones for e in exercises] == [7]
    assert exercises[0].name == "perfect 5th"
    assert exercises[0].direction == "up"
    assert (exercises[0].from_note, exercises[0].to_note) == ("G3", "D4")


def test_interval_endpoints_always_agree_with_the_named_interval() -> None:
    # Endpoints snap to semitones, so two exercises can never show the same
    # note pair while claiming different intervals.
    notes = [
        note(61.4, 0.0, 1.0),
        note(58.6, 1.05, 2.0),
        note(61.0, 2.05, 3.0),
        note(59.4, 3.05, 4.0),
    ]
    for exercise in build_intervals(notes):
        assert exercise.to_midi - exercise.from_midi == exercise.semitones
        assert exercise.from_note == note_name(exercise.from_midi)
        assert exercise.to_note == note_name(exercise.to_midi)


def test_steps_smaller_than_the_minimum_are_not_leaps() -> None:
    notes = [note(60.0, 0.0, 1.0), note(61.0, 1.05, 2.0)]
    assert build_intervals(notes) == []


def test_wider_leaps_are_offered_before_narrower_ones() -> None:
    notes = [
        note(60.0, 0.0, 1.0),
        note(62.0, 1.05, 2.0),
        note(60.0, 2.05, 3.0),
        note(62.0, 3.05, 4.0),  # a common but easy major 2nd
        note(72.0, 4.05, 5.0),  # a rare but hard octave
    ]
    exercises = build_intervals(notes)
    assert abs(exercises[0].semitones) > abs(exercises[-1].semitones)


def test_warmup_spans_the_range_and_includes_both_extremes() -> None:
    warmup = build_warmup(54.0, 62.0, 55.0)
    assert warmup is not None
    assert warmup.steps_midi[0] == 54.0
    assert warmup.steps_midi[-1] == 62.0
    assert warmup.steps_midi == sorted(warmup.steps_midi)
    assert len(set(warmup.steps_midi)) == len(warmup.steps_midi), "no repeated steps"
    assert warmup.steps_note[0] == "F#3"


def test_warmup_is_capped_and_declines_a_degenerate_range() -> None:
    wide = build_warmup(40.0, 80.0, 60.0)
    assert wide is not None
    assert len(wide.steps_midi) <= 11
    assert build_warmup(60.0, 60.0, 60.0) is None


def test_interval_names_cover_the_octave_and_beyond() -> None:
    assert interval_name(7) == "perfect 5th"
    assert interval_name(-7) == "perfect 5th"
    assert interval_name(12) == "octave"
    assert interval_name(14) == "14 semitones"


def test_note_naming_matches_scientific_pitch_notation() -> None:
    assert note_name(60) == "C4"
    assert note_name(69) == "A4"
    assert note_name(54) == "F#3"

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

from vocalika.analysis.cleaning import clean_pitch_track
from vocalika.analysis.pitch import PyinPitchExtractor
from vocalika.config import AnalysisConfig
from vocalika.practice.notes import note_name

FloatArray = NDArray[np.float64]


@dataclass(frozen=True)
class HeldNoteScore:
    """How one attempt at holding a single pitch went."""

    target_midi: float
    target_note: str
    sung_note: str | None
    #: Signed cents from the target: negative is flat.
    centre_cents: float | None
    #: Mean deviation about the singer's own centre: drift, wobble, wandering.
    steadiness_cents: float | None
    #: Cents from the *nearest* semitone, which is where an octave error hides.
    held_seconds: float
    #: Fraction of the attempt that produced a usable pitch at all.
    coverage: float
    verdict: str


def _config_extractor(config: AnalysisConfig) -> PyinPitchExtractor:
    return PyinPitchExtractor(
        hop_length=config.pitch_hop_length,
        frame_length=config.pitch_frame_length,
        fmin_midi=config.pitch_min_midi,
        fmax_midi=config.pitch_max_midi,
        concert_pitch_hz=config.concert_pitch_hz,
        harmonic_margin=config.pitch_harmonic_margin,
    )


#: Mean deviation from the singer's own centre, above which a note counts as
#: unsteady rather than merely vibrato-ed. Calibrated against pyin's actual
#: output: a healthy +-40 cent vibrato measures about 12 here and +-60 about
#: 18, while a full semitone of wobble measures about 31. Frame-based tracking
#: smooths the modulation, so this number is well below the true excursion.
STEADINESS_LIMIT_CENTS = 30.0


def verdict_for(centre_cents: float | None, steadiness: float | None) -> str:
    if centre_cents is None:
        return "not-heard"
    magnitude = abs(centre_cents)
    if magnitude > 150:
        return "wrong-note"
    if magnitude > 50:
        return "off"
    if steadiness is not None and steadiness > STEADINESS_LIMIT_CENTS:
        # Landing on the note but not staying there is a different fault from
        # landing beside it, and needs different practice.
        return "unsteady"
    if magnitude > 25:
        return "close"
    return "on-pitch"


def score_held_note(
    audio_path: Path,
    target_midi: float,
    *,
    config: AnalysisConfig | None = None,
    trim_fraction: float = 0.15,
) -> HeldNoteScore:
    """Score one recorded attempt at holding a pitch.

    This runs the same extractor the analysis pipeline uses rather than the
    browser's live estimator. The live display exists to guide a singer while
    they sing and is allowed to be approximate; a score they will act on is
    not, so the attempt is measured properly even though that costs a round
    trip.

    The onset and release are trimmed away before measuring. Nobody arrives on
    a note instantly, and scoring the scoop into it would report a fault the
    singer did not commit.
    """
    config = config or AnalysisConfig()
    track = clean_pitch_track(
        _config_extractor(config).extract(audio_path),
        confidence_threshold=config.pitch_confidence_threshold,
        octave_window=config.octave_window_frames,
        max_gap_seconds=config.max_pitch_gap_seconds,
        sustain_confidence_threshold=config.pitch_sustain_confidence_threshold,
    )

    midi = np.asarray(track.midi, dtype=np.float64)
    total = midi.size
    if total == 0:
        return HeldNoteScore(
            target_midi=target_midi,
            target_note=note_name(target_midi),
            sung_note=None,
            centre_cents=None,
            steadiness_cents=None,
            held_seconds=0.0,
            coverage=0.0,
            verdict="not-heard",
        )

    margin = int(total * trim_fraction)
    core = midi[margin : total - margin] if total - 2 * margin > 4 else midi
    voiced = core[np.isfinite(core)]
    frame_seconds = track.hop_length / track.sample_rate
    coverage = float(voiced.size / core.size) if core.size else 0.0

    if voiced.size < 3:
        return HeldNoteScore(
            target_midi=target_midi,
            target_note=note_name(target_midi),
            sung_note=None,
            centre_cents=None,
            steadiness_cents=None,
            held_seconds=round(voiced.size * frame_seconds, 2),
            coverage=round(coverage, 3),
            verdict="not-heard",
        )

    # The median resists the scoop and the release far better than the mean.
    centre = float(np.median(voiced))
    centre_cents = 100.0 * (centre - target_midi)
    steadiness = 100.0 * float(np.mean(np.abs(voiced - centre)))

    return HeldNoteScore(
        target_midi=target_midi,
        target_note=note_name(target_midi),
        sung_note=note_name(centre),
        centre_cents=round(centre_cents, 1),
        steadiness_cents=round(steadiness, 1),
        held_seconds=round(voiced.size * frame_seconds, 2),
        coverage=round(coverage, 3),
        verdict=verdict_for(centre_cents, steadiness),
    )


def score_interval(
    audio_path: Path,
    from_midi: float,
    to_midi: float,
    *,
    config: AnalysisConfig | None = None,
) -> dict[str, Any]:
    """Score a leap: both endpoints, and the size of the leap itself.

    The interval is judged separately from the pitches, because a singer can
    place a leap perfectly while sitting a semitone low throughout -- that is
    good relative pitch and poor tuning, and the two need different work.
    """
    config = config or AnalysisConfig()
    track = clean_pitch_track(
        _config_extractor(config).extract(audio_path),
        confidence_threshold=config.pitch_confidence_threshold,
        octave_window=config.octave_window_frames,
        max_gap_seconds=config.max_pitch_gap_seconds,
        sustain_confidence_threshold=config.pitch_sustain_confidence_threshold,
    )
    midi = np.asarray(track.midi, dtype=np.float64)
    voiced_index = np.flatnonzero(np.isfinite(midi))
    if voiced_index.size < 8:
        return {
            "first": None,
            "second": None,
            "sung_semitones": None,
            "target_semitones": round(to_midi - from_midi, 2),
            "interval_error_cents": None,
            "verdict": "not-heard",
        }

    # Split at the largest pitch move rather than at the midpoint in time: the
    # singer decides when to leap, not the exercise.
    start, end = int(voiced_index[0]), int(voiced_index[-1])
    span = midi[start : end + 1]
    filled = np.where(np.isfinite(span), span, np.nan)
    guard = max(2, span.size // 8)
    if span.size < 2 * guard + 2:
        split = span.size // 2
    else:
        steps = np.abs(np.diff(filled))
        steps[: guard - 1] = np.nan
        steps[-(guard - 1) :] = np.nan
        split = int(np.nanargmax(steps)) + 1 if np.any(np.isfinite(steps)) else span.size // 2

    first = span[:split][np.isfinite(span[:split])]
    second = span[split:][np.isfinite(span[split:])]
    if first.size < 3 or second.size < 3:
        return {
            "first": None,
            "second": None,
            "sung_semitones": None,
            "target_semitones": round(to_midi - from_midi, 2),
            "interval_error_cents": None,
            "verdict": "not-heard",
        }

    first_centre = float(np.median(first))
    second_centre = float(np.median(second))
    sung = second_centre - first_centre
    target = to_midi - from_midi
    error = 100.0 * (sung - target)

    return {
        "first": asdict(_centre_score(first_centre, from_midi, first, track)),
        "second": asdict(_centre_score(second_centre, to_midi, second, track)),
        "sung_semitones": round(sung, 2),
        "target_semitones": round(target, 2),
        "interval_error_cents": round(error, 1),
        "verdict": (
            "on-pitch" if abs(error) <= 30 else "close" if abs(error) <= 60 else "off"
        ),
    }


def _centre_score(
    centre: float,
    target: float,
    values: FloatArray,
    track: Any,
) -> HeldNoteScore:
    centre_cents = 100.0 * (centre - target)
    steadiness = 100.0 * float(np.mean(np.abs(values - centre)))
    frame_seconds = track.hop_length / track.sample_rate
    return HeldNoteScore(
        target_midi=target,
        target_note=note_name(target),
        sung_note=note_name(centre),
        centre_cents=round(centre_cents, 1),
        steadiness_cents=round(steadiness, 1),
        held_seconds=round(values.size * frame_seconds, 2),
        coverage=1.0,
        verdict=verdict_for(centre_cents, steadiness),
    )

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import numpy as np

from vocalika.api.reference_pitch import build_reference_pitch
from vocalika.audio.decode import decode_for_analysis
from vocalika.cache.manager import CacheManager
from vocalika.practice.exercises import build_exercises
from vocalika.practice.notes import segment_notes
from vocalika.practice.scoring import score_held_note, score_interval
from vocalika.projects.models import Project
from vocalika.projects.reference_audio import ReferenceAudioService


def build_practice_plan(
    project: Project,
    reference_audio: ReferenceAudioService,
    cache: CacheManager,
    transpose_semitones: int,
) -> dict[str, Any]:
    """Derive practice material from the song the singer is preparing.

    Exercises come from the reference itself rather than from a generic set of
    scales, so the notes drilled are the notes the song will actually demand.
    """
    contour = build_reference_pitch(project, reference_audio, cache, transpose_semitones)
    times = np.asarray(contour["times"], dtype=np.float64)
    midi = np.asarray(
        [np.nan if value is None else value for value in contour["midi"]], dtype=np.float64
    )
    notes = segment_notes(times, midi)
    plan = build_exercises(notes, contour.get("range"))
    plan["range"] = contour.get("range")
    plan["transpose_semitones"] = transpose_semitones
    return plan


def score_attempt(
    audio_path: Path,
    kind: str,
    target_midi: float,
    to_midi: float | None,
) -> dict[str, Any]:
    """Score one recorded exercise attempt.

    Browser recordings arrive as WebM/Opus, which the analysis path cannot read
    directly, so the attempt is decoded to the analysis format first -- the
    same step a take goes through before it is analysed.
    """
    with TemporaryDirectory(prefix="vocalika-attempt-") as raw:
        decoded = decode_for_analysis(audio_path, Path(raw) / "attempt.wav")
        if kind == "interval":
            if to_midi is None:
                raise ValueError("An interval attempt needs both a starting and a target note.")
            return score_interval(decoded, target_midi, to_midi)
        return asdict(score_held_note(decoded, target_midi))

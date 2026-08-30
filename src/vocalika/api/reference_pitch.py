from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

from vocalika import __version__
from vocalika.analysis.pitch import PyinPitchExtractor
from vocalika.analysis.pitch_cache import extract_clean_pitch
from vocalika.audio.decode import hash_file
from vocalika.cache.manager import CacheManager
from vocalika.config import AnalysisConfig
from vocalika.projects.models import Project
from vocalika.projects.reference_audio import ReferenceAudioService


def build_reference_pitch(
    project: Project,
    reference_audio: ReferenceAudioService,
    cache: CacheManager,
    transpose_semitones: int,
    *,
    config: AnalysisConfig | None = None,
) -> dict[str, Any]:
    """Return the reference vocal's pitch contour for live comparison.

    The recording screen needs this before any take exists, so it cannot be
    read out of an analysis artifact. It goes through the same cached
    extractor the pipeline uses, so the first call pays for pyin and every
    later one -- including the pipeline's own, when a take is finally
    analysed -- is a cache read.

    Unvoiced frames are returned as null rather than dropped, so the client
    breaks the line at a rest instead of interpolating across it.
    """
    config = config or AnalysisConfig()
    vocal_path = Path(reference_audio.resolve(project, "vocal", transpose_semitones))
    extractor = PyinPitchExtractor(
        hop_length=config.pitch_hop_length,
        frame_length=config.pitch_frame_length,
        fmin_midi=config.pitch_min_midi,
        fmax_midi=config.pitch_max_midi,
        concert_pitch_hz=config.concert_pitch_hz,
        harmonic_margin=config.pitch_harmonic_margin,
    )
    cached = extract_clean_pitch(
        audio_path=vocal_path,
        content_hash=hash_file(vocal_path),
        cache=cache,
        extractor=extractor,
        cleaning_parameters={
            "confidence_threshold": config.pitch_confidence_threshold,
            "octave_window": config.octave_window_frames,
            "max_gap_seconds": config.max_pitch_gap_seconds,
            "sustain_confidence_threshold": config.pitch_sustain_confidence_threshold,
        },
        pipeline_version=__version__,
    )
    track = cached.track
    midi = np.asarray(track.midi, dtype=np.float64)
    return {
        "times": [round(float(value), 4) for value in track.times],
        "midi": [None if not np.isfinite(value) else round(float(value), 3) for value in midi],
        "range": vocal_range(midi),
    }


NOTE_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")


def note_name(midi_value: float) -> str:
    """Nearest named note, in scientific pitch notation (MIDI 60 is C4)."""
    nearest = int(round(midi_value))
    return f"{NOTE_NAMES[nearest % 12]}{nearest // 12 - 1}"


def vocal_range(midi: NDArray[np.float64]) -> dict[str, Any] | None:
    """The reference vocal's working range, for judging whether it is singable.

    Reported as the 5th to 95th percentile rather than the outright extremes.
    pyin drops or doubles an octave on a small number of frames, and a single
    such frame would otherwise widen the range by an octave and misrepresent
    what the song actually asks for.
    """
    voiced = midi[np.isfinite(midi)]
    if voiced.size < 20:
        return None
    low, high = (float(value) for value in np.percentile(voiced, [5, 95]))
    median = float(np.median(voiced))
    return {
        "low_midi": round(low, 2),
        "high_midi": round(high, 2),
        "median_midi": round(median, 2),
        "low_note": note_name(low),
        "high_note": note_name(high),
        "median_note": note_name(median),
        "semitones": round(high - low, 1),
    }

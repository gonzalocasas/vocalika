from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from vocalika.analysis.pitch import PitchTrack

BoolArray = NDArray[np.bool_]
FloatArray = NDArray[np.float64]


def _sustained(
    voiced: BoolArray,
    confidence: FloatArray,
    onset_threshold: float,
    sustain_threshold: float,
) -> BoolArray:
    """Keep a run of frames once any frame in it clears the onset threshold.

    A singer does not restart phonation frame to frame, so the evidence needed
    to stay inside a note is lower than the evidence needed to declare one.
    Judging every frame independently against a single threshold perforates
    sustained notes wherever confidence dips -- on separated stems, where
    residual accompaniment depresses pyin's confidence throughout, it discards
    the majority of what the singer audibly sang.
    """
    candidate = voiced & (confidence >= sustain_threshold)
    onset = candidate & (confidence >= onset_threshold)
    edges = np.flatnonzero(np.diff(np.concatenate(([0], candidate.astype(np.int8), [0]))))
    kept = np.zeros(candidate.size, dtype=bool)
    for start, end in zip(edges[::2], edges[1::2], strict=True):
        if onset[start:end].any():
            kept[start:end] = True
    return kept


def clean_pitch_track(
    track: PitchTrack,
    confidence_threshold: float = 0.55,
    octave_window: int = 9,
    max_gap_seconds: float = 0.08,
    sustain_confidence_threshold: float = 0.20,
) -> PitchTrack:
    """Filter uncertain frames, repair obvious octave jumps, and fill tiny gaps."""
    midi = track.raw_midi.copy()
    reliable = np.isfinite(midi) & _sustained(
        track.voiced,
        track.confidence,
        confidence_threshold,
        min(sustain_confidence_threshold, confidence_threshold),
    )
    midi[~reliable] = np.nan

    half_window = octave_window // 2
    for raw_index in np.flatnonzero(np.isfinite(midi)):
        index = int(raw_index)
        start = max(0, index - half_window)
        end = min(midi.size, index + half_window + 1)
        neighborhood = midi[start:end]
        local_center = np.nanmedian(neighborhood)
        if not np.isfinite(local_center):
            continue
        difference = midi[index] - local_center
        if abs(difference) >= 9.0:
            corrected = midi[index] - 12.0 * round(difference / 12.0)
            if abs(corrected - local_center) <= 3.0:
                midi[index] = corrected

    frame_seconds = track.hop_length / track.sample_rate
    max_gap = max(1, round(max_gap_seconds / frame_seconds))
    valid_indices = np.flatnonzero(np.isfinite(midi))
    for left, right in zip(valid_indices[:-1], valid_indices[1:], strict=False):
        gap = right - left - 1
        if 0 < gap <= max_gap:
            midi[left : right + 1] = np.linspace(midi[left], midi[right], right - left + 1)

    cleaned_voiced = np.isfinite(midi)
    return PitchTrack(
        times=track.times,
        raw_frequency_hz=track.raw_frequency_hz,
        raw_midi=track.raw_midi,
        midi=midi,
        confidence=track.confidence,
        voiced=cleaned_voiced,
        extractor=track.extractor,
        sample_rate=track.sample_rate,
        hop_length=track.hop_length,
    )

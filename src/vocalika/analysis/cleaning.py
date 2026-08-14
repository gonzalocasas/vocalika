from __future__ import annotations

import numpy as np

from vocalika.analysis.pitch import PitchTrack


def clean_pitch_track(
    track: PitchTrack,
    confidence_threshold: float = 0.55,
    octave_window: int = 9,
    max_gap_seconds: float = 0.08,
) -> PitchTrack:
    """Filter uncertain frames, repair obvious octave jumps, and fill tiny gaps."""
    midi = track.raw_midi.copy()
    reliable = np.isfinite(midi) & track.voiced & (track.confidence >= confidence_threshold)
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

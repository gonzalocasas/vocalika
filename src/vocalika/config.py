from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class AnalysisConfig:
    analysis_sample_rate: int = 16_000
    pitch_hop_length: int = 256
    pitch_frame_length: int = 2048
    pitch_min_midi: float = 36.0
    pitch_max_midi: float = 84.0
    pitch_confidence_threshold: float = 0.55
    octave_window_frames: int = 9
    max_pitch_gap_seconds: float = 0.08
    alignment_frames_per_second: float = 10.0
    alignment_band_radius: float = 0.2
    excellent_tolerance_cents: float = 15.0
    good_tolerance_cents: float = 25.0
    noticeable_tolerance_cents: float = 50.0
    minimum_matched_seconds: float = 10.0
    minimum_valid_fraction: float = 0.05
    concert_pitch_hz: float = 440.0
    stable_note_window_seconds: float = 0.7
    stable_note_max_span_cents: float = 120.0
    stable_note_max_slope_cents_per_second: float = 60.0
    stable_note_minimum_duration_seconds: float = 0.5
    stable_note_minimum_voiced_window_fraction: float = 0.7
    stable_note_minimum_matched_region_fraction: float = 0.4
    stable_note_minimum_alignment_duration_ratio: float = 0.35
    stable_note_maximum_alignment_duration_ratio: float = 2.5

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from vocalika.analysis.pitch import PitchVoice, RmvpePitchExtractor


@dataclass(frozen=True)
class AnalysisConfig:
    analysis_sample_rate: int = 16_000
    pitch_min_midi: float = 36.0
    pitch_max_midi: float = 84.0
    pitch_confidence_threshold: float = 0.55
    # Frames continue an already-established note down to this confidence.
    # See _sustained in analysis/cleaning.py.
    pitch_sustain_confidence_threshold: float = 0.20
    # RMVPE's peak salience below which a frame is unvoiced (its authors' value).
    pitch_voicing_threshold: float = 0.03
    # Which voice of the reference is the melody where two people sing: the
    # louder one, or the upper or lower one. See analysis/voices.py.
    reference_voice: Literal["louder", "upper", "lower"] = "louder"
    # Frames this far below the track's singing level are not voice, whatever
    # the tracker says. See _loud_enough in analysis/cleaning.py.
    pitch_level_floor_db: float = 40.0
    octave_window_frames: int = 9
    max_pitch_gap_seconds: float = 0.08
    # Fine enough that alignment lands within ~7 ms: RMVPE reports vibrato and
    # note transitions faithfully, and at 10 fps the ~30 ms alignment error
    # alone put tens of cents of false error on them.
    alignment_frames_per_second: float = 50.0
    alignment_band_radius: float = 0.2
    alignment_temporal_consistency_weight: float = 0.1
    # Cost of a non-diagonal DTW step. At 50 fps an unpenalised path chases
    # vibrato and biased a +-30 cent vibrato by 6 cents; any value from 0.1 to
    # 0.8 removes that with no loss on tempo changes or delays (bench sweep).
    alignment_step_penalty: float = 0.2
    alignment_maximum_offset_seconds: float = 5.0
    alignment_offset_minimum_confidence: float = 0.9
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

    def cleaning_parameters(self) -> dict[str, Any]:
        """The cleaning settings, as the pitch cache keys them.

        Kept in one place because it is a cache key: any caller that builds
        this dict by hand and forgets a field silently reads back a track
        cleaned with different settings, reports a cache hit, and looks fine.
        """
        return {
            "confidence_threshold": self.pitch_confidence_threshold,
            "octave_window": self.octave_window_frames,
            "max_gap_seconds": self.max_pitch_gap_seconds,
            "sustain_confidence_threshold": self.pitch_sustain_confidence_threshold,
            "level_floor_db": self.pitch_level_floor_db,
        }

    def pitch_extractor(self, voice: PitchVoice = "single") -> RmvpePitchExtractor:
        """The extractor for a recording: ``single`` for a take, the reference voice otherwise."""
        from vocalika.analysis.pitch import RmvpePitchExtractor

        return RmvpePitchExtractor(
            voice=voice,
            fmin_midi=self.pitch_min_midi,
            fmax_midi=self.pitch_max_midi,
            concert_pitch_hz=self.concert_pitch_hz,
            voicing_threshold=self.pitch_voicing_threshold,
        )

    def reference_extractor(self) -> RmvpePitchExtractor:
        from vocalika.analysis.voices import REFERENCE_VOICES

        if self.reference_voice not in REFERENCE_VOICES:
            raise ValueError(f"Unknown reference voice: {self.reference_voice!r}")
        return self.pitch_extractor(self.reference_voice)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

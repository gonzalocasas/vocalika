from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any

import numpy as np

from vocalika import __version__
from vocalika.analysis.alignment import align_pitch_tracks
from vocalika.analysis.cleaning import clean_pitch_track
from vocalika.analysis.comparison import compare_alignment
from vocalika.analysis.pitch import PitchTrack, PyinPitchExtractor
from vocalika.audio.decode import decode_for_analysis, probe_audio
from vocalika.config import AnalysisConfig

ProgressCallback = Callable[[str], None]


def _quiet(_: str) -> None:
    pass


def _resolve_output_paths(output: Path) -> tuple[Path, Path]:
    resolved_output = output.expanduser().resolve()
    if resolved_output.suffix.lower() == ".json":
        return resolved_output.parent, resolved_output
    return resolved_output, resolved_output / "analysis.json"


def _save_tracks(path: Path, reference: PitchTrack, performance: PitchTrack) -> None:
    np.savez_compressed(
        path,
        reference_times=reference.times,
        reference_raw_frequency_hz=reference.raw_frequency_hz,
        reference_raw_midi=reference.raw_midi,
        reference_midi=reference.midi,
        reference_confidence=reference.confidence,
        reference_voiced=reference.voiced,
        performance_times=performance.times,
        performance_raw_frequency_hz=performance.raw_frequency_hz,
        performance_raw_midi=performance.raw_midi,
        performance_midi=performance.midi,
        performance_confidence=performance.confidence,
        performance_voiced=performance.voiced,
    )


def run_analysis(
    reference_path: Path,
    performance_path: Path,
    output: Path,
    *,
    reference_is_vocal: bool = False,
    reference_mix_path: Path | None = None,
    config: AnalysisConfig | None = None,
    progress: ProgressCallback = _quiet,
) -> Path:
    config = config or AnalysisConfig()
    output_directory, artifact_path = _resolve_output_paths(output)
    explicit_name = artifact_path.name != "analysis.json"
    asset_prefix = f"{artifact_path.stem}." if explicit_name else ""
    work_directory = output_directory / (
        f"{artifact_path.stem}.working-audio" if explicit_name else "working-audio"
    )
    output_directory.mkdir(parents=True, exist_ok=True)

    progress("Inspecting input audio")
    reference_info = probe_audio(reference_path)
    performance_info = probe_audio(performance_path)
    reference_mix_info = probe_audio(reference_mix_path) if reference_mix_path else None

    progress("Decoding reference to analysis audio")
    reference_wav = decode_for_analysis(
        reference_path,
        work_directory / "reference.wav",
        sample_rate=config.analysis_sample_rate,
    )
    progress("Decoding performance to analysis audio")
    performance_wav = decode_for_analysis(
        performance_path,
        work_directory / "performance.wav",
        sample_rate=config.analysis_sample_rate,
    )

    extractor = PyinPitchExtractor(
        hop_length=config.pitch_hop_length,
        frame_length=config.pitch_frame_length,
        fmin_midi=config.pitch_min_midi,
        fmax_midi=config.pitch_max_midi,
        concert_pitch_hz=config.concert_pitch_hz,
    )
    progress("Extracting reference pitch")
    reference_pitch = clean_pitch_track(
        extractor.extract(reference_wav),
        confidence_threshold=config.pitch_confidence_threshold,
        octave_window=config.octave_window_frames,
        max_gap_seconds=config.max_pitch_gap_seconds,
    )
    progress("Extracting performance pitch")
    performance_pitch = clean_pitch_track(
        extractor.extract(performance_wav),
        confidence_threshold=config.pitch_confidence_threshold,
        octave_window=config.octave_window_frames,
        max_gap_seconds=config.max_pitch_gap_seconds,
    )

    progress("Aligning pitch tracks")
    alignment = align_pitch_tracks(
        reference_pitch,
        performance_pitch,
        frames_per_second=config.alignment_frames_per_second,
        band_radius=config.alignment_band_radius,
    )
    progress("Calculating pitch differences")
    comparison = compare_alignment(
        alignment,
        confidence_threshold=config.pitch_confidence_threshold,
        excellent_tolerance_cents=config.excellent_tolerance_cents,
        good_tolerance_cents=config.good_tolerance_cents,
        noticeable_tolerance_cents=config.noticeable_tolerance_cents,
    )

    arrays_path = output_directory / f"{asset_prefix}pitch-tracks.npz"
    _save_tracks(arrays_path, reference_pitch, performance_pitch)

    frames: dict[str, Any] = {
        "reference_time": comparison.reference_times.tolist(),
        "performance_time": comparison.performance_times.tolist(),
        "reference_midi": comparison.reference_midi.tolist(),
        "performance_midi": comparison.performance_midi.tolist(),
        "confidence": comparison.confidence.tolist(),
        "valid": comparison.valid.tolist(),
        "absolute_error_cents": comparison.absolute_error_cents.tolist(),
        "relative_error_cents": comparison.relative_error_cents.tolist(),
    }
    warnings: list[str] = []
    if not reference_is_vocal:
        warnings.append(
            "Milestone 1 does not isolate vocals. Pitch extracted from a full mix may follow "
            "instruments or backing vocals."
        )
    if comparison.matched_seconds < config.minimum_matched_seconds:
        warnings.append(
            f"Only {comparison.matched_seconds:.1f} seconds of confident corresponding vocal "
            "audio were found; summary metrics may be unreliable."
        )
    if comparison.valid_fraction < config.minimum_valid_fraction:
        warnings.append(
            f"Only {comparison.valid_fraction:.1%} of alignment points were sufficiently "
            "confident and voiced; inspect the contours before trusting summary metrics."
        )

    artifact: dict[str, Any] = {
        "schema_version": "0.1.0",
        "created_at": datetime.now(UTC).isoformat(),
        "pipeline_version": __version__,
        "configuration": config.to_dict(),
        "provenance": {
            "vocalika_version": __version__,
            "librosa_version": version("librosa"),
            "numpy_version": version("numpy"),
            "scipy_version": version("scipy"),
        },
        "reference": {
            "source": reference_info.to_dict(),
            "analysis_audio": str(reference_wav),
            "conversion": {
                "input_sample_rate": reference_info.sample_rate,
                "analysis_sample_rate": config.analysis_sample_rate,
                "channels": 1,
                "sample_format": "float32_pcm",
            },
            "is_isolated_vocal": reference_is_vocal,
            "original_mix": reference_mix_info.to_dict() if reference_mix_info else None,
        },
        "performance": {
            "source": performance_info.to_dict(),
            "analysis_audio": str(performance_wav),
            "conversion": {
                "input_sample_rate": performance_info.sample_rate,
                "analysis_sample_rate": config.analysis_sample_rate,
                "channels": 1,
                "sample_format": "float32_pcm",
            },
            "is_isolated_vocal": True,
        },
        "pitch": {
            "extractor": reference_pitch.extractor,
            "sample_rate": reference_pitch.sample_rate,
            "hop_length": reference_pitch.hop_length,
            "fmin_midi": extractor.fmin_midi,
            "fmax_midi": extractor.fmax_midi,
            "concert_pitch_hz": extractor.concert_pitch_hz,
            "arrays": arrays_path.name,
        },
        "alignment": {
            "method": "pitch-dtw",
            "frames_per_second": alignment.frames_per_second,
            "point_count": int(comparison.reference_times.size),
        },
        "comparison": {
            "summary": {
                "global_bias_cents": comparison.global_bias_cents,
                "mean_absolute_error_cents": comparison.mean_absolute_error_cents,
                "relative_mean_absolute_error_cents": (
                    comparison.relative_mean_absolute_error_cents
                ),
                "within_15_percent": comparison.within_15_percent,
                "within_25_percent": comparison.within_25_percent,
                "within_50_percent": comparison.within_50_percent,
                "relative_within_15_percent": comparison.relative_within_15_percent,
                "relative_within_25_percent": comparison.relative_within_25_percent,
                "relative_within_50_percent": comparison.relative_within_50_percent,
                "valid_frame_count": int(np.count_nonzero(comparison.valid)),
                "valid_fraction": comparison.valid_fraction,
                "matched_seconds": comparison.matched_seconds,
            },
            "frames": frames,
        },
        "warnings": warnings,
    }
    artifact_path.write_text(
        json.dumps(artifact, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    progress(f"Analysis written to {artifact_path}")
    return artifact_path

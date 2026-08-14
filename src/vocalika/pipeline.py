from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any

import numpy as np

from vocalika import __version__
from vocalika.analysis.alignment import align_pitch_tracks
from vocalika.analysis.comparison import compare_alignment
from vocalika.analysis.pitch import PitchTrack, PyinPitchExtractor
from vocalika.analysis.pitch_cache import extract_clean_pitch
from vocalika.analysis.stable_notes import analyze_stable_pitch_centers
from vocalika.audio.preprocessing import normalize_for_analysis
from vocalika.audio.separation import DemucsVocalSeparator, SeparationResult
from vocalika.audio.sources import (
    AudioAsset,
    LocalAudioSource,
    YouTubeAudioSource,
    is_youtube_url,
)
from vocalika.cache.manager import CacheManager
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


def _acquire_reference(
    value: str | Path,
    cache: CacheManager,
    *,
    refresh: bool,
) -> AudioAsset:
    text = str(value)
    if is_youtube_url(text):
        return YouTubeAudioSource(text, cache, refresh=refresh).acquire()
    return LocalAudioSource(Path(value)).acquire()


def run_analysis(
    reference_path: str | Path,
    performance_path: Path,
    output: Path,
    *,
    reference_is_vocal: bool = False,
    reference_mix_path: Path | None = None,
    config: AnalysisConfig | None = None,
    cache_directory: Path | None = None,
    refresh_cache: bool = False,
    progress: ProgressCallback = _quiet,
) -> Path:
    config = config or AnalysisConfig()
    cache = (
        CacheManager(cache_directory.expanduser().resolve())
        if cache_directory
        else CacheManager.default()
    )
    output_directory, artifact_path = _resolve_output_paths(output)
    explicit_name = artifact_path.name != "analysis.json"
    asset_prefix = f"{artifact_path.stem}." if explicit_name else ""
    output_directory.mkdir(parents=True, exist_ok=True)

    progress("Acquiring reference audio")
    reference_asset = _acquire_reference(reference_path, cache, refresh=refresh_cache)
    progress("Inspecting performance audio")
    performance_asset = LocalAudioSource(performance_path).acquire()
    reference_mix_asset = (
        LocalAudioSource(reference_mix_path).acquire() if reference_mix_path else None
    )

    separation: SeparationResult | None = None
    analysis_reference_asset = reference_asset
    if not reference_is_vocal:
        progress("Isolating reference vocal")
        separation = DemucsVocalSeparator(cache, refresh=refresh_cache).separate(reference_asset)
        separated_asset = LocalAudioSource(separation.vocals).acquire()
        analysis_reference_asset = replace(
            separated_asset,
            source_type="derived_vocal",
            title=f"{reference_asset.title or 'Reference'} — vocals",
            source_url=reference_asset.source_url,
            metadata={
                **separated_asset.metadata,
                "derived_from": reference_asset.content_hash,
                "separation": separation.to_dict(),
            },
        )
        reference_mix_asset = reference_asset

    progress("Normalizing reference audio")
    normalized_reference = normalize_for_analysis(
        analysis_reference_asset,
        cache,
        config.analysis_sample_rate,
        refresh=refresh_cache,
    )
    progress("Normalizing performance audio")
    normalized_performance = normalize_for_analysis(
        performance_asset,
        cache,
        config.analysis_sample_rate,
        refresh=refresh_cache,
    )

    extractor = PyinPitchExtractor(
        hop_length=config.pitch_hop_length,
        frame_length=config.pitch_frame_length,
        fmin_midi=config.pitch_min_midi,
        fmax_midi=config.pitch_max_midi,
        concert_pitch_hz=config.concert_pitch_hz,
    )
    cleaning_parameters = {
        "confidence_threshold": config.pitch_confidence_threshold,
        "octave_window": config.octave_window_frames,
        "max_gap_seconds": config.max_pitch_gap_seconds,
    }
    progress("Extracting reference pitch")
    cached_reference_pitch = extract_clean_pitch(
        audio_path=normalized_reference.path,
        content_hash=analysis_reference_asset.content_hash,
        cache=cache,
        extractor=extractor,
        cleaning_parameters=cleaning_parameters,
        pipeline_version=__version__,
        refresh=refresh_cache,
    )
    progress("Extracting performance pitch")
    cached_performance_pitch = extract_clean_pitch(
        audio_path=normalized_performance.path,
        content_hash=performance_asset.content_hash,
        cache=cache,
        extractor=extractor,
        cleaning_parameters=cleaning_parameters,
        pipeline_version=__version__,
        refresh=refresh_cache,
    )
    reference_pitch = cached_reference_pitch.track
    performance_pitch = cached_performance_pitch.track

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
    stable_pitch = analyze_stable_pitch_centers(
        alignment,
        comparison,
        frames_per_second=alignment.frames_per_second,
        window_seconds=config.stable_note_window_seconds,
        max_span_cents=config.stable_note_max_span_cents,
        max_slope_cents_per_second=config.stable_note_max_slope_cents_per_second,
        minimum_duration_seconds=config.stable_note_minimum_duration_seconds,
        minimum_voiced_window_fraction=config.stable_note_minimum_voiced_window_fraction,
        minimum_matched_region_fraction=config.stable_note_minimum_matched_region_fraction,
        minimum_alignment_duration_ratio=(config.stable_note_minimum_alignment_duration_ratio),
        maximum_alignment_duration_ratio=(config.stable_note_maximum_alignment_duration_ratio),
        confidence_threshold=config.pitch_confidence_threshold,
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
    if not stable_pitch.regions:
        warnings.append(
            "No sufficiently long, stable reference pitch regions were found; pitch-center "
            "metrics are unavailable."
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
            "source": reference_asset.to_dict(),
            "analysis_source": analysis_reference_asset.to_dict(),
            "analysis_audio": str(normalized_reference.path),
            "normalization_cache_hit": normalized_reference.cache_hit,
            "conversion": {
                "input_sample_rate": analysis_reference_asset.sample_rate,
                "analysis_sample_rate": config.analysis_sample_rate,
                "channels": 1,
                "sample_format": "float32_pcm",
            },
            "is_isolated_vocal": reference_is_vocal,
            "original_mix": reference_mix_asset.to_dict() if reference_mix_asset else None,
            "separation": separation.to_dict() if separation else None,
        },
        "performance": {
            "source": performance_asset.to_dict(),
            "analysis_audio": str(normalized_performance.path),
            "normalization_cache_hit": normalized_performance.cache_hit,
            "conversion": {
                "input_sample_rate": performance_asset.sample_rate,
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
            "reference_cache_hit": cached_reference_pitch.cache_hit,
            "performance_cache_hit": cached_performance_pitch.cache_hit,
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
                "stable_note_pitch_center_mae_cents": stable_pitch.pitch_center_mae_cents,
                "relative_stable_note_pitch_center_mae_cents": (
                    stable_pitch.relative_pitch_center_mae_cents
                ),
                "stable_note_duration_weighted_mae_cents": (
                    stable_pitch.duration_weighted_mae_cents
                ),
                "relative_stable_note_duration_weighted_mae_cents": (
                    stable_pitch.relative_duration_weighted_mae_cents
                ),
                "stable_note_region_count": len(stable_pitch.regions),
                "stable_note_total_seconds": stable_pitch.total_stable_seconds,
            },
            "frames": frames,
            "stable_pitch_regions": [region.to_dict() for region in stable_pitch.regions],
        },
        "warnings": warnings,
    }
    artifact_path.write_text(
        json.dumps(artifact, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    progress(f"Analysis written to {artifact_path}")
    return artifact_path

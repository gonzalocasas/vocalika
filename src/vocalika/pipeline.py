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
from vocalika.analysis.offset import (
    GlobalOffsetEstimate,
    estimate_global_offset,
    estimate_spectral_change_offset,
    estimate_vocal_envelope_offset,
    refine_global_offset,
    select_global_offset,
)
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


def _derived_vocal_asset(
    source: AudioAsset,
    separation: SeparationResult,
    label: str,
) -> AudioAsset:
    separated = LocalAudioSource(separation.vocals).acquire()
    return replace(
        separated,
        source_type="derived_vocal",
        title=f"{source.title or label} — vocals",
        source_url=source.source_url,
        metadata={
            **separated.metadata,
            "derived_from": source.content_hash,
            "separation": separation.to_dict(),
        },
    )


def run_analysis(
    reference_path: str | Path,
    performance_path: Path,
    output: Path,
    *,
    reference_is_vocal: bool = False,
    reference_mix_path: Path | None = None,
    isolate_performance: bool = False,
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

    reference_separation: SeparationResult | None = None
    analysis_reference_asset = reference_asset
    if not reference_is_vocal:
        progress("Isolating reference vocal")
        reference_separation = DemucsVocalSeparator(cache, refresh=refresh_cache).separate(
            reference_asset
        )
        analysis_reference_asset = _derived_vocal_asset(
            reference_asset,
            reference_separation,
            "Reference",
        )
        reference_mix_asset = reference_asset

    performance_separation: SeparationResult | None = None
    analysis_performance_asset = performance_asset
    performance_mix_asset: AudioAsset | None = None
    if isolate_performance:
        progress("Isolating performance vocal")
        performance_separation = DemucsVocalSeparator(cache, refresh=refresh_cache).separate(
            performance_asset
        )
        analysis_performance_asset = _derived_vocal_asset(
            performance_asset,
            performance_separation,
            "Performance",
        )
        performance_mix_asset = performance_asset

    progress("Normalizing reference audio")
    normalized_reference = normalize_for_analysis(
        analysis_reference_asset,
        cache,
        config.analysis_sample_rate,
        refresh=refresh_cache,
    )
    progress("Normalizing performance audio")
    normalized_performance = normalize_for_analysis(
        analysis_performance_asset,
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
        harmonic_margin=config.pitch_harmonic_margin,
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
        content_hash=analysis_performance_asset.content_hash,
        cache=cache,
        extractor=extractor,
        cleaning_parameters=cleaning_parameters,
        pipeline_version=__version__,
        refresh=refresh_cache,
    )
    reference_pitch = cached_reference_pitch.track
    performance_pitch = cached_performance_pitch.track

    progress("Estimating global time offset")
    offset_estimates: list[GlobalOffsetEstimate] = []
    offset_estimation_errors: list[str] = []
    try:
        offset_estimates.append(
            estimate_global_offset(
                normalized_reference.path,
                normalized_performance.path,
                maximum_offset_seconds=config.alignment_maximum_offset_seconds,
            )
        )
    except (OSError, ValueError) as error:
        offset_estimation_errors.append(f"PCM: {error}")
    try:
        offset_estimates.append(
            estimate_spectral_change_offset(
                normalized_reference.path,
                normalized_performance.path,
            )
        )
    except (OSError, ValueError) as error:
        offset_estimation_errors.append(f"spectral changes: {error}")
    try:
        offset_estimates.append(
            estimate_vocal_envelope_offset(
                normalized_reference.path,
                normalized_performance.path,
            )
        )
    except (OSError, ValueError) as error:
        offset_estimation_errors.append(f"vocal envelope: {error}")
    # Estimators are ordered from most identity-specific to least. Direct PCM
    # wins for identical audio; spectral changes can distinguish lyrics that
    # share a melody; the energy envelope remains a useful final fallback.
    offset_estimate = select_global_offset(
        offset_estimates,
        config.alignment_offset_minimum_confidence,
    )
    offset_estimate = refine_global_offset(offset_estimate, offset_estimates)
    offset_estimation_error = "; ".join(offset_estimation_errors) or None
    applied_offset_seconds = (
        offset_estimate.seconds
        if offset_estimate is not None
        and offset_estimate.confidence >= config.alignment_offset_minimum_confidence
        and abs(offset_estimate.seconds) >= 0.5 / config.alignment_frames_per_second
        else None
    )
    progress("Aligning pitch tracks")
    alignment = align_pitch_tracks(
        reference_pitch,
        performance_pitch,
        frames_per_second=config.alignment_frames_per_second,
        band_radius=config.alignment_band_radius,
        global_offset_seconds=applied_offset_seconds,
        temporal_consistency_weight=config.alignment_temporal_consistency_weight,
        allow_subsequence=(
            offset_estimate is not None
            and offset_estimate.confidence >= config.alignment_offset_minimum_confidence
        ),
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
        "reference_confidence": alignment.reference.confidence[
            alignment.reference_indices
        ].tolist(),
        "performance_confidence": alignment.performance.confidence[
            alignment.performance_indices
        ].tolist(),
        "reference_voiced": alignment.reference.voiced[alignment.reference_indices].tolist(),
        "performance_voiced": alignment.performance.voiced[alignment.performance_indices].tolist(),
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
            "separation": reference_separation.to_dict() if reference_separation else None,
        },
        "performance": {
            "source": performance_asset.to_dict(),
            "analysis_source": analysis_performance_asset.to_dict(),
            "analysis_audio": str(normalized_performance.path),
            "normalization_cache_hit": normalized_performance.cache_hit,
            "conversion": {
                "input_sample_rate": performance_asset.sample_rate,
                "analysis_sample_rate": config.analysis_sample_rate,
                "channels": 1,
                "sample_format": "float32_pcm",
            },
            "is_isolated_vocal": True,
            "isolation_applied": isolate_performance,
            "original_mix": performance_mix_asset.to_dict() if performance_mix_asset else None,
            "separation": (performance_separation.to_dict() if performance_separation else None),
        },
        "pitch": {
            "extractor": reference_pitch.extractor,
            "sample_rate": reference_pitch.sample_rate,
            "hop_length": reference_pitch.hop_length,
            "fmin_midi": extractor.fmin_midi,
            "fmax_midi": extractor.fmax_midi,
            "concert_pitch_hz": extractor.concert_pitch_hz,
            "harmonic_margin": extractor.harmonic_margin,
            "arrays": arrays_path.name,
            "reference_cache_hit": cached_reference_pitch.cache_hit,
            "performance_cache_hit": cached_performance_pitch.cache_hit,
        },
        "alignment": {
            "method": "audio-offset-plus-open-ended-temporally-regularized-pitch-dtw",
            "frames_per_second": alignment.frames_per_second,
            "point_count": int(comparison.reference_times.size),
            "temporal_consistency_weight": (alignment.effective_temporal_consistency_weight),
            "subsequence_alignment_applied": alignment.used_subsequence,
            "global_offset_seconds": offset_estimate.seconds if offset_estimate else None,
            "global_offset_confidence": offset_estimate.confidence if offset_estimate else None,
            "global_offset_method": offset_estimate.method if offset_estimate else None,
            "global_offset_raw_correlation": (
                offset_estimate.raw_correlation if offset_estimate else None
            ),
            "global_offset_peak_margin": offset_estimate.peak_margin if offset_estimate else None,
            "global_offset_candidates": [
                {
                    "method": estimate.method,
                    "seconds": estimate.seconds,
                    "confidence": estimate.confidence,
                    "raw_correlation": estimate.raw_correlation,
                    "peak_margin": estimate.peak_margin,
                }
                for estimate in offset_estimates
            ],
            "global_offset_applied": applied_offset_seconds is not None,
            "global_offset_error": offset_estimation_error,
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

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from vocalika import __version__
from vocalika.analysis.alignment import align_pitch_tracks
from vocalika.analysis.cleaning import clean_pitch_track
from vocalika.analysis.comparison import compare_alignment
from vocalika.analysis.pitch import PitchTrack, PyinPitchExtractor
from vocalika.audio.decode import decode_for_analysis, probe_audio

ProgressCallback = Callable[[str], None]


def _quiet(_: str) -> None:
    pass


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
    output_directory: Path,
    *,
    reference_is_vocal: bool = False,
    progress: ProgressCallback = _quiet,
) -> Path:
    output_directory = output_directory.expanduser().resolve()
    work_directory = output_directory / "working-audio"
    output_directory.mkdir(parents=True, exist_ok=True)

    progress("Inspecting input audio")
    reference_info = probe_audio(reference_path)
    performance_info = probe_audio(performance_path)

    progress("Decoding reference to analysis audio")
    reference_wav = decode_for_analysis(reference_path, work_directory / "reference.wav")
    progress("Decoding performance to analysis audio")
    performance_wav = decode_for_analysis(performance_path, work_directory / "performance.wav")

    extractor = PyinPitchExtractor()
    progress("Extracting reference pitch")
    reference_pitch = clean_pitch_track(extractor.extract(reference_wav))
    progress("Extracting performance pitch")
    performance_pitch = clean_pitch_track(extractor.extract(performance_wav))

    progress("Aligning pitch tracks")
    alignment = align_pitch_tracks(reference_pitch, performance_pitch)
    progress("Calculating pitch differences")
    comparison = compare_alignment(alignment)

    arrays_path = output_directory / "pitch-tracks.npz"
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
    artifact: dict[str, Any] = {
        "schema_version": "0.1.0",
        "created_at": datetime.now(UTC).isoformat(),
        "pipeline_version": __version__,
        "reference": {
            "source": reference_info.to_dict(),
            "analysis_audio": str(reference_wav),
            "is_isolated_vocal": reference_is_vocal,
        },
        "performance": {
            "source": performance_info.to_dict(),
            "analysis_audio": str(performance_wav),
            "is_isolated_vocal": True,
        },
        "pitch": {
            "extractor": reference_pitch.extractor,
            "sample_rate": reference_pitch.sample_rate,
            "hop_length": reference_pitch.hop_length,
            "fmin_midi": extractor.fmin_midi,
            "fmax_midi": extractor.fmax_midi,
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
                "within_25_percent": comparison.within_25_percent,
                "within_50_percent": comparison.within_50_percent,
                "valid_frame_count": int(np.count_nonzero(comparison.valid)),
            },
            "frames": frames,
        },
        "warnings": (
            []
            if reference_is_vocal
            else [
                "Milestone 0 does not isolate vocals. Pitch extracted from a full mix may follow "
                "instruments or backing vocals."
            ]
        ),
    }
    artifact_path = output_directory / "analysis.json"
    artifact_path.write_text(
        json.dumps(artifact, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    progress(f"Analysis written to {artifact_path}")
    return artifact_path

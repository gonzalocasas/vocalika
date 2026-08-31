from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from vocalika import __version__
from vocalika.analysis.pitch import PyinPitchExtractor
from vocalika.analysis.pitch_cache import extract_clean_pitch
from vocalika.api.reference_pitch import build_reference_pitch
from vocalika.audio.preprocessing import normalize_for_analysis
from vocalika.audio.sources import LocalAudioSource
from vocalika.cache.manager import CacheManager
from vocalika.config import AnalysisConfig
from vocalika.projects.models import Project, ProjectReference
from vocalika.projects.reference_audio import ReferenceAudioService
from vocalika.projects.repository import ProjectRepository


def _reference_wav(path: Path, sample_rate: int = 44_100, seconds: float = 3.0) -> Path:
    """A tone at a rate that is deliberately not the analysis rate."""
    times = np.arange(int(sample_rate * seconds), dtype=np.float64) / sample_rate
    wave = 0.3 * np.sin(2 * np.pi * 220.0 * times) + 0.1 * np.sin(2 * np.pi * 440.0 * times)
    sf.write(path, wave.astype(np.float32), sample_rate)
    return path


def _project(tmp_path: Path, source: Path) -> tuple[Project, ProjectRepository]:
    repository = ProjectRepository(tmp_path / "projects")
    project = Project(
        id="e" * 32,
        title="Cache agreement",
        created_at="2026-09-01T00:00:00Z",
        updated_at="2026-09-01T00:00:00Z",
        reference=ProjectReference(
            title="Reference",
            source_type="local",
            source_url=None,
            original_path=str(source),
            vocal_path=str(source),
            instrumental_path=str(source),
            duration_seconds=3.0,
            sample_rate=48_000,
            separation_model="test",
            separation_cached=False,
        ),
    )
    repository.save(project)
    return project, repository


def test_the_contour_endpoint_caches_what_the_pipeline_would_read(tmp_path: Path) -> None:
    """The endpoint and the pipeline share one cache entry, so they must agree.

    Both key on the hash of the source vocal, but the pipeline extracts from
    the analysis-rate normalization of that file. An endpoint that extracted
    straight from the source would store a 44.1 kHz track under the key the
    pipeline reads for its 16 kHz one, and every later analysis would compare
    against a reference measured with a different window -- with a cache hit,
    so nothing would look wrong.
    """
    source = _reference_wav(tmp_path / "vocals.wav")
    project, repository = _project(tmp_path, source)
    cache = CacheManager(tmp_path / "cache")
    config = AnalysisConfig()

    build_reference_pitch(project, ReferenceAudioService(repository), cache, 0, config=config)

    # Now read the cache exactly as the pipeline does.
    asset = LocalAudioSource(source).acquire()
    normalized = normalize_for_analysis(asset, cache, config.analysis_sample_rate)
    cached = extract_clean_pitch(
        audio_path=normalized.path,
        content_hash=asset.content_hash,
        cache=cache,
        extractor=PyinPitchExtractor(
            hop_length=config.pitch_hop_length,
            frame_length=config.pitch_frame_length,
            fmin_midi=config.pitch_min_midi,
            fmax_midi=config.pitch_max_midi,
            concert_pitch_hz=config.concert_pitch_hz,
            harmonic_margin=config.pitch_harmonic_margin,
        ),
        cleaning_parameters=config.cleaning_parameters(),
        pipeline_version=__version__,
    )

    assert cached.cache_hit, "the pipeline must reuse the endpoint's entry, not rebuild it"
    assert cached.track.sample_rate == config.analysis_sample_rate, (
        f"cached track is at {cached.track.sample_rate} Hz, not the analysis rate"
    )
    expected_frames = math.ceil(3.0 * config.analysis_sample_rate / config.pitch_hop_length)
    assert cached.track.times.size == pytest.approx(expected_frames, abs=4), (
        f"{cached.track.times.size} frames is not a 16 kHz track of this audio"
    )


def test_the_contour_endpoint_reports_the_analysis_rate_timeline(tmp_path: Path) -> None:
    source = _reference_wav(tmp_path / "vocals.wav")
    project, repository = _project(tmp_path, source)
    cache = CacheManager(tmp_path / "cache")

    payload = build_reference_pitch(project, ReferenceAudioService(repository), cache, 0)

    assert payload["times"][-1] == pytest.approx(3.0, abs=0.1)
    step = payload["times"][1] - payload["times"][0]
    assert step == pytest.approx(256 / 16_000, abs=1e-6), (
        "frame spacing must follow the analysis rate"
    )

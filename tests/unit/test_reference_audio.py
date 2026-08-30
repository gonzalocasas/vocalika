from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from vocalika.projects.models import Project, ProjectReference
from vocalika.projects.reference_audio import ReferenceAudioService, transpose_ratio
from vocalika.projects.repository import ProjectRepository


def test_transposed_reference_changes_pitch_without_changing_duration(tmp_path: Path) -> None:
    sample_rate = 16_000
    duration = 2.0
    source = tmp_path / "reference.wav"
    times = np.arange(round(duration * sample_rate), dtype=np.float32) / sample_rate
    sf.write(source, 0.2 * np.sin(2 * np.pi * 440 * times), sample_rate)
    repository = ProjectRepository(tmp_path / "projects")
    project = Project(
        id="c" * 32,
        title="Transpose test",
        created_at="2026-08-22T10:00:00Z",
        updated_at="2026-08-22T10:00:00Z",
        reference=ProjectReference(
            title="Reference",
            source_type="local",
            source_url=None,
            original_path=str(source),
            vocal_path=str(source),
            instrumental_path=str(source),
            duration_seconds=duration,
            sample_rate=sample_rate,
            separation_model="test",
            separation_cached=False,
        ),
    )
    repository.save(project)
    service = ReferenceAudioService(repository)

    rendered = service.resolve(project, "vocal", 2)
    samples, rendered_rate = sf.read(rendered, dtype="float32")
    center = samples[rendered_rate // 2 : -rendered_rate // 2]
    frequencies = np.fft.rfftfreq(center.size, 1 / rendered_rate)
    peak_frequency = frequencies[int(np.argmax(np.abs(np.fft.rfft(center))))]

    assert rendered_rate == sample_rate
    assert len(samples) / rendered_rate == pytest.approx(duration, abs=0.03)
    assert peak_frequency == pytest.approx(440 * transpose_ratio(2), abs=3)
    assert service.resolve(project, "vocal", 2) == rendered


def test_transposition_uses_the_file_rate_not_the_declared_one(tmp_path: Path) -> None:
    """The stems are not written at the rate the project records.

    A project stores the sample rate of the original download, but demucs
    writes its stems at its own rate -- 44.1 kHz against a 48 kHz source in
    practice. `asetrate` reinterprets a stream as if it had a given rate, so
    feeding it the declared rate rendered transposed audio at the ratio
    between the two: 8.8% fast, and short of the requested transposition.
    """
    file_rate = 44_100
    declared_rate = 48_000
    duration = 2.0
    source = tmp_path / "reference.wav"
    times = np.arange(round(duration * file_rate), dtype=np.float32) / file_rate
    sf.write(source, 0.2 * np.sin(2 * np.pi * 440 * times), file_rate)

    repository = ProjectRepository(tmp_path / "projects")
    project = Project(
        id="d" * 32,
        title="Rate mismatch",
        created_at="2026-08-30T10:00:00Z",
        updated_at="2026-08-30T10:00:00Z",
        reference=ProjectReference(
            title="Reference",
            source_type="local",
            source_url=None,
            original_path=str(source),
            vocal_path=str(source),
            instrumental_path=str(source),
            duration_seconds=duration,
            # Deliberately not the rate the file was written at.
            sample_rate=declared_rate,
            separation_model="test",
            separation_cached=False,
        ),
    )
    repository.save(project)
    service = ReferenceAudioService(repository)

    rendered = service.resolve(project, "vocal", -4)
    samples, rendered_rate = sf.read(rendered, dtype="float32")

    assert len(samples) / rendered_rate == pytest.approx(duration, abs=0.05), (
        "transposition must preserve duration even when the declared rate is wrong"
    )
    center = samples[rendered_rate // 2 : -rendered_rate // 2]
    frequencies = np.fft.rfftfreq(center.size, 1 / rendered_rate)
    peak = frequencies[int(np.argmax(np.abs(np.fft.rfft(center))))]
    assert peak == pytest.approx(440 * transpose_ratio(-4), abs=4), (
        "the pitch must land where the transposition asked, not scaled by the "
        "ratio between the declared and actual rates"
    )

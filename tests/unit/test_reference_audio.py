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

from __future__ import annotations

from pathlib import Path

import numpy as np
import soundfile as sf
from typer.testing import CliRunner

from vocalika.cache.manager import CacheManager
from vocalika.cli import app
from vocalika.projects.repository import ProjectRepository
from vocalika.projects.service import ProjectService

SAMPLE_RATE = 16_000


def _melody(path: Path, offset_cents: float = 0.0) -> Path:
    """Four voice-like notes, so there is something to align and compare."""
    parts = []
    for midi in (60.0, 62.0, 64.0, 67.0):
        times = np.arange(SAMPLE_RATE, dtype=np.float64) / SAMPLE_RATE
        phase = 2 * np.pi * 440.0 * 2 ** ((midi + offset_cents / 100 - 69) / 12) * times
        parts.append(sum(0.2 / h * np.sin(h * phase) for h in range(1, 6)))
    sf.write(path, np.concatenate(parts).astype(np.float32), SAMPLE_RATE)
    return path


def test_reanalyze_recomputes_the_takes_of_the_chosen_project(tmp_path: Path) -> None:
    analyses = tmp_path / "analysis-output"
    service = ProjectService(
        ProjectRepository(analyses / "projects"), cache=CacheManager(tmp_path / "cache")
    )
    project = service.create_project(
        service.new_id(),
        _melody(tmp_path / "reference.wav"),
        title="Duet song",
        reference_is_vocal=True,
    )
    service.update_settings(project.id, reference_voice="upper")
    _, take, _ = service.add_take(
        project.id,
        _melody(tmp_path / "take.wav", 20.0),
        name="Take",
        isolate_performance=False,
        analyze=False,
    )

    result = CliRunner().invoke(
        app,
        [
            "reanalyze",
            "--project",
            "duet",
            "--analyses-directory",
            str(analyses),
            "--cache-directory",
            str(tmp_path / "cache"),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Duet song (melody: upper voice)" in result.output
    reloaded = service.repository.load(project.id).takes[0]
    assert reloaded.status == "analyzed"
    assert reloaded.reference_voice == "upper"
    assert reloaded.analysis_summary is not None
    assert abs(reloaded.analysis_summary["global_bias_cents"] - 20.0) < 5.0


def test_reanalyze_refuses_a_project_it_cannot_find(tmp_path: Path) -> None:
    (tmp_path / "analysis-output" / "projects").mkdir(parents=True)

    result = CliRunner().invoke(
        app,
        [
            "reanalyze",
            "--project",
            "nothing",
            "--analyses-directory",
            str(tmp_path / "analysis-output"),
        ],
    )

    assert result.exit_code != 0
    assert "No project matches" in result.output

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf
from httpx import ASGITransport, AsyncClient

from vocalika.api.app import create_app
from vocalika.projects.export import ProjectExportService
from vocalika.projects.models import Project, ProjectReference, Take
from vocalika.projects.repository import ProjectRepository


@pytest.mark.anyio
async def test_project_export_places_analyzed_take_on_reference_timeline(
    tmp_path: Path,
) -> None:
    sample_rate = 16_000
    project_id = "a" * 32
    take_id = "b" * 32
    repository = ProjectRepository(tmp_path / "projects")
    project_directory = repository.project_directory(project_id)
    take_directory = project_directory / "takes" / take_id
    take_directory.mkdir(parents=True)

    times = np.arange(2 * sample_rate, dtype=np.float32) / sample_rate
    instrumental = np.zeros((times.size, 2), dtype=np.float32)
    instrumental_path = project_directory / "instrumental.wav"
    sf.write(instrumental_path, instrumental, sample_rate)

    take_times = np.arange(sample_rate, dtype=np.float32) / sample_rate
    take_vocal = 0.2 * np.sin(2 * np.pi * 220 * take_times)
    take_wav = take_directory / "recorded.wav"
    take_path = take_directory / "source.webm"
    sf.write(take_wav, take_vocal, sample_rate)
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-i",
            str(take_wav),
            "-c:a",
            "libopus",
            str(take_path),
        ],
        check=True,
    )
    artifact_path = take_directory / "analysis.json"
    artifact_path.write_text(
        json.dumps(
            {
                "schema_version": "0.1.0",
                "performance": {
                    "source": {"path": str(take_path)},
                    "analysis_source": {"path": str(take_path)},
                },
                "comparison": {
                    "frames": {
                        "reference_time": [0.25, 0.5, 0.75, 1.0, 1.25],
                        "performance_time": [0.0, 0.25, 0.5, 0.75, 1.0],
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    take = Take(
        id=take_id,
        name="First take",
        created_at="2026-08-22T10:00:00Z",
        source_path=str(take_path),
        isolate_performance=False,
        status="analyzed",
        analysis_path=str(artifact_path),
    )
    repository.save(
        Project(
            id=project_id,
            title="Practice Song",
            created_at="2026-08-22T10:00:00Z",
            updated_at="2026-08-22T10:00:00Z",
            reference=ProjectReference(
                title="Reference",
                source_type="local",
                source_url=None,
                original_path=str(instrumental_path),
                vocal_path=str(instrumental_path),
                instrumental_path=str(instrumental_path),
                duration_seconds=2.0,
                sample_rate=sample_rate,
                separation_model="test",
                separation_cached=False,
            ),
            trim_start_seconds=0.25,
            trim_end_seconds=1.25,
            takes=(take,),
        )
    )

    result = ProjectExportService(repository).render(
        project_id,
        take_id,
        instrumental_db=-24,
        output_format="wav",
    )

    exported, exported_rate = sf.read(result.path, always_2d=True)
    assert exported_rate == 44_100
    assert exported.shape == (44_100, 2)
    assert float(np.max(np.abs(exported))) > 0.15
    assert result.filename == "practice-song_first-take_mix.wav"
    assert result.media_type == "audio/wav"

    app = create_app(
        None,
        projects_directory=repository.root,
        library_directory=tmp_path / "analyses",
        cache_directory=tmp_path / "cache",
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/api/projects/{project_id}/exports",
            json={
                "take_id": take_id,
                "instrumental_db": -24,
                "output_format": "wav",
            },
        )
    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/wav"
    assert "practice-song_first-take_mix.wav" in response.headers["content-disposition"]
    assert len(response.content) > 44_100

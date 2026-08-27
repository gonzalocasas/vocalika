from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf
from httpx import ASGITransport, AsyncClient

from vocalika.api.app import create_app


def _wav_bytes(path: Path, frequency: float = 220.0) -> bytes:
    sample_rate = 16_000
    times = np.arange(sample_rate, dtype=np.float32) / sample_rate
    sf.write(path, 0.25 * np.sin(2 * np.pi * frequency * times), sample_rate)
    return path.read_bytes()


@pytest.mark.anyio
async def test_projects_and_unanalyzed_takes_persist_across_app_instances(tmp_path: Path) -> None:
    reference_bytes = _wav_bytes(tmp_path / "reference.wav")
    take_bytes = _wav_bytes(tmp_path / "take.wav", 240.0)
    recorded_webm = tmp_path / "recorded.webm"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-i",
            str(tmp_path / "take.wav"),
            "-c:a",
            "libopus",
            str(recorded_webm),
        ],
        check=True,
    )
    projects = tmp_path / "projects"
    app = create_app(
        None,
        projects_directory=projects,
        library_directory=tmp_path / "analyses",
        cache_directory=tmp_path / "cache",
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post(
            "/api/projects",
            data={"title": "Practice song", "reference_is_vocal": "true"},
            files={"reference_file": ("reference.wav", reference_bytes, "audio/wav")},
        )
        assert created.status_code == 200
        project = created.json()["project"]
        project_id = project["id"]
        assert project["title"] == "Practice song"
        assert Path(project["reference"]["original_path"]).is_file()

        updated = await client.patch(
            f"/api/projects/{project_id}",
            json={
                "trim_start_seconds": 0.2,
                "trim_end_seconds": 0.8,
                "transpose_semitones": -3,
                "lyrics": "First verse\nSecond line",
            },
        )
        assert updated.status_code == 200
        assert updated.json()["project"]["trim_start_seconds"] == 0.2
        assert updated.json()["project"]["lyrics"] == "First verse\nSecond line"
        assert updated.json()["project"]["transpose_semitones"] == -3

        added = await client.post(
            f"/api/projects/{project_id}/takes",
            data={"analyze": "false", "name": "Morning take"},
            files={"audio_file": ("take.wav", take_bytes, "audio/wav")},
        )
        assert added.status_code == 200
        assert added.json()["take"]["status"] == "ready"
        assert added.json()["take"]["reference_transpose_semitones"] == -3
        assert Path(added.json()["take"]["source_path"]).is_file()

        browser_take = await client.post(
            f"/api/projects/{project_id}/takes",
            data={"analyze": "false", "name": "Browser recording"},
            files={"audio_file": ("recording.webm", recorded_webm.read_bytes(), "audio/webm")},
        )
        assert browser_take.status_code == 200
        browser_take_id = browser_take.json()["take"]["id"]
        browser_take_directory = Path(browser_take.json()["take"]["source_path"]).parent
        waveform = await client.get(f"/api/projects/{project_id}/takes/{browser_take_id}/waveform")
        assert waveform.status_code == 200
        assert len(waveform.json()["amplitude"]) == 100

        deleted = await client.delete(f"/api/projects/{project_id}/takes/{browser_take_id}")
        assert deleted.status_code == 200
        assert [take["name"] for take in deleted.json()["project"]["takes"]] == ["Morning take"]
        assert not browser_take_directory.exists()
        assert (
            await client.delete(f"/api/projects/{project_id}/takes/{browser_take_id}")
        ).status_code == 404

    restarted = create_app(
        None,
        projects_directory=projects,
        library_directory=tmp_path / "analyses",
        cache_directory=tmp_path / "cache",
    )
    async with AsyncClient(
        transport=ASGITransport(app=restarted),
        base_url="http://test",
    ) as client:
        listing = (await client.get("/api/projects")).json()["projects"]
        assert len(listing) == 1
        assert listing[0]["takes"][0]["name"] == "Morning take"
        assert listing[0]["lyrics"] == "First verse\nSecond line"
        assert (await client.get(f"/api/projects/{project_id}/audio/vocal")).status_code == 200


@pytest.mark.anyio
async def test_project_ids_reject_path_traversal(tmp_path: Path) -> None:
    app = create_app(None, projects_directory=tmp_path / "projects")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/projects/not-a-project")

    assert response.status_code == 404

from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf
from httpx import ASGITransport, AsyncClient

from vocalika import storage
from vocalika.api.app import create_app
from vocalika.projects.models import Project, ProjectReference, Take
from vocalika.projects.repository import ProjectRepository, load_take_artifact
from vocalika.projects.sidecar import cached
from vocalika.storage import StorageError, StorageSettings, move_projects

PROJECT_ID = "a" * 32
TAKE_ID = "b" * 32


def _write_project(projects: Path, project_id: str = PROJECT_ID) -> Project:
    """A project with real audio, an analysed take, and the paths an analysis records."""
    directory = projects / project_id
    reference = directory / "reference" / "original.wav"
    take_directory = directory / "takes" / TAKE_ID
    source = take_directory / "source.wav"
    artifact_path = take_directory / "analysis" / "analysis.json"
    for path in (reference, source, artifact_path):
        path.parent.mkdir(parents=True, exist_ok=True)
    times = np.arange(16_000, dtype=np.float32) / 16_000
    sf.write(reference, 0.25 * np.sin(2 * np.pi * 220 * times), 16_000)
    sf.write(source, 0.25 * np.sin(2 * np.pi * 240 * times), 16_000)
    artifact_path.write_text(
        json.dumps(
            {
                "schema_version": "0.1.0",
                "performance": {
                    "source": {"path": str(source.resolve())},
                    "analysis_source": {"path": str(source.resolve())},
                },
                "comparison": {"frames": {"reference_time": [0.0, 0.5]}},
            }
        ),
        encoding="utf-8",
    )
    project = Project(
        id=project_id,
        title="Practice song",
        created_at="2026-08-27T00:00:00+00:00",
        updated_at="2026-08-27T00:00:00+00:00",
        reference=ProjectReference(
            title="Reference",
            source_type="local",
            source_url=None,
            original_path=str(reference.resolve()),
            vocal_path=str(reference.resolve()),
            instrumental_path=None,
            duration_seconds=1.0,
            sample_rate=16_000,
            separation_model=None,
            separation_cached=False,
        ),
        takes=(
            Take(
                id=TAKE_ID,
                name="Take",
                created_at="2026-08-27T00:00:00+00:00",
                source_path=str(source.resolve()),
                isolate_performance=False,
                status="analyzed",
                analysis_path=str(artifact_path.resolve()),
            ),
        ),
    )
    return ProjectRepository(projects).save(project)


def _legacy_manifest(projects: Path, project_id: str = PROJECT_ID) -> None:
    """Rewrite a manifest the way projects were stored before: absolute paths."""
    manifest = projects / project_id / "project.json"
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    root = projects.resolve() / project_id
    payload["reference"]["original_path"] = str(root / payload["reference"]["original_path"])
    payload["reference"]["vocal_path"] = str(root / payload["reference"]["vocal_path"])
    for take in payload["takes"]:
        take["source_path"] = str(root / take["source_path"])
        take["analysis_path"] = str(root / take["analysis_path"])
    manifest.write_text(json.dumps(payload), encoding="utf-8")


def test_project_paths_are_stored_relative_to_the_project(tmp_path: Path) -> None:
    _write_project(tmp_path / "projects")

    stored = json.loads((tmp_path / "projects" / PROJECT_ID / "project.json").read_text())
    assert stored["reference"]["original_path"] == "reference/original.wav"
    assert stored["takes"][0]["source_path"] == f"takes/{TAKE_ID}/source.wav"

    loaded = ProjectRepository(tmp_path / "projects").load(PROJECT_ID)
    assert Path(loaded.takes[0].source_path).is_file()


def test_legacy_absolute_paths_follow_a_folder_moved_by_hand(tmp_path: Path) -> None:
    _write_project(tmp_path / "old" / "projects")
    _legacy_manifest(tmp_path / "old" / "projects")
    shutil.move(tmp_path / "old", tmp_path / "new")

    project = ProjectRepository(tmp_path / "new" / "projects").load(PROJECT_ID)
    take = project.takes[0]

    new_root = (tmp_path / "new" / "projects" / PROJECT_ID).resolve()
    assert Path(project.reference.original_path) == new_root / "reference" / "original.wav"
    assert Path(take.source_path).is_file()
    artifact = load_take_artifact(take)
    assert Path(artifact["performance"]["source"]["path"]).is_file()
    assert Path(artifact["performance"]["source"]["path"]).is_relative_to(new_root)


def test_a_copied_folder_reads_its_own_files_not_the_original(tmp_path: Path) -> None:
    _write_project(tmp_path / "old" / "projects")
    _legacy_manifest(tmp_path / "old" / "projects")
    shutil.copytree(tmp_path / "old", tmp_path / "copy")

    project = ProjectRepository(tmp_path / "copy" / "projects").load(PROJECT_ID)

    assert Path(project.takes[0].source_path).is_relative_to((tmp_path / "copy").resolve())


def test_derived_values_are_recomputed_only_when_the_source_changes(tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    source.write_text("one")
    calls: list[int] = []

    def compute() -> dict[str, int]:
        calls.append(1)
        return {"n": len(calls)}

    cache_file = tmp_path / "derived.cache"
    assert cached(cache_file, source, compute) == {"n": 1}
    assert cached(cache_file, source, compute) == {"n": 1}
    source.write_text("changed")
    assert cached(cache_file, source, compute) == {"n": 2}


def test_moving_projects_refuses_clashes_and_nesting(tmp_path: Path) -> None:
    _write_project(tmp_path / "a" / "projects")
    _write_project(tmp_path / "b" / "projects")

    with pytest.raises(StorageError, match="already has 1"):
        move_projects(tmp_path / "a" / "projects", tmp_path / "b" / "projects")
    with pytest.raises(StorageError, match="inside"):
        move_projects(tmp_path / "a" / "projects", tmp_path / "a" / "projects" / "nested")
    assert (tmp_path / "a" / "projects" / PROJECT_ID / "project.json").is_file()


@pytest.mark.parametrize("same_device", [True, False])
def test_moving_projects_moves_every_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, same_device: bool
) -> None:
    monkeypatch.setattr(storage, "_same_device", lambda *_: same_device)
    _write_project(tmp_path / "a" / "projects")
    _write_project(tmp_path / "a" / "projects", "c" * 32)

    assert move_projects(tmp_path / "a" / "projects", tmp_path / "b" / "projects") == 2

    assert not list((tmp_path / "a" / "projects").iterdir())
    assert sorted(path.name for path in (tmp_path / "b" / "projects").iterdir()) == [
        "a" * 32,
        "c" * 32,
    ]


def test_a_failed_copy_leaves_the_projects_where_they_were(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(storage, "_same_device", lambda *_: False)
    _write_project(tmp_path / "a" / "projects")
    _write_project(tmp_path / "a" / "projects", "c" * 32)
    copies = 0
    real_copytree = shutil.copytree

    def failing_copytree(*args: object, **kwargs: object) -> object:
        nonlocal copies
        copies += 1
        if copies == 2:
            raise OSError("disk full")
        return real_copytree(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(storage.shutil, "copytree", failing_copytree)

    with pytest.raises(OSError, match="disk full"):
        move_projects(tmp_path / "a" / "projects", tmp_path / "b" / "projects")

    assert len(list((tmp_path / "a" / "projects").iterdir())) == 2
    assert not list((tmp_path / "b" / "projects").iterdir())


def test_the_chosen_folder_is_remembered(tmp_path: Path) -> None:
    settings_path = tmp_path / "config" / "settings.json"
    first = StorageSettings(settings_path, tmp_path / "fallback")
    assert not first.configured
    assert first.data_directory == (tmp_path / "fallback").resolve()

    first.choose((tmp_path / "chosen").resolve())

    second = StorageSettings(settings_path, tmp_path / "fallback")
    assert second.configured
    assert second.data_directory == (tmp_path / "chosen").resolve()


@pytest.mark.anyio
async def test_first_start_then_moving_the_library_through_the_api(tmp_path: Path) -> None:
    _write_project(tmp_path / "start" / "projects")
    _legacy_manifest(tmp_path / "start" / "projects")
    settings = StorageSettings(tmp_path / "settings.json", tmp_path / "start")
    app = create_app(None, library_directory=tmp_path / "library", storage=settings)
    target = tmp_path / "Music" / "Vocalika"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        status = (await client.get("/api/settings/storage")).json()
        assert status["configured"] is False
        # The existing library is what a first start offers to keep.
        assert status["suggested_directory"] == str((tmp_path / "start").resolve())
        assert status["project_count"] == 1

        inspected = await client.post("/api/settings/storage/inspect", json={"path": str(target)})
        assert inspected.json() == {
            "path": str(target.resolve()),
            "exists": False,
            "project_count": 0,
            "problem": None,
        }

        moved = await client.put("/api/settings/storage", json={"path": str(target), "move": True})
        assert moved.status_code == 200
        assert moved.json()["configured"] is True
        assert moved.json()["project_count"] == 1

        listed = (await client.get("/api/projects")).json()["projects"]
        waveform = await client.get(f"/api/projects/{PROJECT_ID}/waveform/mix")
        take_waveform = await client.get(f"/api/projects/{PROJECT_ID}/takes/{TAKE_ID}/waveform")

    assert [project["id"] for project in listed] == [PROJECT_ID]
    assert Path(listed[0]["takes"][0]["source_path"]).is_relative_to(target.resolve())
    assert waveform.status_code == 200
    assert take_waveform.status_code == 200
    assert (target / "projects" / PROJECT_ID / "waveforms" / "mix.cache").is_file()
    assert not (tmp_path / "start" / "projects" / PROJECT_ID).exists()
    assert StorageSettings(tmp_path / "settings.json", tmp_path / "start").data_directory == (
        target.resolve()
    )


@pytest.mark.anyio
async def test_relative_folder_paths_are_refused(tmp_path: Path) -> None:
    app = create_app(
        None,
        library_directory=tmp_path / "library",
        storage=StorageSettings(tmp_path / "settings.json", tmp_path / "start"),
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.put("/api/settings/storage", json={"path": "music", "move": False})

    assert response.status_code == 409
    assert "full folder path" in response.json()["detail"]

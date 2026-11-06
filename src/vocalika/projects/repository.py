from __future__ import annotations

import json
import re
import shutil
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path, PurePath, PurePosixPath, PureWindowsPath
from threading import RLock
from typing import Any

from vocalika.models.artifact import load_artifact
from vocalika.projects.models import Project, Take

PROJECT_ID_PATTERN = re.compile(r"^[a-f0-9]{32}$")
MANIFEST = "project.json"


class ProjectNotFoundError(LookupError):
    pass


def locate(value: str, project_directory: Path) -> str:
    """Where a stored path is now, given the project's current folder.

    Paths inside a project are saved relative to it, so the data folder can be
    moved. Projects written before that hold absolute paths into wherever the
    folder used to be; those are recognised by the project id among their parts
    and re-rooted, so data moved by hand keeps working too. The copy inside the
    project wins even when the old location still exists, so a copied folder
    never reads from its original. Anything else (the shared cache, say) is
    left as it is.
    """
    path = Path(value)
    if not path.is_absolute():
        return str(project_directory / path)
    parts = path.parts
    if project_directory.name in parts:
        index = len(parts) - 1 - parts[::-1].index(project_directory.name)
        candidate = project_directory.joinpath(*parts[index + 1 :])
        if candidate == path or candidate.exists() or not path.exists():
            return str(candidate)
    return value


def portable(value: str, project_directory: Path) -> str:
    """A path as stored: relative when it lies inside the project."""
    try:
        return PurePath(value).relative_to(project_directory).as_posix()
    except ValueError:
        return value


def _map_paths(project: Project, mapping: Callable[[str], str]) -> Project:
    def optional(value: str | None) -> str | None:
        return None if value is None else mapping(value)

    reference = replace(
        project.reference,
        original_path=mapping(project.reference.original_path),
        vocal_path=optional(project.reference.vocal_path),
        instrumental_path=optional(project.reference.instrumental_path),
    )
    takes = tuple(
        replace(
            take,
            source_path=mapping(take.source_path),
            analysis_path=optional(take.analysis_path),
        )
        for take in project.takes
    )
    return replace(project, reference=reference, takes=takes)


def _is_absolute_path(value: str) -> bool:
    return PurePosixPath(value).is_absolute() or PureWindowsPath(value).is_absolute()


def _locate_in_artifact(value: Any, project_directory: Path) -> Any:
    if isinstance(value, dict):
        return {key: _locate_in_artifact(item, project_directory) for key, item in value.items()}
    if isinstance(value, list):
        # Frame arrays are long lists of numbers; only lists of records can
        # hold paths.
        if value and isinstance(value[0], dict):
            return [_locate_in_artifact(item, project_directory) for item in value]
        return value
    if isinstance(value, str) and _is_absolute_path(value):
        return locate(value, project_directory)
    return value


def load_take_artifact(take: Take) -> dict[str, Any]:
    """A take's analysis, with its paths into the project resolved where they are now.

    The artifact lives at ``<project>/takes/<take>/analysis/<file>.json`` and
    holds absolute paths, which are re-rooted like a legacy manifest's.
    """
    if take.analysis_path is None:
        raise ValueError("This take has not been analyzed yet.")
    path = Path(take.analysis_path)
    artifact = load_artifact(path)
    if len(path.parents) > 3 and path.parents[2].name == "takes":
        located: dict[str, Any] = _locate_in_artifact(artifact, path.parents[3])
        return located
    return artifact


class ProjectRepository:
    def __init__(self, root: Path) -> None:
        self.root = root.expanduser().resolve()
        self._lock = RLock()

    @property
    def lock(self) -> RLock:
        """Held for any change to the stored projects, moving them included."""
        return self._lock

    def use_root(self, root: Path) -> None:
        with self._lock:
            self.root = root.expanduser().resolve()

    def project_directory(self, project_id: str) -> Path:
        if not PROJECT_ID_PATTERN.fullmatch(project_id):
            raise ProjectNotFoundError(f"Invalid project id: {project_id!r}")
        return self.root / project_id

    @staticmethod
    def _read(path: Path) -> Project:
        project = Project.from_dict(json.loads(path.read_text(encoding="utf-8")))
        directory = path.parent
        return _map_paths(project, lambda value: locate(value, directory))

    def load(self, project_id: str) -> Project:
        with self._lock:
            path = self.project_directory(project_id) / MANIFEST
            try:
                return self._read(path)
            except (FileNotFoundError, json.JSONDecodeError) as error:
                raise ProjectNotFoundError(f"Project not found: {project_id}") from error

    def list(self) -> list[Project]:
        root = self.root
        if not root.is_dir():
            return []
        projects: list[Project] = []
        for path in root.glob(f"*/{MANIFEST}"):
            try:
                projects.append(self._read(path))
            except (OSError, TypeError, ValueError, json.JSONDecodeError):
                continue
        return sorted(projects, key=lambda project: project.updated_at, reverse=True)

    def delete(self, project_id: str) -> None:
        with self._lock:
            directory = self.project_directory(project_id)
            try:
                # Removing the manifest first drops the project from the list at
                # once, even if the media below fails to delete.
                (directory / MANIFEST).unlink()
            except FileNotFoundError as error:
                raise ProjectNotFoundError(f"Project not found: {project_id}") from error
            shutil.rmtree(directory)

    def save(self, project: Project) -> Project:
        with self._lock:
            directory = self.project_directory(project.id)
            directory.mkdir(parents=True, exist_ok=True)
            stored = _map_paths(project, lambda value: portable(value, directory))
            path = directory / MANIFEST
            temporary = directory / f"{MANIFEST}.tmp"
            temporary.write_text(
                json.dumps(stored.to_dict(), indent=2, allow_nan=False) + "\n",
                encoding="utf-8",
            )
            temporary.replace(path)
            return project

    def update(self, project_id: str, transform: Callable[[Project], Project]) -> Project:
        with self._lock:
            return self.save(transform(self.load(project_id)))

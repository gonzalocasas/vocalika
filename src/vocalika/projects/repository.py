from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path
from threading import RLock

from vocalika.projects.models import Project

PROJECT_ID_PATTERN = re.compile(r"^[a-f0-9]{32}$")


class ProjectNotFoundError(LookupError):
    pass


class ProjectRepository:
    def __init__(self, root: Path) -> None:
        self.root = root.expanduser().resolve()
        self._lock = RLock()

    def project_directory(self, project_id: str) -> Path:
        if not PROJECT_ID_PATTERN.fullmatch(project_id):
            raise ProjectNotFoundError(f"Invalid project id: {project_id!r}")
        return self.root / project_id

    def load(self, project_id: str) -> Project:
        with self._lock:
            path = self.project_directory(project_id) / "project.json"
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (FileNotFoundError, json.JSONDecodeError) as error:
                raise ProjectNotFoundError(f"Project not found: {project_id}") from error
            return Project.from_dict(payload)

    def list(self) -> list[Project]:
        if not self.root.is_dir():
            return []
        projects: list[Project] = []
        for path in self.root.glob("*/project.json"):
            try:
                projects.append(Project.from_dict(json.loads(path.read_text(encoding="utf-8"))))
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
        return sorted(projects, key=lambda project: project.updated_at, reverse=True)

    def save(self, project: Project) -> Project:
        with self._lock:
            directory = self.project_directory(project.id)
            directory.mkdir(parents=True, exist_ok=True)
            path = directory / "project.json"
            temporary = directory / "project.json.tmp"
            temporary.write_text(
                json.dumps(project.to_dict(), indent=2, allow_nan=False) + "\n",
                encoding="utf-8",
            )
            temporary.replace(path)
            return project

    def update(self, project_id: str, transform: Callable[[Project], Project]) -> Project:
        with self._lock:
            return self.save(transform(self.load(project_id)))

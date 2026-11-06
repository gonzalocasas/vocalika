"""Where Vocalika keeps its projects, and moving them somewhere else.

The data folder is chosen by the singer (on first start, and later in
Settings) and recorded in a small settings file in the OS's per-user config
folder, so it holds across restarts and does not depend on the folder the
server was started from. Projects live in ``<data folder>/projects/<id>/``.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Any

import platformdirs

from vocalika.projects.repository import MANIFEST, PROJECT_ID_PATTERN, ProjectRepository

PROJECTS_FOLDER = "projects"


class StorageError(ValueError):
    pass


def default_settings_path() -> Path:
    """The per-user settings file. ``VOCALIKA_SETTINGS`` points elsewhere (tests, a 2nd setup)."""
    override = os.environ.get("VOCALIKA_SETTINGS")
    if override:
        return Path(override).expanduser()
    return platformdirs.user_config_path("vocalika", appauthor=False) / "settings.json"


def suggested_data_directory() -> Path:
    """A folder the singer can find again: their Music folder, not a hidden app folder."""
    return Path(platformdirs.user_music_dir()) / "Vocalika"


def projects_directory(data_directory: Path) -> Path:
    return data_directory / PROJECTS_FOLDER


def _project_folders(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    return sorted(
        child
        for child in directory.iterdir()
        if child.is_dir()
        and PROJECT_ID_PATTERN.fullmatch(child.name)
        and (child / MANIFEST).is_file()
    )


def normalize(value: str | Path) -> Path:
    text = str(value).strip()
    if not text:
        raise StorageError("Choose a folder.")
    path = Path(text).expanduser()
    if not path.is_absolute():
        raise StorageError("Use a full folder path, such as ~/Music/Vocalika.")
    return path.resolve()


def describe(path: Path) -> dict[str, Any]:
    """What choosing ``path`` as the data folder would mean."""
    existing = path
    while not existing.exists() and existing != existing.parent:
        existing = existing.parent
    if path.exists() and not path.is_dir():
        problem: str | None = "That is a file, not a folder."
    elif not os.access(existing, os.W_OK):
        problem = "Vocalika cannot write to that folder."
    else:
        problem = None
    return {
        "path": str(path),
        "exists": path.is_dir(),
        "project_count": len(_project_folders(projects_directory(path))),
        "problem": problem,
    }


@dataclass
class StorageSettings:
    """The data folder in use, and the settings file that remembers it.

    ``settings_path`` None keeps the choice in memory only (tests, or a caller
    that fixes the folder). ``fallback`` is used until a folder is chosen.
    """

    settings_path: Path | None
    fallback: Path
    _chosen: Path | None = None

    def __post_init__(self) -> None:
        self.fallback = self.fallback.expanduser().resolve()
        if self.settings_path is None:
            self._chosen = self.fallback
            return
        try:
            payload = json.loads(self.settings_path.read_text(encoding="utf-8"))
            self._chosen = Path(payload["data_directory"]).expanduser().resolve()
        except (OSError, ValueError, KeyError, TypeError):
            self._chosen = None

    @property
    def configured(self) -> bool:
        return self._chosen is not None

    @property
    def data_directory(self) -> Path:
        return self._chosen or self.fallback

    def choose(self, directory: Path) -> None:
        if self.settings_path is not None:
            self.settings_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.settings_path.with_name(f"{self.settings_path.name}.tmp")
            temporary.write_text(
                json.dumps({"data_directory": str(directory)}, indent=2) + "\n",
                encoding="utf-8",
            )
            temporary.replace(self.settings_path)
        self._chosen = directory


def _same_device(first: Path, second: Path) -> bool:
    existing = second
    while not existing.exists():
        existing = existing.parent
    return first.stat().st_dev == existing.stat().st_dev


def move_projects(source: Path, target: Path) -> int:
    """Move every project from one projects folder to another; returns how many.

    Nothing is removed from ``source`` until every project has arrived, so a
    failure part way (a full disk, an unplugged drive) leaves the projects
    where they were. On one disk the move is a rename and takes no time.
    """
    folders = _project_folders(source)
    if source == target:
        return 0
    if target.is_relative_to(source) or source.is_relative_to(target):
        raise StorageError("The new folder cannot be inside the current one, or contain it.")
    clashes = [folder.name for folder in folders if (target / folder.name).exists()]
    if clashes:
        raise StorageError(
            f"The new folder already has {len(clashes)} of these projects. "
            "Use that folder as it is, or choose an empty one."
        )
    target.mkdir(parents=True, exist_ok=True)
    if not folders:
        return 0
    if _same_device(source, target):
        moved: list[tuple[Path, Path]] = []
        try:
            for folder in folders:
                destination = target / folder.name
                folder.rename(destination)
                moved.append((destination, folder))
        except OSError:
            for destination, original in reversed(moved):
                destination.rename(original)
            raise
        return len(folders)

    staging = target / f".incoming-{uuid.uuid4().hex}"
    try:
        for folder in folders:
            shutil.copytree(folder, staging / folder.name)
        for folder in folders:
            (staging / folder.name).rename(target / folder.name)
    except OSError:
        # The originals are untouched; drop whatever copies already landed
        # (none of them existed before: clashes were refused above).
        for folder in folders:
            shutil.rmtree(target / folder.name, ignore_errors=True)
        raise
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    for folder in folders:
        # Every copy is in place; a leftover original is only wasted space.
        shutil.rmtree(folder, ignore_errors=True)
    return len(folders)


class StorageManager:
    """Switches the live repository between data folders."""

    def __init__(
        self,
        settings: StorageSettings,
        repository: ProjectRepository,
        *,
        is_busy: Callable[[], bool] = lambda: False,
    ) -> None:
        self.settings = settings
        self.repository = repository
        self.is_busy = is_busy
        self._lock = RLock()

    def status(self) -> dict[str, Any]:
        current = self.settings.data_directory
        count = len(_project_folders(projects_directory(current)))
        # Before anything is chosen, projects already in the start-up folder
        # are the singer's existing library: offer to keep them there.
        suggested = current if self.settings.configured or count else suggested_data_directory()
        return {
            "configured": self.settings.configured,
            "data_directory": str(current),
            "project_count": count,
            "suggested_directory": str(suggested),
            "can_browse": folder_picker_available(),
        }

    def relocate(self, value: str | Path, *, move: bool) -> dict[str, Any]:
        target = normalize(value)
        problem = describe(target)["problem"]
        if problem:
            raise StorageError(problem)
        with self._lock, self.repository.lock:
            if self.is_busy():
                raise StorageError(
                    "Wait for the song or take being processed to finish, then try again."
                )
            current = projects_directory(self.settings.data_directory)
            new = projects_directory(target)
            if move:
                move_projects(current, new)
            new.mkdir(parents=True, exist_ok=True)
            self.settings.choose(target)
            self.repository.use_root(new)
        return self.status()


def folder_picker_available() -> bool:
    system = platform.system()
    return (system == "Darwin" and shutil.which("osascript") is not None) or (
        system == "Windows" and shutil.which("powershell") is not None
    )


def pick_folder(start: Path | None = None) -> Path | None:
    """Ask the OS for a folder with its own dialog; None when cancelled.

    The server runs on the singer's own machine, so the native dialog is the
    one place a real path can come from: a browser page only ever sees a
    folder's name, never where it is.
    """
    system = platform.system()
    prompt = "Choose where Vocalika keeps your songs and recordings"
    if system == "Darwin":
        script = f'POSIX path of (choose folder with prompt "{prompt}"'
        if start is not None and start.is_dir():
            script += f' default location POSIX file "{start}"'
        script += ")"
        result = subprocess.run(
            ["osascript", "-e", script], capture_output=True, text=True, check=False
        )
    elif system == "Windows":
        script = (
            "Add-Type -AssemblyName System.Windows.Forms;"
            "$d = New-Object System.Windows.Forms.FolderBrowserDialog;"
            f"$d.Description = '{prompt}';"
            "$d.ShowNewFolderButton = $true;"
            "$top = New-Object System.Windows.Forms.Form -Property @{TopMost=$true};"
            "if ($d.ShowDialog($top) -eq 'OK') { $d.SelectedPath }"
        )
        result = subprocess.run(
            ["powershell", "-NoProfile", "-STA", "-Command", script],
            capture_output=True,
            text=True,
            check=False,
        )
    else:
        raise StorageError("Type the folder path instead.")
    chosen = result.stdout.strip()
    return Path(chosen).resolve() if result.returncode == 0 and chosen else None

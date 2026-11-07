"""What changes when Vocalika runs inside the desktop app.

The desktop launcher sets ``VOCALIKA_DESKTOP=1`` for the server it starts.
The page and the server then share one machine and one person, so the
server can do what a browser page cannot: put a file in a real folder and
show it in Finder or Explorer.
"""

from __future__ import annotations

import contextlib
import os
import platform
import shutil
import subprocess
from pathlib import Path

import platformdirs


def is_desktop() -> bool:
    return os.environ.get("VOCALIKA_DESKTOP") == "1"


def downloads_directory() -> Path:
    """Where exports go: the Downloads folder, as a browser download would."""
    return Path(platformdirs.user_downloads_dir())


def free_path(directory: Path, filename: str) -> Path:
    """``filename`` in ``directory``, numbered like a browser would if it is taken."""
    candidate = directory / filename
    stem, suffix = candidate.stem, candidate.suffix
    number = 2
    while candidate.exists():
        candidate = directory / f"{stem} ({number}){suffix}"
        number += 1
    return candidate


def save_copy(source: Path, filename: str, directory: Path | None = None) -> Path:
    directory = directory or downloads_directory()
    directory.mkdir(parents=True, exist_ok=True)
    destination = free_path(directory, filename)
    shutil.copyfile(source, destination)
    return destination


def reveal(path: Path) -> None:
    """Show ``path`` selected in the system file manager (best effort)."""
    system = platform.system()
    if system == "Darwin":
        command = ["open", "-R", str(path)]
    elif system == "Windows":
        # Explorer takes "/select,<path>" as one argument, and exits with 1
        # even when it worked, so the exit code says nothing.
        command = ["explorer", f"/select,{path}"]
    else:
        command = ["xdg-open", str(path.parent)]
    # The file is saved either way, and the page says where.
    with contextlib.suppress(OSError):
        subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

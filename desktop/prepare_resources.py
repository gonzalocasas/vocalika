"""Gather what the desktop launcher installs on first run into src-tauri/resources/.

The installer carries no Python environment. It carries the means to build
one reproducibly on the user's machine:

* ``uv``             - the installer that builds the environment;
* ``requirements.txt`` - ``uv.lock`` exported with hashes (the real-input
  extra included, dev tools excluded), so every machine gets the exact
  versions the repository is tested with;
* the Vocalika wheel  - the app itself, with the built web UI inside;
* ``bin/ffmpeg`` and ``bin/ffprobe`` - put on the server's PATH.

Run from desktop/: ``python3 prepare_resources.py``.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

DESKTOP = Path(__file__).resolve().parent
REPOSITORY = DESKTOP.parent
RESOURCES = DESKTOP / "src-tauri" / "resources"
EXE = ".exe" if sys.platform == "win32" else ""


def run(*command: str, cwd: Path = REPOSITORY) -> None:
    print("+", " ".join(command), flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def which(name: str, override_variable: str) -> Path:
    override = os.environ.get(override_variable)
    found = override or shutil.which(name)
    if not found:
        sys.exit(f"{name} not found; put it on PATH or set {override_variable}.")
    return Path(found).resolve()


def main() -> None:
    if RESOURCES.exists():
        shutil.rmtree(RESOURCES)
    (RESOURCES / "bin").mkdir(parents=True)

    run("npm", "run", "build", cwd=REPOSITORY / "frontend")
    run("uv", "build", "--wheel", "--out-dir", str(RESOURCES))
    run(
        "uv", "export", "--frozen", "--no-dev", "--extra", "real-input",
        "--no-emit-project", "--format", "requirements-txt",
        "--output-file", str(RESOURCES / "requirements.txt"),
    )

    # The launcher shells out to this uv, never to one on the user's PATH.
    shutil.copy2(which("uv", "VOCALIKA_UV"), RESOURCES / f"uv{EXE}")

    # SPIKE: copies whatever ffmpeg is on PATH. A Homebrew build links against
    # /opt/homebrew dylibs, so it only works on machines that have them. A
    # release needs static ffmpeg/ffprobe builds per platform (see the notes).
    ffmpeg_dir = os.environ.get("VOCALIKA_FFMPEG_DIR")
    for tool in ("ffmpeg", "ffprobe"):
        source = Path(ffmpeg_dir) / f"{tool}{EXE}" if ffmpeg_dir else which(tool, "_unused")
        target = RESOURCES / "bin" / f"{tool}{EXE}"
        shutil.copy2(source, target)
        # Homebrew installs these read-only; Tauri must be able to overwrite
        # its bundled copy on the next build.
        target.chmod(0o755)

    # One stamp for "this installer's environment": any change to the locked
    # dependencies or the app wheel makes the launcher rebuild on next start.
    digest = hashlib.sha256()
    for path in sorted(RESOURCES.glob("*.whl")) + [RESOURCES / "requirements.txt"]:
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    (RESOURCES / "stamp.txt").write_text(digest.hexdigest() + "\n")
    print(f"Resources ready in {RESOURCES}")


if __name__ == "__main__":
    main()

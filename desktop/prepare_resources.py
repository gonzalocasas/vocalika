"""Gather what the desktop launcher installs on first run into src-tauri/resources/.

The installer carries no Python environment. It carries the means to build
one reproducibly on the user's machine:

* ``uv``             - the installer that builds the environment;
* ``requirements.txt`` - ``uv.lock`` exported with hashes (the real-input
  extra included, dev tools excluded), so every machine gets the exact
  versions the repository is tested with;
* the Vocalika wheel  - the app itself, with the built web UI inside;
* ``launcher-notices.json`` - the launcher's Rust crates and the bundled uv,
  with their license texts, for the About page.

Audio decoding and encoding go through PyAV, whose wheels carry FFmpeg's
libraries, so no ffmpeg executable is bundled.

Run from desktop/: ``python3 prepare_resources.py``.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
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
    # Resolve the program first: on Windows npm is npm.cmd, which
    # CreateProcess does not find by its bare name.
    program = shutil.which(command[0]) or command[0]
    subprocess.run([program, *command[1:]], cwd=cwd, check=True)


def which(name: str, override_variable: str) -> Path:
    override = os.environ.get(override_variable)
    found = override or shutil.which(name)
    if not found:
        sys.exit(f"{name} not found; put it on PATH or set {override_variable}.")
    return Path(found).resolve()


LICENSE_FILE = re.compile(r"^(LICEN[CS]E|COPYING|NOTICE|COPYRIGHT)", re.IGNORECASE)


def launcher_notices(uv: Path) -> dict[str, object]:
    """The crates compiled into the launcher, and uv, with their license texts.

    Only normal dependencies for this platform count: build scripts and
    macros run while compiling and do not ship. Identical texts (the Apache
    license, mostly) are stored once.
    """
    output = subprocess.run(
        [
            shutil.which("cargo") or "cargo",
            "metadata",
            "--format-version",
            "1",
            "--locked",
            "--filter-platform",
            host_target(),
        ],
        cwd=DESKTOP / "src-tauri",
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    data = json.loads(output)
    by_id = {package["id"]: package for package in data["packages"]}
    nodes = {node["id"]: node for node in data["resolve"]["nodes"]}
    root = data["resolve"]["root"]
    shipped: set[str] = set()
    pending = [root]
    while pending:
        node = nodes[pending.pop()]
        for dependency in node["deps"]:
            normal = any(kind["kind"] is None for kind in dependency["dep_kinds"])
            if normal and dependency["pkg"] not in shipped:
                shipped.add(dependency["pkg"])
                pending.append(dependency["pkg"])

    texts: dict[str, str] = {}

    def keep(text: str) -> str:
        key = hashlib.sha256(text.encode()).hexdigest()[:16]
        texts[key] = text
        return key

    packages = []
    for package in sorted((by_id[i] for i in shipped), key=lambda p: (p["name"], p["version"])):
        folder = Path(package["manifest_path"]).parent
        licenses = [
            {"file": path.name, "text": keep(path.read_text(errors="replace"))}
            for path in sorted(folder.iterdir())
            if path.is_file() and LICENSE_FILE.match(path.name)
        ]
        packages.append(
            {
                "name": package["name"],
                "version": package["version"],
                "license": package.get("license") or "See the license text",
                "url": package.get("repository") or package.get("homepage"),
                "licenses": licenses,
            }
        )
    version = subprocess.run(
        [str(uv), "--version"], check=True, capture_output=True, text=True
    ).stdout.split()[1]
    packages.insert(
        0,
        {
            "name": "uv",
            "version": version,
            "license": "MIT OR Apache-2.0",
            "url": "https://github.com/astral-sh/uv",
            # uv's binary carries no license file; its repository has both.
            "licenses": [],
        },
    )
    return {"packages": packages, "texts": texts}


def host_target() -> str:
    for line in subprocess.run(
        [shutil.which("rustc") or "rustc", "-vV"], check=True, capture_output=True, text=True
    ).stdout.splitlines():
        if line.startswith("host: "):
            return line.removeprefix("host: ")
    sys.exit("rustc -vV did not name the host target.")


def main() -> None:
    if RESOURCES.exists():
        shutil.rmtree(RESOURCES)
    RESOURCES.mkdir(parents=True)

    run("npm", "run", "build", cwd=REPOSITORY / "frontend")
    run("uv", "build", "--wheel", "--out-dir", str(RESOURCES))
    run(
        "uv",
        "export",
        "--frozen",
        "--no-dev",
        "--extra",
        "real-input",
        "--no-emit-project",
        "--format",
        "requirements-txt",
        "--output-file",
        str(RESOURCES / "requirements.txt"),
    )

    # The launcher shells out to this uv, never to one on the user's PATH.
    shutil.copy2(which("uv", "VOCALIKA_UV"), RESOURCES / f"uv{EXE}")
    notices = launcher_notices(RESOURCES / f"uv{EXE}")
    (RESOURCES / "launcher-notices.json").write_text(json.dumps(notices))
    print(f"Listed {len(notices['packages'])} launcher components for the About page.")

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

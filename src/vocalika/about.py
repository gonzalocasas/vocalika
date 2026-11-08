"""What the About page says: the version, and whose work Vocalika runs on.

The open source list is read from what is actually installed, not kept by
hand, so it cannot drift from what ships: the Python packages Vocalika
depends on (directly or not), each with the license files its wheel carries,
and the Python interpreter itself. The desktop launcher adds its own Rust
crates and the bundled uv, gathered when the installer is built (see
``desktop/prepare_resources.py``), through ``VOCALIKA_LAUNCHER_NOTICES``.
"""

from __future__ import annotations

import functools
import json
import os
import platform
import re
import sys
from importlib import metadata
from pathlib import Path
from typing import Any

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

from vocalika import __version__, desktop

_LICENSE_FILE = re.compile(r"(^|/)(LICEN[CS]E|COPYING|NOTICE|COPYRIGHT)[^/]*$", re.IGNORECASE)
_ROOT = "vocalika"
# The extras the app runs with ("dev" is the developer's tools). Their
# packages are listed only when installed, as in the desktop app.
_ROOT_EXTRAS = ("real-input",)


def _license(dist: metadata.Distribution) -> str:
    """A short license name: the SPDX expression, or the best the metadata offers."""
    meta = dist.metadata
    expression = meta.get("License-Expression")
    if expression:
        return expression.strip()
    declared = (meta.get("License") or "").strip()
    # Some packages put the whole license text in this field.
    if declared and "\n" not in declared and len(declared) <= 60 and declared != "UNKNOWN":
        return declared
    classifiers = [
        value.split(" :: ")[-1]
        for value in meta.get_all("Classifier") or []
        if value.startswith("License :: ") and value.count(" :: ") >= 2
    ]
    return ", ".join(classifiers) or "See the license text"


def _homepage(dist: metadata.Distribution) -> str | None:
    meta = dist.metadata
    urls: dict[str, str] = {}
    for entry in meta.get_all("Project-URL") or []:
        label, _, url = entry.partition(",")
        urls[label.strip().lower()] = url.strip()
    for label in ("homepage", "home", "source", "source code", "repository", "documentation"):
        if label in urls:
            return urls[label]
    return meta.get("Home-page") or next(iter(urls.values()), None)


def _installed(name: str) -> metadata.Distribution | None:
    try:
        return metadata.distribution(name)
    except metadata.PackageNotFoundError:
        return None


@functools.cache
def _dependencies() -> tuple[metadata.Distribution, ...]:
    """Every installed distribution Vocalika needs, found from its requirements.

    Walking the requirements, rather than listing everything installed, keeps
    a developer's tools (pytest, ruff) off the page.
    """
    root = _installed(_ROOT)
    if root is None:
        return ()
    found: dict[str, metadata.Distribution] = {}
    # (distribution, the extras requested of it)
    pending: list[tuple[metadata.Distribution, set[str]]] = [(root, set(_ROOT_EXTRAS))]
    while pending:
        dist, extras = pending.pop()
        for line in dist.requires or []:
            requirement = Requirement(line)
            if requirement.marker is not None:
                environments = [{"extra": extra} for extra in extras] or [{"extra": ""}]
                if not any(requirement.marker.evaluate(env) for env in environments):
                    continue
            name = canonicalize_name(requirement.name)
            if name in found or name == _ROOT:
                continue
            dependency = _installed(requirement.name)
            if dependency is None:
                # An extra that is not installed (the browser-only setup).
                continue
            found[name] = dependency
            pending.append((dependency, set(requirement.extras)))
    return tuple(sorted(found.values(), key=lambda dist: dist.metadata["Name"].lower()))


def _python_license_file() -> Path | None:
    base = Path(sys.base_prefix)
    version = f"python{sys.version_info.major}.{sys.version_info.minor}"
    for candidate in (base / "lib" / version / "LICENSE.txt", base / "LICENSE.txt"):
        if candidate.is_file():
            return candidate
    return None


def python_packages() -> list[dict[str, Any]]:
    packages: list[dict[str, Any]] = [
        {
            "name": "Python",
            "version": platform.python_version(),
            "license": "PSF-2.0",
            "url": "https://www.python.org",
        }
    ]
    for dist in _dependencies():
        packages.append(
            {
                "name": dist.metadata["Name"],
                "version": dist.version,
                "license": _license(dist),
                "url": _homepage(dist),
            }
        )
    return packages


def license_texts(name: str) -> list[dict[str, str]]:
    """The license files a Python package installed, as ``{file, text}``.

    Only Vocalika's own dependencies are answered for, so this cannot be
    used to read arbitrary files.
    """
    if name == "Python":
        path = _python_license_file()
        return (
            [{"file": path.name, "text": path.read_text(encoding="utf-8", errors="replace")}]
            if path
            else []
        )
    wanted = canonicalize_name(name)
    for dist in _dependencies():
        if canonicalize_name(dist.metadata["Name"]) != wanted:
            continue
        texts = []
        for file in dist.files or []:
            if ".dist-info" not in str(file) or not _LICENSE_FILE.search(str(file)):
                continue
            path = Path(str(dist.locate_file(file)))
            if path.is_file():
                texts.append(
                    {"file": file.name, "text": path.read_text(encoding="utf-8", errors="replace")}
                )
        if not texts:
            # The license text in the metadata field, where some packages put it.
            declared = (dist.metadata.get("License") or "").strip()
            if "\n" in declared:
                texts.append({"file": "METADATA", "text": declared})
        return texts
    raise KeyError(name)


@functools.cache
def _launcher_file() -> dict[str, Any] | None:
    path = os.environ.get("VOCALIKA_LAUNCHER_NOTICES")
    if not path or not Path(path).is_file():
        return None
    notices: dict[str, Any] = json.loads(Path(path).read_text(encoding="utf-8"))
    return notices


def launcher_packages() -> list[dict[str, Any]] | None:
    """The desktop launcher's own open source parts, when running inside it."""
    notices = _launcher_file()
    if notices is None:
        return None
    return [
        {key: package[key] for key in ("name", "version", "license", "url")}
        for package in notices["packages"]
    ]


def launcher_license_texts(name: str) -> list[dict[str, str]]:
    notices = _launcher_file()
    for package in (notices or {}).get("packages", []):
        if package["name"] == name:
            return [
                {"file": entry["file"], "text": notices["texts"][entry["text"]]}  # type: ignore[index]
                for entry in package["licenses"]
            ]
    raise KeyError(name)


def summary() -> dict[str, Any]:
    return {
        "version": __version__,
        "desktop": desktop.is_desktop(),
        "platform": f"{platform.system()} {platform.machine()}",
        "python_packages": python_packages(),
        "launcher_packages": launcher_packages(),
    }

"""Put the built web UI inside the wheel.

The desktop app installs Vocalika as a wheel into its own environment and
serves the web UI from it, so a wheel without the UI is a broken app. An
editable install (development, CI) serves the repository's frontend/dist
directly and must not depend on it having been built first.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class WebUIBuildHook(BuildHookInterface):  # type: ignore[type-arg]
    PLUGIN_NAME = "custom"

    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        if self.target_name != "wheel" or version == "editable":
            return
        dist = Path(self.root) / "frontend" / "dist"
        if not (dist / "index.html").is_file():
            raise RuntimeError(
                "frontend/dist is missing: run `npm run build` in frontend/ before building "
                "a wheel. The desktop app serves the web UI from inside the wheel."
            )
        build_data["force_include"][str(dist)] = "vocalika/web"

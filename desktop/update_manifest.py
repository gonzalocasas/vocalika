"""Write latest.json, the file installed apps read to find a new release.

The launcher asks
``https://github.com/gonzalocasas/vocalika/releases/latest/download/latest.json``
on start. GitHub answers with this file from the newest release, which
names the version and, per platform, the update bundle's URL and its
signature. The app installs a bundle only if that signature checks out
against the public key built into it.

Run in CI after both platforms have attached their bundles and signatures:
``uv run --no-project update_manifest.py v0.5.0 SIGNATURES_DIR OUTPUT``.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

REPOSITORY = "gonzalocasas/vocalika"

# Updater target -> the release asset holding that platform's update. The
# names are the release workflow's fixed asset names. On Windows the update
# is the installer itself, run without questions; on macOS it is the app
# bundle, tarred.
PLATFORMS = {
    "darwin-aarch64": "Vocalika-macOS-AppleSilicon.app.tar.gz",
    "windows-x86_64": "Vocalika-Windows-x64-setup.exe",
}


def manifest(tag: str, signatures: Path) -> dict[str, object]:
    platforms = {}
    for target, asset in PLATFORMS.items():
        signature = signatures / f"{asset}.sig"
        if not signature.is_file():
            sys.exit(f"Missing {signature.name}: did that platform's build attach it?")
        platforms[target] = {
            "url": f"https://github.com/{REPOSITORY}/releases/download/{tag}/{asset}",
            "signature": signature.read_text().strip(),
        }
    return {
        "version": tag.removeprefix("v"),
        "pub_date": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "platforms": platforms,
    }


def main() -> None:
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    tag, signatures, output = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])
    output.write_text(json.dumps(manifest(tag, signatures), indent=2) + "\n")
    print(output.read_text())


if __name__ == "__main__":
    main()

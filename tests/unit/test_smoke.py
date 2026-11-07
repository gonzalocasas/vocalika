import json
from pathlib import Path

from vocalika import __version__


def test_version_is_the_released_one() -> None:
    # Release Please bumps both together; a mismatch means one was edited by hand.
    manifest = Path(__file__).parents[2] / ".release-please-manifest.json"
    assert __version__ == json.loads(manifest.read_text())["."]

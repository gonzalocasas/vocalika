from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from vocalika.api.app import create_app


def test_analysis_and_audio_are_served_locally(tmp_path: Path) -> None:
    reference = tmp_path / "reference.wav"
    performance = tmp_path / "performance.flac"
    reference.write_bytes(b"reference-audio")
    performance.write_bytes(b"performance-audio")
    artifact_path = tmp_path / "analysis.json"
    artifact_path.write_text(
        json.dumps(
            {
                "schema_version": "0.1.0",
                "reference": {
                    "analysis_audio": str(reference),
                    "source": {"path": str(reference)},
                },
                "performance": {"source": {"path": str(performance)}},
            }
        ),
        encoding="utf-8",
    )
    client = TestClient(create_app(artifact_path))

    assert client.get("/api/health").json() == {"status": "ok"}
    assert client.get("/api/analysis").json()["schema_version"] == "0.1.0"
    assert client.get("/api/audio/reference").content == b"reference-audio"
    assert client.get("/api/audio/performance").content == b"performance-audio"

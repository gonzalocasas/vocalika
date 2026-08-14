from __future__ import annotations

import json
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from vocalika.api.app import create_app


@pytest.mark.anyio
async def test_analysis_and_audio_are_served_locally(tmp_path: Path) -> None:
    reference = tmp_path / "reference.wav"
    performance = tmp_path / "performance.flac"
    original_mix = tmp_path / "original-mix.mp3"
    reference.write_bytes(b"reference-audio")
    performance.write_bytes(b"performance-audio")
    original_mix.write_bytes(b"original-mix-audio")
    artifact_path = tmp_path / "analysis.json"
    artifact_path.write_text(
        json.dumps(
            {
                "schema_version": "0.1.0",
                "reference": {
                    "analysis_audio": str(reference),
                    "source": {"path": str(reference)},
                    "original_mix": {"path": str(original_mix)},
                },
                "performance": {"source": {"path": str(performance)}},
            }
        ),
        encoding="utf-8",
    )
    transport = ASGITransport(app=create_app(artifact_path))

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        assert (await client.get("/api/health")).json() == {"status": "ok"}
        assert (await client.get("/api/analysis")).json()["schema_version"] == "0.1.0"
        assert (await client.get("/api/audio/reference")).content == b"reference-audio"
        assert (await client.get("/api/audio/reference-mix")).content == b"original-mix-audio"
        assert (await client.get("/api/audio/performance")).content == b"performance-audio"


@pytest.mark.anyio
async def test_uploaded_analysis_is_saved_and_becomes_active(tmp_path: Path) -> None:
    initial_reference = tmp_path / "initial.wav"
    initial_performance = tmp_path / "initial.flac"
    initial_reference.write_bytes(b"initial-reference")
    initial_performance.write_bytes(b"initial-performance")
    initial_artifact = tmp_path / "initial.json"
    initial_artifact.write_text(
        json.dumps(
            {
                "schema_version": "0.1.0",
                "reference": {
                    "analysis_audio": str(initial_reference),
                    "source": {"path": str(initial_reference)},
                },
                "performance": {"source": {"path": str(initial_performance)}},
            }
        ),
        encoding="utf-8",
    )
    captured: dict[str, Path | str | bool] = {}

    def fake_analysis_runner(
        reference: str | Path,
        performance: Path,
        output: Path,
        *,
        reference_is_vocal: bool,
    ) -> Path:
        captured.update(
            reference=reference,
            performance=performance,
            reference_is_vocal=reference_is_vocal,
        )
        output.mkdir(parents=True)
        result_path = output / "analysis.json"
        result_path.write_text(
            json.dumps(
                {
                    "schema_version": "0.1.0",
                    "created_at": "test",
                    "reference": {
                        "analysis_audio": str(reference),
                        "source": {"path": str(reference)},
                    },
                    "performance": {"source": {"path": str(performance)}},
                }
            ),
            encoding="utf-8",
        )
        return result_path

    app = create_app(
        initial_artifact,
        uploads_directory=tmp_path / "uploads",
        analyses_directory=tmp_path / "analyses",
        analysis_runner=fake_analysis_runner,
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/analyze",
            data={"reference_is_vocal": "true"},
            files={
                "reference_file": ("my mix.mp3", b"new-reference", "audio/mpeg"),
                "performance_file": ("ableton.flac", b"new-performance", "audio/flac"),
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["analysis_id"]
        assert (await client.get("/api/analysis")).json()["created_at"] == "test"
        assert Path(captured["reference"]).read_bytes() == b"new-reference"
        assert Path(captured["performance"]).read_bytes() == b"new-performance"
        assert captured["reference_is_vocal"] is True


@pytest.mark.anyio
async def test_upload_requires_exactly_one_reference(tmp_path: Path) -> None:
    artifact_path = tmp_path / "analysis.json"
    artifact_path.write_text(
        json.dumps(
            {
                "schema_version": "0.1.0",
                "reference": {"analysis_audio": "missing", "source": {"path": "missing"}},
                "performance": {"source": {"path": "missing"}},
            }
        ),
        encoding="utf-8",
    )
    app = create_app(artifact_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/analyze",
            files={"performance_file": ("take.flac", b"audio", "audio/flac")},
        )

    assert response.status_code == 400
    assert "exactly one reference" in response.json()["detail"]

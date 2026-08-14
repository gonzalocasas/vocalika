from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from vocalika.models.artifact import load_artifact


def create_app(artifact_path: Path, frontend_directory: Path | None = None) -> FastAPI:
    artifact_path = artifact_path.expanduser().resolve()
    artifact = load_artifact(artifact_path)
    app = FastAPI(title="Vocalika", version="0.1.0")

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/analysis")
    def analysis() -> dict[str, Any]:
        return artifact

    @app.get("/api/audio/{kind}", response_class=FileResponse)
    def audio(kind: Literal["reference", "performance", "reference-mix"]) -> FileResponse:
        if kind == "reference":
            candidate = Path(artifact["reference"]["analysis_audio"])
        elif kind == "reference-mix":
            original_mix = artifact["reference"].get("original_mix")
            candidate = Path(
                original_mix["path"] if original_mix else artifact["reference"]["source"]["path"]
            )
        else:
            candidate = Path(artifact["performance"]["source"]["path"])
        if not candidate.is_file():
            raise HTTPException(status_code=404, detail=f"Audio unavailable: {kind}")
        return FileResponse(candidate)

    if frontend_directory is not None and frontend_directory.is_dir():
        app.mount("/", StaticFiles(directory=frontend_directory, html=True), name="frontend")
    return app

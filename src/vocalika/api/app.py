from __future__ import annotations

import asyncio
import re
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any, Literal
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from vocalika.models.artifact import load_artifact
from vocalika.pipeline import run_analysis

AnalysisRunner = Callable[..., Path]
SUPPORTED_UPLOAD_SUFFIXES = {".flac", ".wav", ".mp3", ".m4a"}
MAX_UPLOAD_BYTES = 2 * 1024 * 1024 * 1024


def _safe_upload_name(filename: str | None, role: str) -> str:
    original = Path(filename or f"{role}.audio").name
    suffix = Path(original).suffix.lower()
    if suffix not in SUPPORTED_UPLOAD_SUFFIXES:
        supported = ", ".join(sorted(SUPPORTED_UPLOAD_SUFFIXES))
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported {role} format {suffix or '(none)'}. Use one of: {supported}.",
        )
    stem = re.sub(r"[^\w .()-]+", "_", Path(original).stem, flags=re.UNICODE).strip()
    return f"{role}-{stem or role}{suffix}"


async def _save_upload(upload: UploadFile, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    try:
        with destination.open("wb") as target:
            while chunk := await upload.read(1024 * 1024):
                written += len(chunk)
                if written > MAX_UPLOAD_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail="Audio upload exceeds the 2 GB limit.",
                    )
                target.write(chunk)
    finally:
        await upload.close()


def create_app(
    artifact_path: Path,
    frontend_directory: Path | None = None,
    *,
    uploads_directory: Path | None = None,
    analyses_directory: Path | None = None,
    analysis_runner: AnalysisRunner = run_analysis,
) -> FastAPI:
    artifact_path = artifact_path.expanduser().resolve()
    artifact = load_artifact(artifact_path)
    repository_root = Path(__file__).resolve().parents[3]
    uploads_directory = (uploads_directory or repository_root / "samples" / "uploads").resolve()
    analyses_directory = (
        analyses_directory or repository_root / "analysis-output" / "web"
    ).resolve()
    analysis_lock = asyncio.Lock()
    app = FastAPI(title="Vocalika", version="0.1.0")

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/analysis")
    def current_analysis() -> dict[str, Any]:
        return artifact

    @app.post("/api/analyze")
    async def analyze_uploads(
        performance_file: Annotated[UploadFile, File()],
        reference_file: Annotated[UploadFile | None, File()] = None,
        reference_url: Annotated[str | None, Form()] = None,
        reference_is_vocal: Annotated[bool, Form()] = False,
    ) -> dict[str, Any]:
        nonlocal artifact, artifact_path
        normalized_url = (reference_url or "").strip()
        if bool(reference_file) == bool(normalized_url):
            raise HTTPException(
                status_code=400,
                detail="Provide exactly one reference: a YouTube URL or a local audio file.",
            )
        analysis_id = uuid4().hex
        upload_directory = uploads_directory / analysis_id
        performance_path = upload_directory / _safe_upload_name(
            performance_file.filename,
            "performance",
        )
        await _save_upload(performance_file, performance_path)
        reference_value: str | Path = normalized_url
        if reference_file is not None:
            reference_path = upload_directory / _safe_upload_name(
                reference_file.filename,
                "reference",
            )
            await _save_upload(reference_file, reference_path)
            reference_value = reference_path

        output_directory = analyses_directory / analysis_id
        async with analysis_lock:
            try:
                result_path = await run_in_threadpool(
                    analysis_runner,
                    reference_value,
                    performance_path,
                    output_directory,
                    reference_is_vocal=reference_is_vocal,
                )
                result = load_artifact(result_path)
            except HTTPException:
                raise
            except Exception as error:
                raise HTTPException(status_code=422, detail=str(error)) from error
            artifact_path = result_path
            artifact = result
        return {"analysis_id": analysis_id, "artifact": artifact}

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

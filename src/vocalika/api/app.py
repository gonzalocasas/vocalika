from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response
from starlette.types import Scope

from vocalika.api.projects import create_projects_router
from vocalika.api.uploads import safe_upload_name, save_upload
from vocalika.api.waveform import build_aligned_waveforms
from vocalika.cache.manager import CacheManager
from vocalika.models.artifact import load_artifact
from vocalika.pipeline import run_analysis
from vocalika.projects.repository import ProjectRepository
from vocalika.projects.service import ProjectService

AnalysisRunner = Callable[..., Path]


class SPAStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope: Scope) -> Response:
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as error:
            is_app_route = not path.startswith("api/") and not Path(path).suffix
            if error.status_code != 404 or not is_app_route:
                raise
            return await super().get_response("index.html", scope)


class AnalysisSelection(BaseModel):
    id: str


def create_app(
    artifact_path: Path | None = None,
    frontend_directory: Path | None = None,
    *,
    uploads_directory: Path | None = None,
    analyses_directory: Path | None = None,
    library_directory: Path | None = None,
    analysis_runner: AnalysisRunner = run_analysis,
    projects_directory: Path | None = None,
    cache_directory: Path | None = None,
    project_analysis_runner: AnalysisRunner = run_analysis,
) -> FastAPI:
    repository_root = Path(__file__).resolve().parents[3]
    artifact_path = artifact_path.expanduser().resolve() if artifact_path is not None else None
    artifact = load_artifact(artifact_path) if artifact_path is not None else None
    uploads_directory = (uploads_directory or repository_root / "samples" / "uploads").resolve()
    analyses_directory = (
        analyses_directory or repository_root / "analysis-output" / "web"
    ).resolve()
    library_directory = (library_directory or repository_root / "analysis-output").resolve()
    projects_directory = (
        projects_directory or library_directory / "projects"
    ).expanduser().resolve()
    analysis_lock = asyncio.Lock()
    waveform_lock = asyncio.Lock()
    waveform_cache: tuple[str, dict[str, list[float]]] | None = None
    app = FastAPI(title="Vocalika", version="0.1.0")
    project_cache = (
        CacheManager(cache_directory.expanduser().resolve())
        if cache_directory is not None
        else CacheManager.default()
    )
    app.include_router(
        create_projects_router(
            ProjectService(
                ProjectRepository(projects_directory),
                cache=project_cache,
                analysis_runner=project_analysis_runner,
            )
        )
    )

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/analysis")
    def current_analysis() -> dict[str, Any] | None:
        return artifact

    @app.get("/api/analyses")
    def available_analyses() -> dict[str, list[dict[str, Any]]]:
        results: list[dict[str, Any]] = []
        if not library_directory.is_dir():
            return {"analyses": results}
        for candidate in library_directory.rglob("*.json"):
            resolved = candidate.resolve()
            try:
                resolved.relative_to(library_directory)
                payload = load_artifact(resolved)
            except (OSError, ValueError):
                continue
            reference_path = str(payload.get("reference", {}).get("source", {}).get("path", ""))
            performance_path = str(payload.get("performance", {}).get("source", {}).get("path", ""))
            created_at = (
                payload.get("created_at")
                or datetime.fromtimestamp(
                    resolved.stat().st_mtime,
                    tz=UTC,
                ).isoformat()
            )
            results.append(
                {
                    "id": resolved.relative_to(library_directory).as_posix(),
                    "created_at": created_at,
                    "reference_name": Path(reference_path).name or "Unknown reference",
                    "performance_name": Path(performance_path).name or "Unknown performance",
                }
            )
        results.sort(key=lambda item: str(item["created_at"]), reverse=True)
        return {"analyses": results}

    @app.post("/api/analyses/select")
    async def select_analysis(selection: AnalysisSelection) -> dict[str, Any]:
        nonlocal artifact, artifact_path, waveform_cache
        requested = Path(selection.id)
        if requested.is_absolute():
            raise HTTPException(status_code=400, detail="Invalid analysis id.")
        candidate = (library_directory / requested).resolve()
        try:
            candidate.relative_to(library_directory)
        except ValueError as error:
            raise HTTPException(status_code=400, detail="Invalid analysis id.") from error
        if not candidate.is_file():
            raise HTTPException(status_code=404, detail="Analysis not found.")
        try:
            selected = load_artifact(candidate)
        except (OSError, ValueError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        async with analysis_lock:
            artifact_path = candidate
            artifact = selected
            waveform_cache = None
        return {"artifact": artifact}

    @app.post("/api/analyze")
    async def analyze_uploads(
        performance_file: Annotated[UploadFile, File()],
        reference_file: Annotated[UploadFile | None, File()] = None,
        reference_url: Annotated[str | None, Form()] = None,
        reference_is_vocal: Annotated[bool, Form()] = False,
        isolate_performance: Annotated[bool, Form()] = False,
    ) -> dict[str, Any]:
        nonlocal artifact, artifact_path, waveform_cache
        normalized_url = (reference_url or "").strip()
        if bool(reference_file) == bool(normalized_url):
            raise HTTPException(
                status_code=400,
                detail="Provide exactly one reference: a YouTube URL or a local audio file.",
            )
        analysis_id = uuid4().hex
        upload_directory = uploads_directory / analysis_id
        performance_path = upload_directory / safe_upload_name(
            performance_file.filename,
            "performance",
        )
        await save_upload(performance_file, performance_path)
        reference_value: str | Path = normalized_url
        if reference_file is not None:
            reference_path = upload_directory / safe_upload_name(
                reference_file.filename,
                "reference",
            )
            await save_upload(reference_file, reference_path)
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
                    isolate_performance=isolate_performance,
                )
                result = load_artifact(result_path)
            except HTTPException:
                raise
            except Exception as error:
                raise HTTPException(status_code=422, detail=str(error)) from error
            artifact_path = result_path
            artifact = result
            waveform_cache = None
        return {"analysis_id": analysis_id, "artifact": artifact}

    @app.get("/api/waveforms")
    async def aligned_waveforms() -> dict[str, list[float]]:
        nonlocal waveform_cache
        if artifact is None:
            raise HTTPException(status_code=404, detail="No analysis is selected.")
        cache_key = "|".join(
            (
                str(artifact_path),
                str(artifact.get("created_at", "")),
                str(artifact.get("reference", {}).get("analysis_audio", "")),
                str(artifact.get("performance", {}).get("analysis_audio", "")),
            )
        )
        if waveform_cache is not None and waveform_cache[0] == cache_key:
            return waveform_cache[1]
        async with waveform_lock:
            if waveform_cache is not None and waveform_cache[0] == cache_key:
                return waveform_cache[1]
            try:
                result = await run_in_threadpool(build_aligned_waveforms, artifact)
            except (KeyError, OSError, RuntimeError, ValueError) as error:
                raise HTTPException(
                    status_code=422,
                    detail=f"Unable to prepare aligned waveforms: {error}",
                ) from error
            waveform_cache = (cache_key, result)
            return result

    @app.get("/api/audio/{kind}", response_class=FileResponse)
    def audio(
        kind: Literal["reference", "performance", "reference-mix", "performance-mix"],
    ) -> FileResponse:
        if artifact is None:
            raise HTTPException(status_code=404, detail="No analysis is selected.")
        if kind == "reference":
            candidate = Path(artifact["reference"]["analysis_audio"])
        elif kind == "reference-mix":
            original_mix = artifact["reference"].get("original_mix")
            candidate = Path(
                original_mix["path"] if original_mix else artifact["reference"]["source"]["path"]
            )
        elif kind == "performance-mix":
            original_mix = artifact["performance"].get("original_mix")
            candidate = Path(
                original_mix["path"] if original_mix else artifact["performance"]["source"]["path"]
            )
        else:
            performance = artifact["performance"]
            analysis_source = performance.get("analysis_source")
            candidate = Path(
                analysis_source["path"]
                if performance.get("isolation_applied") and analysis_source
                else performance["source"]["path"]
            )
        if not candidate.is_file():
            raise HTTPException(status_code=404, detail=f"Audio unavailable: {kind}")
        return FileResponse(candidate)

    if frontend_directory is not None and frontend_directory.is_dir():
        app.mount("/", SPAStaticFiles(directory=frontend_directory, html=True), name="frontend")
    return app

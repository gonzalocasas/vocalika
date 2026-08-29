from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from vocalika.api.reference_pitch import build_reference_pitch
from vocalika.api.uploads import safe_upload_name, save_upload
from vocalika.api.waveform import build_aligned_waveforms, build_waveform_envelope
from vocalika.audio.sources import LocalAudioSource
from vocalika.models.artifact import load_artifact
from vocalika.projects.export import (
    ChannelLayout,
    ExportFormat,
    PerformanceChannel,
    ProjectExportService,
)
from vocalika.projects.models import Project, Take
from vocalika.projects.reference_audio import ReferenceAudioService
from vocalika.projects.repository import ProjectNotFoundError
from vocalika.projects.service import ProjectService


class ProjectSettingsUpdate(BaseModel):
    trim_start_seconds: float | None = None
    trim_end_seconds: float | None = None
    transpose_semitones: int | None = None
    lyrics: str | None = None


class ExportRequest(BaseModel):
    take_id: str
    instrumental_db: float = -4.0
    output_format: ExportFormat = "mp3"
    channel_layout: ChannelLayout = "stereo_reference"
    performance_channel: PerformanceChannel = "right"


def _project_payload(project: Project) -> dict[str, Any]:
    return project.to_dict()


def _take(project: Project, take_id: str) -> Take:
    try:
        return next(take for take in project.takes if take.id == take_id)
    except StopIteration as error:
        raise HTTPException(status_code=404, detail="Take not found.") from error


def _artifact_for_take(service: ProjectService, project_id: str, take_id: str) -> dict[str, Any]:
    project = service.repository.load(project_id)
    take = _take(project, take_id)
    if take.analysis_path is None:
        raise HTTPException(status_code=404, detail="This take has not been analyzed yet.")
    try:
        return load_artifact(Path(take.analysis_path))
    except (OSError, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


def create_projects_router(service: ProjectService) -> APIRouter:
    router = APIRouter(prefix="/api/projects", tags=["projects"])
    export_service = ProjectExportService(service.repository)
    reference_audio_service = ReferenceAudioService(service.repository)

    @router.get("")
    def list_projects() -> dict[str, list[dict[str, Any]]]:
        return {"projects": [_project_payload(project) for project in service.repository.list()]}

    @router.post("")
    async def create_project(
        reference_file: Annotated[UploadFile | None, File()] = None,
        reference_url: Annotated[str | None, Form()] = None,
        title: Annotated[str | None, Form()] = None,
        reference_is_vocal: Annotated[bool, Form()] = False,
    ) -> dict[str, Any]:
        normalized_url = (reference_url or "").strip()
        if bool(reference_file) == bool(normalized_url):
            raise HTTPException(
                status_code=400,
                detail="Provide exactly one reference: a YouTube URL or a local audio file.",
            )
        project_id = service.new_id()
        reference_value: str | Path = normalized_url
        if reference_file is not None:
            upload_path = (
                service.repository.project_directory(project_id)
                / "incoming"
                / safe_upload_name(reference_file.filename, "reference")
            )
            await save_upload(reference_file, upload_path)
            reference_value = upload_path
        try:
            project = await run_in_threadpool(
                service.create_project,
                project_id,
                reference_value,
                title=title,
                reference_is_vocal=reference_is_vocal,
            )
        except Exception as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return {"project": _project_payload(project)}

    @router.get("/{project_id}")
    def get_project(project_id: str) -> dict[str, Any]:
        try:
            return {"project": _project_payload(service.repository.load(project_id))}
        except ProjectNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @router.patch("/{project_id}")
    def update_project(project_id: str, update: ProjectSettingsUpdate) -> dict[str, Any]:
        try:
            project = service.update_settings(project_id, **update.model_dump())
        except ProjectNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        return {"project": _project_payload(project)}

    @router.post("/{project_id}/takes")
    async def add_take(
        project_id: str,
        audio_file: Annotated[UploadFile, File()],
        isolate_performance: Annotated[bool, Form()] = False,
        analyze: Annotated[bool, Form()] = True,
        name: Annotated[str | None, Form()] = None,
    ) -> dict[str, Any]:
        try:
            service.repository.load(project_id)
        except ProjectNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        take_id = service.new_id()
        safe_name = safe_upload_name(audio_file.filename, "take")
        suffix = Path(safe_name).suffix
        source_path = (
            service.repository.project_directory(project_id) / "takes" / take_id / f"source{suffix}"
        )
        await save_upload(audio_file, source_path)
        try:
            project, take, artifact = await run_in_threadpool(
                service.add_take,
                project_id,
                source_path,
                name=name or Path(safe_name).stem.removeprefix("take-"),
                isolate_performance=isolate_performance,
                analyze=analyze,
                take_id=take_id,
            )
        except Exception as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return {
            "project": _project_payload(project),
            "take": take.__dict__,
            "artifact": artifact,
        }

    @router.post("/{project_id}/takes/{take_id}/analyze")
    async def analyze_take(project_id: str, take_id: str) -> dict[str, Any]:
        try:
            project, take, artifact = await run_in_threadpool(
                service.analyze_take,
                project_id,
                take_id,
            )
        except (ProjectNotFoundError, LookupError) as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except Exception as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return {
            "project": _project_payload(project),
            "take": take.__dict__,
            "artifact": artifact,
        }

    @router.delete("/{project_id}/takes/{take_id}")
    async def delete_take(project_id: str, take_id: str) -> dict[str, Any]:
        try:
            project = await run_in_threadpool(service.delete_take, project_id, take_id)
        except (ProjectNotFoundError, LookupError) as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except (OSError, ValueError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return {"project": _project_payload(project)}

    @router.get("/{project_id}/takes/{take_id}/analysis")
    def take_analysis(project_id: str, take_id: str) -> dict[str, Any]:
        return {"artifact": _artifact_for_take(service, project_id, take_id)}

    @router.get("/{project_id}/takes/{take_id}/waveforms")
    async def take_waveforms(project_id: str, take_id: str) -> dict[str, list[float]]:
        artifact = _artifact_for_take(service, project_id, take_id)
        try:
            return await run_in_threadpool(build_aligned_waveforms, artifact)
        except (KeyError, OSError, RuntimeError, ValueError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @router.get("/{project_id}/audio/{kind}", response_class=FileResponse)
    def reference_audio(
        project_id: str,
        kind: Literal["mix", "vocal", "instrumental"],
        transpose: int = 0,
    ) -> FileResponse:
        try:
            project = service.repository.load(project_id)
        except ProjectNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        try:
            value = reference_audio_service.resolve(project, kind, transpose)
        except (OSError, RuntimeError, ValueError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        if not value.is_file():
            raise HTTPException(status_code=404, detail=f"Reference {kind} is unavailable.")
        return FileResponse(value)

    @router.get("/{project_id}/waveform/{kind}")
    async def reference_waveform(
        project_id: str,
        kind: Literal["mix", "vocal", "instrumental"],
    ) -> dict[str, list[float]]:
        try:
            reference = service.repository.load(project_id).reference
        except ProjectNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        candidates = {
            "mix": reference.original_path,
            "vocal": reference.vocal_path,
            "instrumental": reference.instrumental_path,
        }
        value = candidates[kind]
        if value is None or not Path(value).is_file():
            raise HTTPException(status_code=404, detail=f"Reference {kind} is unavailable.")
        return await run_in_threadpool(
            build_waveform_envelope,
            Path(value),
            reference.duration_seconds,
        )

    @router.get("/{project_id}/reference/pitch")
    async def reference_pitch(
        project_id: str,
        transpose: int = 0,
    ) -> dict[str, list[float | None]]:
        """Reference contour for the recording screen's live pitch display."""
        try:
            project = service.repository.load(project_id)
        except ProjectNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        try:
            return await run_in_threadpool(
                build_reference_pitch,
                project,
                reference_audio_service,
                service.cache,
                transpose,
            )
        except (OSError, RuntimeError, ValueError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @router.get("/{project_id}/takes/{take_id}/audio/{kind}", response_class=FileResponse)
    def take_audio(
        project_id: str,
        take_id: str,
        kind: Literal["source", "vocal"],
    ) -> FileResponse:
        try:
            project = service.repository.load(project_id)
        except ProjectNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        take = _take(project, take_id)
        candidate = Path(take.source_path)
        if kind == "vocal" and take.analysis_path is not None:
            artifact = load_artifact(Path(take.analysis_path))
            performance = artifact.get("performance", {})
            analysis_source = performance.get("analysis_source") or {}
            playback_candidates = (
                performance.get("analysis_audio"),
                analysis_source.get("path"),
                take.source_path,
            )
            candidate = next(
                (Path(path) for path in playback_candidates if path and Path(path).is_file()),
                Path(take.source_path),
            )
        if not candidate.is_file():
            raise HTTPException(status_code=404, detail="Take audio is unavailable.")
        return FileResponse(candidate)

    @router.get("/{project_id}/takes/{take_id}/waveform")
    async def take_waveform(project_id: str, take_id: str) -> dict[str, list[float]]:
        try:
            take = _take(service.repository.load(project_id), take_id)
        except ProjectNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        waveform_path = Path(take.source_path)
        if take.analysis_path is not None:
            artifact = load_artifact(Path(take.analysis_path))
            waveform_path = Path(
                artifact.get("performance", {}).get("analysis_audio") or take.source_path
            )
        asset = await run_in_threadpool(LocalAudioSource(Path(take.source_path)).acquire)
        if asset.duration_seconds is None:
            raise HTTPException(status_code=422, detail="Take duration is unavailable.")
        return await run_in_threadpool(
            build_waveform_envelope,
            waveform_path,
            asset.duration_seconds,
            maximum_points=100,
        )

    async def create_export(
        project_id: str,
        request: ExportRequest,
        *,
        preview: bool,
    ) -> FileResponse:
        try:
            result = await run_in_threadpool(
                export_service.render,
                project_id,
                request.take_id,
                instrumental_db=request.instrumental_db,
                output_format=request.output_format,
                channel_layout=request.channel_layout,
                performance_channel=request.performance_channel,
                preview=preview,
            )
        except (ProjectNotFoundError, LookupError) as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except (OSError, RuntimeError, ValueError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return FileResponse(
            result.path,
            media_type=result.media_type,
            filename=result.filename,
        )

    @router.post("/{project_id}/exports/preview", response_class=FileResponse)
    async def preview_export(project_id: str, request: ExportRequest) -> FileResponse:
        return await create_export(project_id, request, preview=True)

    @router.post("/{project_id}/exports", response_class=FileResponse)
    async def render_export(project_id: str, request: ExportRequest) -> FileResponse:
        return await create_export(project_id, request, preview=False)

    return router

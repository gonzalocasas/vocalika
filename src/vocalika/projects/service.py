from __future__ import annotations

import shutil
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from vocalika.audio.separation import DemucsVocalSeparator
from vocalika.audio.sources import LocalAudioSource, YouTubeAudioSource, is_youtube_url
from vocalika.cache.manager import CacheManager
from vocalika.models.artifact import load_artifact
from vocalika.pipeline import run_analysis
from vocalika.projects.models import Project, ProjectReference, Take
from vocalika.projects.reference_audio import ReferenceAudioService
from vocalika.projects.repository import ProjectRepository

AnalysisRunner = Callable[..., Path]


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _copy_media(source: Path, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.resolve() != destination.resolve():
        shutil.copy2(source, destination)
    return destination.resolve()


class ProjectService:
    def __init__(
        self,
        repository: ProjectRepository,
        *,
        cache: CacheManager | None = None,
        analysis_runner: AnalysisRunner = run_analysis,
    ) -> None:
        self.repository = repository
        self.cache = cache or CacheManager.default()
        self.analysis_runner = analysis_runner
        self.reference_audio = ReferenceAudioService(repository)

    def new_id(self) -> str:
        return uuid4().hex

    def create_project(
        self,
        project_id: str,
        reference_value: str | Path,
        *,
        title: str | None = None,
        reference_is_vocal: bool = False,
    ) -> Project:
        directory = self.repository.project_directory(project_id)
        if is_youtube_url(str(reference_value)):
            source = YouTubeAudioSource(str(reference_value), self.cache).acquire()
        else:
            source = LocalAudioSource(Path(reference_value)).acquire()
        if source.duration_seconds is None or source.sample_rate is None:
            raise ValueError("Reference audio duration and sample rate could not be determined")

        suffix = source.path.suffix.lower() or ".audio"
        original = _copy_media(source.path, directory / "reference" / f"original{suffix}")
        separation = None
        vocal = original
        instrumental: Path | None = None
        if not reference_is_vocal:
            separation = DemucsVocalSeparator(self.cache).separate(source)
            vocal = _copy_media(separation.vocals, directory / "reference" / "vocals.wav")
            if separation.accompaniment is not None:
                instrumental = _copy_media(
                    separation.accompaniment,
                    directory / "reference" / "instrumental.wav",
                )

        timestamp = _now()
        project = Project(
            id=project_id,
            title=(title or source.title or source.path.stem).strip(),
            created_at=timestamp,
            updated_at=timestamp,
            reference=ProjectReference(
                title=source.title or source.path.stem,
                source_type="youtube" if source.source_url else "local",
                source_url=source.source_url,
                original_path=str(original),
                vocal_path=str(vocal),
                instrumental_path=str(instrumental) if instrumental else None,
                duration_seconds=source.duration_seconds,
                sample_rate=source.sample_rate,
                separation_model=separation.model if separation else None,
                separation_cached=separation.cache_hit if separation else False,
            ),
            trim_end_seconds=source.duration_seconds,
        )
        return self.repository.save(project)

    def update_settings(
        self,
        project_id: str,
        *,
        trim_start_seconds: float | None = None,
        trim_end_seconds: float | None = None,
        transpose_semitones: int | None = None,
        lyrics: str | None = None,
    ) -> Project:
        def apply(project: Project) -> Project:
            start = project.trim_start_seconds if trim_start_seconds is None else trim_start_seconds
            end = project.trim_end_seconds if trim_end_seconds is None else trim_end_seconds
            duration = project.reference.duration_seconds
            start = max(0.0, min(float(start), duration))
            end = max(start, min(float(end if end is not None else duration), duration))
            transpose = (
                project.transpose_semitones
                if transpose_semitones is None
                else max(-12, min(12, int(transpose_semitones)))
            )
            return replace(
                project,
                trim_start_seconds=start,
                trim_end_seconds=end,
                transpose_semitones=transpose,
                lyrics=project.lyrics if lyrics is None else lyrics,
                updated_at=_now(),
            )

        return self.repository.update(project_id, apply)

    def add_take(
        self,
        project_id: str,
        source_path: Path,
        *,
        name: str,
        isolate_performance: bool,
        analyze: bool = True,
        take_id: str | None = None,
    ) -> tuple[Project, Take, dict[str, Any] | None]:
        project = self.repository.load(project_id)
        take_id = take_id or self.new_id()
        suffix = source_path.suffix.lower() or ".audio"
        stored = _copy_media(
            source_path,
            self.repository.project_directory(project_id) / "takes" / take_id / f"source{suffix}",
        )
        take = Take(
            id=take_id,
            name=name.strip() or source_path.stem,
            created_at=_now(),
            source_path=str(stored),
            isolate_performance=isolate_performance,
            reference_transpose_semitones=project.transpose_semitones,
        )
        project = self.repository.update(
            project_id,
            lambda current: replace(
                current,
                takes=(*current.takes, take),
                updated_at=_now(),
            ),
        )
        if not analyze:
            return project, take, None
        return self.analyze_take(project_id, take_id)

    def analyze_take(
        self,
        project_id: str,
        take_id: str,
    ) -> tuple[Project, Take, dict[str, Any]]:
        project = self.repository.load(project_id)
        try:
            take = next(take for take in project.takes if take.id == take_id)
        except StopIteration as error:
            raise LookupError(f"Take not found: {take_id}") from error
        analyzing = replace(take, status="analyzing", error=None)
        project = self._replace_take(project, analyzing)
        output = self.repository.project_directory(project_id) / "takes" / take_id / "analysis"
        try:
            reference_vocal = self.reference_audio.resolve(
                project,
                "vocal",
                take.reference_transpose_semitones,
            )
            reference_mix = self.reference_audio.resolve(
                project,
                "mix",
                take.reference_transpose_semitones,
            )
            result_path = self.analysis_runner(
                reference_vocal,
                Path(take.source_path),
                output,
                reference_is_vocal=True,
                reference_mix_path=reference_mix,
                isolate_performance=take.isolate_performance,
                cache_directory=self.cache.root,
            )
            artifact = load_artifact(result_path)
        except Exception as error:
            self._replace_take(project, replace(analyzing, status="failed", error=str(error)))
            raise
        completed = replace(
            analyzing,
            status="analyzed",
            analysis_path=str(result_path),
            analysis_summary=artifact.get("comparison", {}).get("summary"),
        )
        project = self._replace_take(project, completed)
        return project, completed, artifact

    def delete_take(self, project_id: str, take_id: str) -> Project:
        project = self.repository.load(project_id)
        try:
            next(take for take in project.takes if take.id == take_id)
        except StopIteration as error:
            raise LookupError(f"Take not found: {take_id}") from error

        takes_directory = (self.repository.project_directory(project_id) / "takes").resolve()
        take_directory = (takes_directory / take_id).resolve()
        if take_directory.parent != takes_directory:
            raise ValueError("Invalid take id")
        if take_directory.exists():
            shutil.rmtree(take_directory)

        return self.repository.update(
            project_id,
            lambda current: replace(
                current,
                takes=tuple(take for take in current.takes if take.id != take_id),
                updated_at=_now(),
            ),
        )

    def _replace_take(self, project: Project, replacement: Take) -> Project:
        return self.repository.update(
            project.id,
            lambda current: replace(
                current,
                takes=tuple(
                    replacement if take.id == replacement.id else take for take in current.takes
                ),
                updated_at=_now(),
            ),
        )

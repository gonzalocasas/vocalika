from __future__ import annotations

import math
import subprocess
from pathlib import Path
from typing import Literal
from uuid import uuid4

from vocalika.projects.models import Project
from vocalika.projects.repository import ProjectRepository

ReferenceAudioKind = Literal["mix", "vocal", "instrumental"]


class ReferenceAudioService:
    """Resolve original or cached, duration-preserving transposed project audio."""

    def __init__(self, repository: ProjectRepository) -> None:
        self.repository = repository

    def resolve(
        self,
        project: Project,
        kind: ReferenceAudioKind,
        semitones: int,
    ) -> Path:
        source_value = {
            "mix": project.reference.original_path,
            "vocal": project.reference.vocal_path,
            "instrumental": project.reference.instrumental_path,
        }[kind]
        if source_value is None:
            raise ValueError(f"Reference {kind} is unavailable")
        source = Path(source_value)
        steps = max(-12, min(12, int(semitones)))
        if steps == 0:
            return source

        destination = (
            self.repository.project_directory(project.id)
            / "reference"
            / "transposed"
            / f"{kind}_{steps:+d}.flac"
        )
        if destination.is_file():
            return destination
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.stem}-{uuid4().hex}.flac")
        ratio = transpose_ratio(steps)
        sample_rate = project.reference.sample_rate
        audio_filter = (
            f"asetrate={sample_rate}*{ratio:.12f},aresample={sample_rate},atempo={1.0 / ratio:.12f}"
        )
        try:
            subprocess.run(
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-y",
                    "-i",
                    str(source),
                    "-map",
                    "0:a:0",
                    "-af",
                    audio_filter,
                    "-c:a",
                    "flac",
                    "-compression_level",
                    "5",
                    str(temporary),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            if not temporary.is_file() or temporary.stat().st_size == 0:
                raise RuntimeError("Transposed audio renderer produced no output")
            temporary.replace(destination)
        except (FileNotFoundError, subprocess.CalledProcessError) as error:
            detail = getattr(error, "stderr", "") or str(error)
            raise RuntimeError(f"Unable to transpose reference audio: {detail.strip()}") from error
        finally:
            temporary.unlink(missing_ok=True)
        return destination


def transpose_ratio(semitones: int) -> float:
    return math.pow(2.0, semitones / 12.0)

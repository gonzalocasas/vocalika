from __future__ import annotations

import math
import subprocess
from pathlib import Path
from typing import Literal
from uuid import uuid4

from vocalika.projects.models import Project
from vocalika.projects.repository import ProjectRepository

ReferenceAudioKind = Literal["mix", "vocal", "instrumental"]


def _source_sample_rate(path: Path, fallback: int) -> int:
    """The sample rate of the file about to be transposed.

    `asetrate` reinterprets a stream as if it had a different rate, so it has
    to be given the rate the file actually has. The project records the rate of
    the *original* download, but the separated stems are written by demucs at
    its own rate -- 44.1 kHz against a 48 kHz source, in every project here.
    Feeding the declared rate stretched transposed audio by the ratio between
    them, leaving it 8.8% fast and short of the requested transposition.
    """
    try:
        probe = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "a:0",
                "-show_entries",
                "stream=sample_rate",
                "-of",
                "csv=p=0",
                str(path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        rate = int(probe.stdout.strip().splitlines()[0])
    except (FileNotFoundError, subprocess.CalledProcessError, ValueError, IndexError):
        return fallback
    return rate if rate > 0 else fallback


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
        sample_rate = _source_sample_rate(source, project.reference.sample_rate)
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

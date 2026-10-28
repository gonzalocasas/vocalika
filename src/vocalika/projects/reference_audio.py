from __future__ import annotations

import math
import subprocess
from pathlib import Path
from typing import Literal
from uuid import uuid4

from vocalika.projects.models import Project
from vocalika.projects.repository import ProjectRepository

ReferenceAudioKind = Literal["mix", "vocal", "instrumental"]


def _probe(path: Path, entries: str) -> str | None:
    """The first value ffprobe reports for `entries`, or None when it cannot say."""
    try:
        probe = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "a:0",
                "-show_entries",
                entries,
                "-of",
                "csv=p=0",
                str(path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        return probe.stdout.strip().splitlines()[0]
    except (FileNotFoundError, subprocess.CalledProcessError, IndexError):
        return None


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
        rate = int(_probe(path, "stream=sample_rate") or "")
    except ValueError:
        return fallback
    return rate if rate > 0 else fallback


def _duration_seconds(path: Path) -> float | None:
    try:
        return float(_probe(path, "format=duration") or "")
    except ValueError:
        return None


def _keeps_duration(rendered: Path, source: Path) -> bool:
    """Whether a cached transposition is as long as the audio it came from.

    Transposition preserves duration, so a cached file that differs was
    rendered by a broken pipeline -- the stems made before the sample-rate fix
    above play 8.8% short and sharp -- and has to be rendered again. A file
    whose length cannot be read is kept rather than re-rendered on every call.
    """
    rendered_seconds = _duration_seconds(rendered)
    source_seconds = _duration_seconds(source)
    if rendered_seconds is None or not source_seconds:
        return True
    return abs(rendered_seconds - source_seconds) <= 0.01 * source_seconds


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
        if destination.is_file() and _keeps_duration(destination, source):
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

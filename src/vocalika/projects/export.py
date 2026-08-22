from __future__ import annotations

import math
import subprocess
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal

import numpy as np
import soundfile as sf
from numpy.typing import NDArray
from scipy.signal import resample_poly

from vocalika.models.artifact import load_artifact
from vocalika.projects.models import Project, Take
from vocalika.projects.reference_audio import ReferenceAudioService
from vocalika.projects.repository import ProjectRepository

FloatAudio = NDArray[np.float32]
ExportFormat = Literal["mp3", "wav", "flac"]


@dataclass(frozen=True)
class ExportResult:
    path: Path
    filename: str
    media_type: str


def _read_audio(path: Path, target_sample_rate: int) -> FloatAudio:
    try:
        audio, sample_rate = sf.read(path, dtype="float32", always_2d=True)
    except (OSError, RuntimeError, sf.LibsndfileError):
        with TemporaryDirectory(prefix="vocalika-export-") as raw:
            decoded = Path(raw) / "decoded.wav"
            try:
                subprocess.run(
                    [
                        "ffmpeg",
                        "-v",
                        "error",
                        "-y",
                        "-i",
                        str(path),
                        "-map",
                        "0:a:0",
                        "-ar",
                        str(target_sample_rate),
                        "-c:a",
                        "pcm_f32le",
                        str(decoded),
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                )
            except (FileNotFoundError, subprocess.CalledProcessError) as error:
                detail = getattr(error, "stderr", "") or str(error)
                raise RuntimeError(f"Unable to decode {path.name}: {detail.strip()}") from error
            audio, sample_rate = sf.read(decoded, dtype="float32", always_2d=True)
    if sample_rate == target_sample_rate:
        return np.asarray(audio, dtype=np.float32)
    divisor = math.gcd(sample_rate, target_sample_rate)
    channels = [
        resample_poly(audio[:, channel], target_sample_rate // divisor, sample_rate // divisor)
        for channel in range(audio.shape[1])
    ]
    return np.asarray(np.column_stack(channels), dtype=np.float32)


def _take_vocal_path(take: Take) -> Path:
    if take.analysis_path is None:
        return Path(take.source_path)
    artifact = load_artifact(Path(take.analysis_path))
    performance = artifact["performance"]
    source = performance.get("analysis_source") or performance.get("source")
    return Path(source["path"])


def _alignment_map(take: Take) -> tuple[NDArray[np.float64], NDArray[np.float64]] | None:
    if take.analysis_path is None:
        return None
    artifact = load_artifact(Path(take.analysis_path))
    frames = artifact["comparison"]["frames"]
    reference = np.asarray(frames["reference_time"], dtype=np.float64)
    performance = np.asarray(frames["performance_time"], dtype=np.float64)
    finite = np.isfinite(reference) & np.isfinite(performance)
    reference = reference[finite]
    performance = performance[finite]
    if reference.size < 2:
        return None
    unique_reference = np.unique(reference)
    mapped_performance = np.asarray(
        [np.median(performance[reference == time]) for time in unique_reference],
        dtype=np.float64,
    )
    return unique_reference, mapped_performance


def _warp_take(
    take_audio: FloatAudio,
    sample_rate: int,
    reference_times: NDArray[np.float64],
    mapping: tuple[NDArray[np.float64], NDArray[np.float64]] | None,
    trim_start: float,
) -> FloatAudio:
    if mapping is None:
        performance_times = reference_times - trim_start
    else:
        performance_times = np.interp(
            reference_times,
            mapping[0],
            mapping[1],
            left=np.nan,
            right=np.nan,
        )
    positions = performance_times * sample_rate
    source_positions = np.arange(take_audio.shape[0], dtype=np.float64)
    result = np.zeros((reference_times.size, take_audio.shape[1]), dtype=np.float32)
    valid = np.isfinite(positions)
    for channel in range(take_audio.shape[1]):
        result[valid, channel] = np.interp(
            positions[valid],
            source_positions,
            take_audio[:, channel],
            left=0.0,
            right=0.0,
        )
    return result


def _match_channels(audio: FloatAudio, channels: int) -> FloatAudio:
    if audio.shape[1] == channels:
        return audio
    if audio.shape[1] == 1:
        return np.repeat(audio, channels, axis=1)
    if channels == 1:
        return np.asarray(
            np.mean(audio, axis=1, keepdims=True, dtype=np.float32),
            dtype=np.float32,
        )
    return audio[:, :channels]


def _safe_slug(value: str) -> str:
    slug = "".join(character.lower() if character.isalnum() else "-" for character in value)
    return "-".join(part for part in slug.split("-") if part) or "vocalika"


class ProjectExportService:
    def __init__(self, repository: ProjectRepository, *, sample_rate: int = 44_100) -> None:
        self.repository = repository
        self.sample_rate = sample_rate
        self.reference_audio = ReferenceAudioService(repository)

    def render(
        self,
        project_id: str,
        take_id: str,
        *,
        instrumental_db: float = -4.0,
        output_format: ExportFormat = "mp3",
        preview: bool = False,
    ) -> ExportResult:
        project = self.repository.load(project_id)
        take = self._take(project, take_id)
        if project.reference.instrumental_path is None:
            raise ValueError("This project does not have an instrumental stem")
        trim_start = project.trim_start_seconds
        trim_end = project.trim_end_seconds or project.reference.duration_seconds
        if trim_end <= trim_start:
            raise ValueError("Project trim range is empty")

        instrumental_path = self.reference_audio.resolve(
            project,
            "instrumental",
            take.reference_transpose_semitones,
        )
        instrumental = _read_audio(instrumental_path, self.sample_rate)
        start_sample = round(trim_start * self.sample_rate)
        output_samples = round((trim_end - trim_start) * self.sample_rate)
        instrumental_segment = instrumental[start_sample : start_sample + output_samples]
        if instrumental_segment.shape[0] < output_samples:
            instrumental_segment = np.pad(
                instrumental_segment,
                ((0, output_samples - instrumental_segment.shape[0]), (0, 0)),
            )

        take_audio = _read_audio(_take_vocal_path(take), self.sample_rate)
        reference_times = (
            trim_start + np.arange(output_samples, dtype=np.float64) / self.sample_rate
        )
        take_segment = _warp_take(
            take_audio,
            self.sample_rate,
            reference_times,
            _alignment_map(take),
            trim_start,
        )
        channels = max(instrumental_segment.shape[1], take_segment.shape[1])
        instrumental_segment = _match_channels(instrumental_segment, channels)
        take_segment = _match_channels(take_segment, channels)
        gain = float(10.0 ** (np.clip(instrumental_db, -24.0, 6.0) / 20.0))
        mix = take_segment + instrumental_segment * gain
        peak = float(np.max(np.abs(mix))) if mix.size else 0.0
        if peak > 0.98:
            mix *= 0.98 / peak

        if preview:
            mix = self._loudest_excerpt(mix, seconds=20.0)
            output_format = "wav"
        output_directory = (
            self.repository.project_directory(project_id) / "takes" / take_id / "exports"
        )
        output_directory.mkdir(parents=True, exist_ok=True)
        stem = f"{_safe_slug(project.title)}_{_safe_slug(take.name)}"
        filename = f"{stem}_{'preview' if preview else 'mix'}.{output_format}"
        destination = output_directory / filename
        self._write(mix, destination, output_format)
        media_types = {"mp3": "audio/mpeg", "wav": "audio/wav", "flac": "audio/flac"}
        return ExportResult(destination, filename, media_types[output_format])

    @staticmethod
    def _take(project: Project, take_id: str) -> Take:
        try:
            return next(take for take in project.takes if take.id == take_id)
        except StopIteration as error:
            raise LookupError(f"Take not found: {take_id}") from error

    def _loudest_excerpt(self, audio: FloatAudio, *, seconds: float) -> FloatAudio:
        length = min(audio.shape[0], round(seconds * self.sample_rate))
        if audio.shape[0] <= length:
            return audio
        mono_energy = np.mean(np.square(audio, dtype=np.float64), axis=1)
        cumulative = np.concatenate(([0.0], np.cumsum(mono_energy)))
        step = max(1, self.sample_rate // 5)
        starts = np.arange(0, audio.shape[0] - length + 1, step)
        energies = cumulative[starts + length] - cumulative[starts]
        start = int(starts[int(np.argmax(energies))])
        return audio[start : start + length]

    def _write(self, audio: FloatAudio, destination: Path, output_format: ExportFormat) -> None:
        if output_format in {"wav", "flac"}:
            sf.write(destination, audio, self.sample_rate)
            return
        intermediate = destination.with_suffix(".source.wav")
        sf.write(intermediate, audio, self.sample_rate, subtype="PCM_16")
        try:
            subprocess.run(
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-y",
                    "-i",
                    str(intermediate),
                    "-codec:a",
                    "libmp3lame",
                    "-q:a",
                    "2",
                    str(destination),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
        except (FileNotFoundError, subprocess.CalledProcessError) as error:
            detail = getattr(error, "stderr", "") or str(error)
            raise RuntimeError(f"MP3 export failed: {detail.strip()}") from error
        finally:
            intermediate.unlink(missing_ok=True)

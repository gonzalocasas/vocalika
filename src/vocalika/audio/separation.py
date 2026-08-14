from __future__ import annotations

import json
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from importlib.metadata import version
from pathlib import Path
from typing import Any, Protocol

from vocalika.audio.sources.base import AudioAsset
from vocalika.cache.manager import CacheManager


class SeparationError(RuntimeError):
    """Raised when vocal separation cannot produce a usable stem."""


@dataclass(frozen=True)
class SeparationResult:
    vocals: Path
    accompaniment: Path | None
    model: str
    model_version: str | None
    cache_hit: bool

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["vocals"] = str(self.vocals)
        payload["accompaniment"] = str(self.accompaniment) if self.accompaniment else None
        return payload


class VocalSeparator(Protocol):
    def separate(self, audio: AudioAsset) -> SeparationResult: ...


@dataclass(frozen=True)
class DemucsVocalSeparator:
    cache: CacheManager
    model: str = "htdemucs"
    refresh: bool = False

    @property
    def model_version(self) -> str:
        return version("demucs")

    def _parameters(self) -> dict[str, Any]:
        return {
            "separator": "demucs",
            "model": self.model,
            "model_version": self.model_version,
            "two_stems": "vocals",
        }

    def _cached_result(self, directory: Path) -> SeparationResult | None:
        metadata_path = directory / "metadata.json"
        vocals = directory / "vocals.wav"
        accompaniment = directory / "accompaniment.wav"
        if not metadata_path.is_file() or not vocals.is_file():
            return None
        metadata: dict[str, Any] = json.loads(metadata_path.read_text(encoding="utf-8"))
        return SeparationResult(
            vocals=vocals,
            accompaniment=accompaniment if accompaniment.is_file() else None,
            model=metadata["model"],
            model_version=metadata.get("model_version"),
            cache_hit=True,
        )

    def separate(self, audio: AudioAsset) -> SeparationResult:
        directory = self.cache.separation_directory(audio.content_hash, self._parameters())
        if not self.refresh and (cached := self._cached_result(directory)):
            return cached

        directory.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix="vocalika-separation-", dir=directory.parent
        ) as raw:
            temporary = Path(raw)
            command = [
                "demucs",
                "--two-stems",
                "vocals",
                "--name",
                self.model,
                "--out",
                str(temporary),
                "--filename",
                "{stem}.{ext}",
                str(audio.path),
            ]
            try:
                subprocess.run(command, check=True, capture_output=True, text=True)
            except (FileNotFoundError, subprocess.CalledProcessError) as error:
                detail = getattr(error, "stderr", "") or str(error)
                raise SeparationError(
                    "Vocal separation failed. Run `uv sync --extra real-input` and ensure the "
                    f"model can be downloaded. Details: {detail.strip()}"
                ) from error

            model_output = temporary / self.model
            vocals_candidates = list(model_output.glob("**/vocals.wav"))
            accompaniment_candidates = list(model_output.glob("**/no_vocals.wav"))
            if len(vocals_candidates) != 1:
                raise SeparationError("Demucs did not produce exactly one vocals.wav stem")
            directory.mkdir(parents=True, exist_ok=True)
            vocals_candidates[0].replace(directory / "vocals.wav")
            if len(accompaniment_candidates) == 1:
                accompaniment_candidates[0].replace(directory / "accompaniment.wav")
            (directory / "metadata.json").write_text(
                json.dumps(self._parameters(), indent=2) + "\n",
                encoding="utf-8",
            )

        result = self._cached_result(directory)
        if result is None:
            raise SeparationError("Separated vocal cache could not be finalized")
        return SeparationResult(
            vocals=result.vocals,
            accompaniment=result.accompaniment,
            model=result.model,
            model_version=result.model_version,
            cache_hit=False,
        )

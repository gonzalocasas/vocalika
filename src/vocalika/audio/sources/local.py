from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from vocalika.audio.decode import probe_audio
from vocalika.audio.sources.base import AudioAsset


@dataclass(frozen=True)
class LocalAudioSource:
    path: Path

    def acquire(self) -> AudioAsset:
        info = probe_audio(self.path)
        path = Path(info.path)
        return AudioAsset(
            path=path,
            source_type="local",
            title=path.stem,
            source_url=None,
            duration_seconds=info.duration_seconds,
            sample_rate=info.sample_rate,
            content_hash=info.content_hash,
            metadata={
                "format_name": info.format_name,
                "extension": info.extension,
                "channels": info.channels,
            },
        )

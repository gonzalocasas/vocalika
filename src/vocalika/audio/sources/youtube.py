from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from vocalika.audio.decode import hash_file, probe_audio
from vocalika.audio.sources.base import AudioAsset, is_youtube_url
from vocalika.cache.manager import CacheManager


class YouTubeAcquisitionError(RuntimeError):
    """Raised when a public YouTube reference cannot be acquired."""


@dataclass(frozen=True)
class YouTubeAudioSource:
    url: str
    cache: CacheManager
    refresh: bool = False

    def _source_key(self) -> str:
        return hashlib.sha256(self.url.strip().encode()).hexdigest()

    def _load_cached(self, directory: Path) -> AudioAsset | None:
        metadata_path = directory / "metadata.json"
        if not metadata_path.is_file():
            return None
        payload: dict[str, Any] = json.loads(metadata_path.read_text(encoding="utf-8"))
        audio_path = directory / payload["filename"]
        if not audio_path.is_file() or hash_file(audio_path) != payload["content_hash"]:
            return None
        return AudioAsset(
            path=audio_path,
            source_type="youtube",
            title=payload.get("title"),
            source_url=payload.get("source_url"),
            duration_seconds=payload.get("duration_seconds"),
            sample_rate=payload.get("sample_rate"),
            content_hash=payload["content_hash"],
            metadata=payload.get("metadata", {}),
        )

    def acquire(self) -> AudioAsset:
        if not is_youtube_url(self.url):
            raise YouTubeAcquisitionError(f"Not a supported YouTube URL: {self.url}")
        directory = self.cache.source_directory(self._source_key())
        if not self.refresh and (cached := self._load_cached(directory)):
            return cached

        directory.mkdir(parents=True, exist_ok=True)
        output_template = directory / "source.%(ext)s"
        command = [
            "yt-dlp",
            "--no-playlist",
            "--no-progress",
            "--extract-audio",
            "--format",
            "bestaudio/best",
            "--write-info-json",
            "--output",
            str(output_template),
            "--print",
            "after_move:filepath",
            self.url,
        ]
        if self.refresh:
            command.insert(1, "--force-overwrites")
        try:
            result = subprocess.run(command, check=True, capture_output=True, text=True)
        except FileNotFoundError as error:
            raise YouTubeAcquisitionError(
                "Unable to retrieve this YouTube reference because yt-dlp is not installed. "
                "Run `uv sync --extra real-input`, or provide a local audio file instead."
            ) from error
        except subprocess.CalledProcessError as default_error:
            # YouTube increasingly requires a signed JavaScript challenge for
            # media URLs returned by its default android_vr client. Some URLs
            # expose metadata normally but reject the complete media transfer
            # with HTTP 403. The embedded client plus yt-dlp's official EJS
            # component is a reliable fallback for embeddable public videos.
            fallback_command = command.copy()
            fallback_options = [
                "--remote-components",
                "ejs:github",
                "--extractor-args",
                "youtube:player_client=web_embedded",
            ]
            if "--force-overwrites" not in fallback_command:
                fallback_options.insert(0, "--force-overwrites")
            fallback_command[1:1] = fallback_options
            try:
                result = subprocess.run(
                    fallback_command,
                    check=True,
                    capture_output=True,
                    text=True,
                )
            except subprocess.CalledProcessError as fallback_error:
                default_detail = default_error.stderr.strip()
                fallback_detail = fallback_error.stderr.strip()
                raise YouTubeAcquisitionError(
                    "Unable to retrieve this YouTube reference. The normal media request and "
                    "the signed embedded-client fallback both failed. Check that the video is "
                    "public and embeddable, or provide a local audio file instead. "
                    f"Default details: {default_detail or default_error}. "
                    f"Fallback details: {fallback_detail or fallback_error}"
                ) from fallback_error
        except OSError as error:
            detail = getattr(error, "stderr", "") or str(error)
            raise YouTubeAcquisitionError(
                "Unable to retrieve this YouTube reference. Check that it is public and "
                f"available, or provide a local audio file instead. Details: {detail.strip()}"
            ) from error

        printed_paths = [Path(line) for line in result.stdout.splitlines() if line.strip()]
        audio_path = next((path for path in reversed(printed_paths) if path.is_file()), None)
        if audio_path is None:
            candidates = [
                path
                for path in directory.glob("source.*")
                if path.suffix != ".json" and path.is_file()
            ]
            audio_path = candidates[0] if len(candidates) == 1 else None
        if audio_path is None:
            raise YouTubeAcquisitionError("yt-dlp completed without producing an audio file")

        info_path = directory / "source.info.json"
        youtube_info: dict[str, Any] = (
            json.loads(info_path.read_text(encoding="utf-8")) if info_path.is_file() else {}
        )
        audio_info = probe_audio(audio_path)
        content_hash = audio_info.content_hash
        metadata: dict[str, Any] = {
            "video_id": youtube_info.get("id"),
            "extractor": youtube_info.get("extractor_key"),
            "format_id": youtube_info.get("format_id"),
            "channels": audio_info.channels,
            "format_name": audio_info.format_name,
        }
        cache_payload: dict[str, Any] = {
            "filename": audio_path.name,
            "title": youtube_info.get("title"),
            "source_url": youtube_info.get("webpage_url") or self.url,
            "duration_seconds": youtube_info.get("duration") or audio_info.duration_seconds,
            "sample_rate": audio_info.sample_rate,
            "content_hash": content_hash,
            "metadata": metadata,
        }
        (directory / "metadata.json").write_text(
            json.dumps(cache_payload, indent=2) + "\n",
            encoding="utf-8",
        )
        return self._load_cached(directory) or AudioAsset(
            path=audio_path,
            source_type="youtube",
            title=cache_payload["title"],
            source_url=cache_payload["source_url"],
            duration_seconds=cache_payload["duration_seconds"],
            sample_rate=audio_info.sample_rate,
            content_hash=content_hash,
            metadata=metadata,
        )

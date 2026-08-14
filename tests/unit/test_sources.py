from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf

from vocalika.audio.sources import LocalAudioSource, YouTubeAudioSource, is_youtube_url
from vocalika.cache.manager import CacheManager


def write_wav(path: Path) -> None:
    sample_rate = 16_000
    times = np.arange(sample_rate, dtype=np.float64) / sample_rate
    sf.write(path, 0.2 * np.sin(2.0 * np.pi * 220.0 * times), sample_rate)


def test_youtube_url_detection_is_narrow() -> None:
    assert is_youtube_url("https://www.youtube.com/watch?v=abc")
    assert is_youtube_url("https://youtu.be/abc")
    assert not is_youtube_url("https://example.com/watch?v=abc")
    assert not is_youtube_url("./youtube.com-recording.flac")


def test_local_source_produces_common_audio_asset(tmp_path: Path) -> None:
    source = tmp_path / "performance.wav"
    write_wav(source)

    asset = LocalAudioSource(source).acquire()

    assert asset.source_type == "local"
    assert asset.path == source.resolve()
    assert asset.sample_rate == 16_000
    assert asset.duration_seconds == 1.0
    assert len(asset.content_hash) == 64


def test_youtube_source_downloads_once_then_uses_cache(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    cache = CacheManager(tmp_path / "cache")
    original_run = subprocess.run
    yt_dlp_calls = 0

    def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        nonlocal yt_dlp_calls
        if command[0] != "yt-dlp":
            return original_run(command, **kwargs)
        yt_dlp_calls += 1
        output_template = Path(command[command.index("--output") + 1])
        audio_path = output_template.with_name("source.wav")
        write_wav(audio_path)
        (audio_path.parent / "source.info.json").write_text(
            json.dumps(
                {
                    "id": "video-123",
                    "title": "Reference title",
                    "webpage_url": "https://www.youtube.com/watch?v=video-123",
                    "duration": 1.0,
                    "extractor_key": "Youtube",
                    "format_id": "test",
                }
            ),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, stdout=f"{audio_path}\n", stderr="")

    monkeypatch.setattr("vocalika.audio.sources.youtube.subprocess.run", fake_run)
    source = YouTubeAudioSource("https://youtu.be/video-123", cache)

    first = source.acquire()
    second = source.acquire()

    assert yt_dlp_calls == 1
    assert first == second
    assert first.title == "Reference title"
    assert first.metadata["video_id"] == "video-123"

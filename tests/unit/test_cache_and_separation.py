from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf

from vocalika.analysis.pitch import RmvpePitchExtractor
from vocalika.analysis.pitch_cache import extract_clean_pitch
from vocalika.audio.preprocessing import normalize_for_analysis
from vocalika.audio.separation import DemucsVocalSeparator
from vocalika.audio.sources import LocalAudioSource
from vocalika.cache.manager import CacheManager, stable_hash


def write_wav(path: Path, sample_rate: int = 44_100) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    times = np.arange(sample_rate, dtype=np.float64) / sample_rate
    sf.write(path, 0.2 * np.sin(2.0 * np.pi * 220.0 * times), sample_rate)


def test_stable_cache_hash_ignores_dictionary_order() -> None:
    assert stable_hash({"a": 1, "b": 2}) == stable_hash({"b": 2, "a": 1})


def test_normalized_audio_is_cached(tmp_path: Path) -> None:
    source = tmp_path / "source.wav"
    write_wav(source)
    asset = LocalAudioSource(source).acquire()
    cache = CacheManager(tmp_path / "cache")

    first = normalize_for_analysis(asset, cache, 16_000)
    second = normalize_for_analysis(asset, cache, 16_000)

    assert not first.cache_hit
    assert second.cache_hit
    assert first.path == second.path


def test_demucs_separation_is_cached(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    source = tmp_path / "mix.wav"
    write_wav(source)
    asset = LocalAudioSource(source).acquire()
    cache = CacheManager(tmp_path / "cache")
    calls = 0

    def fake_run(command: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        output = Path(command[command.index("--out") + 1]) / "htdemucs"
        write_wav(output / "vocals.wav")
        write_wav(output / "no_vocals.wav")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr("vocalika.audio.separation.subprocess.run", fake_run)
    separator = DemucsVocalSeparator(cache)

    first = separator.separate(asset)
    second = separator.separate(asset)

    assert calls == 1
    assert not first.cache_hit
    assert second.cache_hit
    assert first.vocals == second.vocals
    assert second.accompaniment is not None


def test_clean_pitch_is_cached_by_content_and_parameters(tmp_path: Path) -> None:
    source = tmp_path / "voice.wav"
    write_wav(source, sample_rate=16_000)
    asset = LocalAudioSource(source).acquire()
    cache = CacheManager(tmp_path / "cache")
    extractor = RmvpePitchExtractor()
    parameters = {
        "confidence_threshold": 0.55,
        "octave_window": 9,
        "max_gap_seconds": 0.08,
    }

    first = extract_clean_pitch(
        audio_path=source,
        content_hash=asset.content_hash,
        cache=cache,
        extractor=extractor,
        cleaning_parameters=parameters,
        pipeline_version="test",
    )
    second = extract_clean_pitch(
        audio_path=source,
        content_hash=asset.content_hash,
        cache=cache,
        extractor=extractor,
        cleaning_parameters=parameters,
        pipeline_version="test",
    )
    following_the_louder_voice = extract_clean_pitch(
        audio_path=source,
        content_hash=asset.content_hash,
        cache=cache,
        extractor=RmvpePitchExtractor(voice="louder"),
        cleaning_parameters=parameters,
        pipeline_version="test",
    )

    assert not first.cache_hit
    assert second.cache_hit
    assert not following_the_louder_voice.cache_hit
    np.testing.assert_array_equal(first.track.midi, second.track.midi)


def test_cache_directory_can_be_moved_by_environment(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setenv("VOCALIKA_CACHE_DIR", str(tmp_path / "app-cache"))
    assert CacheManager.default().root == tmp_path / "app-cache"


def test_demucs_is_given_a_decoded_wav_for_formats_it_cannot_read(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    """demucs needs an ffmpeg executable for Opus; it must never be asked to."""
    from vocalika.audio import media

    wav = tmp_path / "mix.wav"
    write_wav(wav)
    source = tmp_path / "source.webm"
    media.transcode(wav, source, codec="libopus", sample_rate=48_000)
    asset = LocalAudioSource(source).acquire()
    received: list[tuple[str, int, int]] = []

    def fake_run(command: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        info = sf.info(command[-1])
        received.append((Path(command[-1]).suffix, info.samplerate, info.channels))
        output = Path(command[command.index("--out") + 1]) / "htdemucs"
        write_wav(output / "vocals.wav")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr("vocalika.audio.separation.subprocess.run", fake_run)
    DemucsVocalSeparator(CacheManager(tmp_path / "cache")).separate(asset)

    assert received == [(".wav", 48_000, 1)]

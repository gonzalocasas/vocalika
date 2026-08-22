from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf

from vocalika.analysis.pitch import PyinPitchExtractor
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
    extractor = PyinPitchExtractor()
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
    without_harmonic_preprocessing = extract_clean_pitch(
        audio_path=source,
        content_hash=asset.content_hash,
        cache=cache,
        extractor=PyinPitchExtractor(harmonic_margin=0.0),
        cleaning_parameters=parameters,
        pipeline_version="test",
    )

    assert not first.cache_hit
    assert second.cache_hit
    assert not without_harmonic_preprocessing.cache_hit
    np.testing.assert_array_equal(first.track.midi, second.track.midi)

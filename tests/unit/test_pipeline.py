from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import soundfile as sf

from vocalika.audio.separation import DemucsVocalSeparator, SeparationResult
from vocalika.audio.sources import AudioAsset
from vocalika.pipeline import run_analysis


def _write_melody(path: Path, *, accompaniment: bool = False) -> None:
    sample_rate = 16_000
    parts: list[np.ndarray] = []
    for midi in (60.0, 62.0, 64.0, 67.0):
        times = np.arange(round(0.8 * sample_rate)) / sample_rate
        frequency = 440.0 * 2.0 ** ((midi - 69.0) / 12.0)
        audio = 0.3 * np.sin(2.0 * np.pi * frequency * times)
        if accompaniment:
            audio += 0.08 * np.sin(2.0 * np.pi * 110.0 * times)
        parts.append(audio)
    sf.write(path, np.concatenate(parts).astype(np.float32), sample_rate, subtype="FLOAT")


def test_opt_in_performance_isolation_uses_stem_and_preserves_mix(
    tmp_path: Path,
    monkeypatch,
) -> None:
    reference = tmp_path / "reference.wav"
    performance_mix = tmp_path / "performance-mix.wav"
    isolated_performance = tmp_path / "isolated-performance.wav"
    _write_melody(reference)
    _write_melody(performance_mix, accompaniment=True)
    _write_melody(isolated_performance)
    progress_messages: list[str] = []

    def fake_separate(
        _separator: DemucsVocalSeparator,
        audio: AudioAsset,
    ) -> SeparationResult:
        assert audio.path == performance_mix.resolve()
        return SeparationResult(
            vocals=isolated_performance,
            accompaniment=None,
            model="test-separator",
            model_version="1",
            cache_hit=False,
        )

    monkeypatch.setattr(DemucsVocalSeparator, "separate", fake_separate)

    artifact_path = run_analysis(
        reference,
        performance_mix,
        tmp_path / "output",
        reference_is_vocal=True,
        isolate_performance=True,
        cache_directory=tmp_path / "cache",
        progress=progress_messages.append,
    )
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))

    assert artifact["performance"]["source"]["path"] == str(performance_mix.resolve())
    assert artifact["performance"]["analysis_source"]["path"] == str(
        isolated_performance.resolve()
    )
    assert artifact["performance"]["original_mix"]["path"] == str(performance_mix.resolve())
    assert artifact["performance"]["isolation_applied"] is True
    assert artifact["performance"]["separation"]["model"] == "test-separator"
    assert artifact["pitch"]["harmonic_margin"] == 1.0
    frames = artifact["comparison"]["frames"]
    frame_count = len(frames["reference_time"])
    for key in (
        "reference_confidence",
        "performance_confidence",
        "reference_voiced",
        "performance_voiced",
    ):
        assert len(frames[key]) == frame_count
    assert "Isolating performance vocal" in progress_messages

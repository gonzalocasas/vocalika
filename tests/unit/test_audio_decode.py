from __future__ import annotations

from pathlib import Path

import numpy as np
import soundfile as sf

from vocalika.audio.decode import decode_for_analysis, hash_file, load_audio, probe_audio


def test_flac_is_preserved_and_decoded_for_analysis(tmp_path: Path) -> None:
    sample_rate = 44_100
    times = np.arange(sample_rate, dtype=np.float64) / sample_rate
    signal = (0.25 * np.sin(2.0 * np.pi * 220.0 * times)).astype(np.float32)
    source = tmp_path / "ableton-export.flac"
    sf.write(source, signal, sample_rate, format="FLAC")
    original_hash = hash_file(source)

    info = probe_audio(source)
    decoded = decode_for_analysis(source, tmp_path / "working" / "performance.wav")
    decoded_signal, decoded_rate = load_audio(decoded)

    assert info.format_name == "flac"
    assert info.sample_rate == sample_rate
    assert info.channels == 1
    assert decoded_rate == 16_000
    assert decoded_signal.ndim == 1
    assert hash_file(source) == original_hash

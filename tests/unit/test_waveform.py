from __future__ import annotations

from pathlib import Path

import numpy as np
import soundfile as sf

from vocalika.api.waveform import build_aligned_waveforms, build_waveform_envelope


def test_aligned_waveforms_prefer_isolated_analysis_sources(tmp_path: Path) -> None:
    sample_rate = 16_000
    times = np.arange(sample_rate, dtype=np.float32) / sample_rate
    silent_mix = tmp_path / "mix.wav"
    reference_vocal = tmp_path / "reference-vocal.wav"
    performance_vocal = tmp_path / "performance-vocal.wav"
    sf.write(silent_mix, np.zeros_like(times), sample_rate)
    sf.write(reference_vocal, 0.2 * np.sin(2 * np.pi * 220 * times), sample_rate)
    sf.write(performance_vocal, 0.2 * np.sin(2 * np.pi * 240 * times), sample_rate)

    frame_times = np.linspace(0.1, 0.9, 20).tolist()
    waveforms = build_aligned_waveforms(
        {
            "reference": {
                "source": {"path": str(silent_mix)},
                "analysis_source": {"path": str(reference_vocal)},
            },
            "performance": {
                "source": {"path": str(silent_mix)},
                "analysis_source": {"path": str(performance_vocal)},
            },
            "comparison": {
                "frames": {
                    "reference_time": frame_times,
                    "performance_time": frame_times,
                }
            },
        }
    )

    assert max(waveforms["reference_amplitude"]) > 0.9
    assert max(waveforms["performance_amplitude"]) > 0.9

    inferred = build_waveform_envelope(reference_vocal, 0.0, maximum_points=12)
    assert len(inferred["amplitude"]) == 12
    assert inferred["time"][-1] == 1.0

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from vocalika.projects.export import _place_take
from vocalika.projects.models import Take
from vocalika.projects.timing import resolve_timing


def take_with_alignment(tmp_path: Path, alignment: dict, **kwargs) -> Take:
    path = tmp_path / "analysis.json"
    path.write_text(json.dumps({
        "schema_version": "0.1.0", "alignment": alignment,
        "comparison": {"frames": {"reference_time": [0, 1], "performance_time": [2, 3]}},
    }))
    return Take("a", "take", "now", "source.wav", False, analysis_path=str(path), **kwargs)


@pytest.mark.parametrize("alignment", [
    {},
    {"global_offset_seconds": -.1, "global_offset_confidence": .941530961,
     "global_offset_method": "smoothed-vocal-envelope-correlation"},
    {"global_offset_seconds": -.1, "global_offset_confidence": 1,
     "global_offset_method": "spectral-phrase-plus-vocal-envelope-timing"},
    {"global_offset_seconds": 3, "global_offset_confidence": 1,
     "global_offset_method": "spectral-change-correlation"},
    {"global_offset_seconds": 3, "global_offset_confidence": .89,
     "global_offset_method": "pcm-cross-correlation"},
    {"global_offset_seconds": float("nan"), "global_offset_confidence": 1,
     "global_offset_method": "pcm-cross-correlation"},
])
def test_uncertain_and_legacy_alignment_never_moves_audio(tmp_path, alignment):
    timing = resolve_timing(take_with_alignment(tmp_path, alignment))
    assert timing.offset_seconds == 0
    assert timing.source == "original"


def test_capture_position_wins_over_analysis_and_roundtrips(tmp_path):
    take = take_with_alignment(tmp_path, {
        "global_offset_seconds": 4, "global_offset_confidence": 1,
        "global_offset_method": "pcm-cross-correlation",
    }, recording_offset_seconds=-19.97)
    restored = Take.from_dict(take.__dict__)
    assert resolve_timing(restored).offset_seconds == -19.97
    assert resolve_timing(restored).source == "recording"


@pytest.mark.parametrize("method,version", [("pcm-cross-correlation", 0),
                                            ("spectral-change-correlation", 2)])
def test_verified_matches_can_place_imported_partial_takes(tmp_path, method, version):
    take = take_with_alignment(tmp_path, {
        "global_offset_seconds": -20, "global_offset_confidence": .99,
        "global_offset_method": method, "timing_estimator_version": version,
    })
    assert resolve_timing(take).offset_seconds == -20


@pytest.mark.parametrize("sample_rate", [16000, 44100, 48000])
@pytest.mark.parametrize("trim,offset", [(0, .25), (0, -.25), (.5, -.25), (1, -1),
                                        (1.5, -1), (0, 10), (0, -10)])
def test_placement_matches_physical_timeline_without_stretching(sample_rate, trim, offset):
    # Every source sample is identifiable; compare against the time equation,
    # not another correlation/DTW implementation.
    source = np.arange(2 * sample_rate, dtype=np.float32)[:, None]
    result = _place_take(source, sample_rate, sample_rate, trim, offset)[:, 0]
    indices = np.arange(sample_rate) + round((trim + offset) * sample_rate)
    expected = np.zeros(sample_rate, dtype=np.float32)
    valid = (indices >= 0) & (indices < len(source))
    expected[valid] = source[indices[valid], 0]
    np.testing.assert_array_equal(result, expected)


@pytest.mark.parametrize("source_rate", [16000, 44100, 48000])
def test_resampling_preserves_known_onset_times(tmp_path, source_rate):
    import soundfile as sf

    from vocalika.projects.export import _read_audio

    path = tmp_path / "impulses.wav"
    audio = np.zeros(source_rate * 3, dtype=np.float32)
    audio[[round(.5 * source_rate), 2 * source_rate]] = 0.5
    sf.write(path, audio, source_rate, subtype="FLOAT")
    rendered = _read_audio(path, 44100)[:, 0]
    assert len(rendered) == 3 * 44100
    for expected in [22050, 88200]:
        peak = expected - 10 + int(np.argmax(abs(rendered[expected - 10:expected + 11])))
        assert abs(peak - expected) <= 1


def test_refinement_does_not_move_physical_audio_to_envelope_peak(tmp_path):
    take = take_with_alignment(tmp_path, {
        "global_offset_seconds": -3.2, "global_offset_confidence": 1,
        "global_offset_method": "spectral-phrase-plus-vocal-envelope-timing",
        "timing_estimator_version": 2,
        "global_offset_candidates": [{"method": "spectral-change-correlation",
                                      "seconds": -3, "confidence": 1}],
    })
    assert resolve_timing(take).offset_seconds == -3

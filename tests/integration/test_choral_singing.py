"""Hold pitch, voice choice, comparison and practice scoring to hand-corrected truth.

The Choral Singing Dataset (CSD) has 16 singers -- four per SATB section --
each recorded on their own microphone singing three pieces, with every
singer's F0 extracted by Tony and then corrected by hand. Sections were
recorded separately against the same backing track, so they are synchronised:
mixing them builds harmony whose every voice has a known answer, and two
singers of one section are a real reference and a real take whose intonation
difference is known frame by frame.

That makes it the one open dataset that checks, against human-verified data,
each layer between audio and the number a singer sees: the take extractor
(down to bass range, which Vocadito barely covers), the reference voice choice
in harmony, the full comparison pipeline, and the practice scorers.

Thresholds sit a little outside the values measured when the tests were
written, so numerical drift between torch builds passes and a real regression
does not. Fetch the data with ``uv run python scripts/fetch_open_datasets.py csd``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import soundfile as sf
from open_data import (
    ANALYSIS_SAMPLE_RATE,
    dataset_root,
    extract_clean,
    frame_errors,
    hz_to_midi,
    load_mono,
    nearest,
    octave_error_share,
)

from vocalika.pipeline import run_analysis
from vocalika.practice.scoring import score_held_note, score_interval, verdict_for

pytestmark = pytest.mark.open_data

PIECES = ("ER", "LI", "ND")
SECTIONS = ("soprano", "alto", "tenor", "bass")
SINGERS = (1, 2, 3, 4)

# The published F0 file for this singer is, for 99.8% of its frames, a copy
# of singer 2's: it is singer 2's contour, not singer 3's. Scoring against it
# would report ~28 cents of error that is not there. Guarded below, so a
# corrected release of the dataset is noticed.
MISANNOTATED = {("ND", "tenor", 3)}

TRACKS = [
    (piece, section, singer)
    for piece in PIECES
    for section in SECTIONS
    for singer in SINGERS
    if (piece, section, singer) not in MISANNOTATED
]


def _track_id(track: tuple[str, str, int]) -> str:
    piece, section, singer = track
    return f"{piece}_{section}_{singer}"


@cache
def _root() -> Path:
    return dataset_root("csd") / "ChoralSingingDataset"


def _audio_path(piece: str, section: str, singer: int) -> Path:
    return _root() / f"CSD_{piece}_{section}_{singer}.wav"


@cache
def _annotation(piece: str, section: str, singer: int) -> tuple[np.ndarray, np.ndarray]:
    data = np.loadtxt(_root() / f"CSD_{piece}_{section}_{singer}.f0")
    return data[:, 0], data[:, 1]


@cache
def _section_notes(piece: str, section: str) -> np.ndarray:
    """The section's hand-corrected notes as rows of (start, mean Hz, duration)."""
    return np.loadtxt(_root() / f"CSD_{piece}_{section}_notes.lab", ndmin=2)


@dataclass(frozen=True)
class FrameScore:
    within_50: float
    median_cents: float
    octave_errors: float
    voicing_recall: float


def _score(track: Any, piece: str, section: str, singer: int) -> FrameScore:
    errors, recall = frame_errors(track, *_annotation(piece, section, singer))
    return FrameScore(
        within_50=float(np.mean(errors <= 50.0)),
        median_cents=float(np.median(errors)),
        octave_errors=octave_error_share(errors),
        voicing_recall=recall,
    )


def test_the_known_annotation_defect_is_still_present() -> None:
    """If this fails, the dataset was corrected: drop the track from MISANNOTATED."""
    for piece, section, singer in MISANNOTATED:
        _, copied = _annotation(piece, section, singer)
        _, original = _annotation(piece, section, singer - 1)
        frames = min(copied.size, original.size)
        assert np.mean(copied[:frames] == original[:frames]) > 0.99


# -- The take path on solo voices ------------------------------------------


@pytest.fixture(scope="module")
def take_scores() -> dict[tuple[str, str, int], FrameScore]:
    """Every singer through the take extractor, scored once for the module."""
    _root()
    return {
        track: _score(extract_clean(load_mono(_audio_path(*track)), "single"), *track)
        for track in TRACKS
    }


@pytest.mark.parametrize("track", TRACKS, ids=_track_id)
def test_take_pitch_matches_the_hand_corrected_f0(
    track: tuple[str, str, int], take_scores: dict[tuple[str, str, int], FrameScore]
) -> None:
    """Every singer, soprano to bass, within a few cents of the hand-corrected F0.

    Measured: median error 1.3-4.7 cents, 94.8-99.3% of frames within 50
    cents, octave errors on at most 0.1% of frames, and 95-100% of sung
    frames reported.
    """
    score = take_scores[track]
    assert score.median_cents < 6.5
    assert score.within_50 > 0.925
    assert score.octave_errors < 0.005
    assert score.voicing_recall > 0.93


def test_take_pitch_holds_across_every_section(
    take_scores: dict[tuple[str, str, int], FrameScore],
) -> None:
    for section in SECTIONS:
        scores = [score for (_, s, _), score in take_scores.items() if s == section]
        # Bass measured 3.0 cents, the others 1.9.
        assert np.median([score.median_cents for score in scores]) < 4.0, section
        assert np.median([score.within_50 for score in scores]) > 0.96, section


# The first singer of every section and piece: enough to cover each range,
# and the singers the pair tests below use as references.
REFERENCE_TRACKS = [track for track in TRACKS if track[2] == 1]


@pytest.mark.parametrize("track", REFERENCE_TRACKS, ids=_track_id)
def test_second_voice_search_costs_little_on_a_solo_voice(
    track: tuple[str, str, int], take_scores: dict[tuple[str, str, int], FrameScore]
) -> None:
    """The reference path searches for a second voice; on a solo it must find none.

    It is not free: on low voices it occasionally takes a harmonic for a
    second singer. The worst case measured, ND bass 1, lost 3 points of
    frames within 50 cents (0.968 to 0.939) and its mean error rose from 10
    to 40 cents. This pins that cost so it cannot grow.
    """
    reference = _score(extract_clean(load_mono(_audio_path(*track))), *track)
    take = take_scores[track]
    assert reference.within_50 > take.within_50 - 0.045
    assert reference.within_50 > 0.92
    assert reference.octave_errors < 0.005


# -- Voice choice in harmony -----------------------------------------------


@dataclass(frozen=True)
class HarmonyCase:
    name: str
    lead: str
    others: tuple[str, ...]
    others_db: float
    voice: str | None  # None: the default reference voice, "louder"
    target: str
    floor: float


# Floors sit ~0.05 under the lowest of the three pieces measured.
HARMONY_CASES = [
    # The melody 6 dB over a harmony below it, and over one above it.
    HarmonyCase("melody-over-lower-harmony", "soprano", ("alto",), -6.0, None, "soprano", 0.78),
    HarmonyCase("melody-under-upper-harmony", "alto", ("soprano",), -6.0, None, "alto", 0.89),
    # An equal-level duet has no acoustic answer; the project's voice setting
    # picks one, and must deliver it.
    HarmonyCase("equal-duet-upper", "soprano", ("alto",), 0.0, "upper", "soprano", 0.79),
    HarmonyCase("equal-duet-lower", "soprano", ("alto",), 0.0, "lower", "alto", 0.83),
    HarmonyCase("tenor-bass-duet-lower", "tenor", ("bass",), 0.0, "lower", "bass", 0.77),
    # The known weak spot: where the bass doubles the tenor an octave down,
    # "upper" follows the bass on up to 19% of frames (ND measured 0.686).
    HarmonyCase("tenor-bass-duet-upper", "tenor", ("bass",), 0.0, "upper", "tenor", 0.63),
]


def _voiced_rms(audio: np.ndarray, times: np.ndarray, frequency: np.ndarray, rate: int) -> float:
    """RMS over the sung frames only, so rests do not skew the balance of a mix."""
    voiced = np.zeros(audio.size, dtype=bool)
    hop = int(round(float(np.median(np.diff(times))) * rate))
    for time in times[frequency > 0.0]:
        start = int(time * rate)
        voiced[start : start + hop] = True
    sample = audio[voiced] if voiced.any() else audio
    return float(np.sqrt(np.mean(sample**2)) + 1e-12)


def _mix(piece: str, lead: str, others: tuple[str, ...], others_db: float) -> np.ndarray:
    rate = ANALYSIS_SAMPLE_RATE
    mix = load_mono(_audio_path(piece, lead, 1))
    lead_rms = _voiced_rms(mix, *_annotation(piece, lead, 1), rate)
    for section in others:
        audio = load_mono(_audio_path(piece, section, 1))
        gain = lead_rms / _voiced_rms(audio, *_annotation(piece, section, 1), rate)
        frames = min(mix.size, audio.size)
        mix = mix[:frames] + gain * 10.0 ** (others_db / 20.0) * audio[:frames]
    return np.asarray(0.9 * mix / np.max(np.abs(mix)), dtype=np.float32)


@pytest.mark.parametrize("piece", PIECES)
@pytest.mark.parametrize("case", HARMONY_CASES, ids=lambda case: case.name)
def test_reference_follows_the_chosen_voice_in_harmony(case: HarmonyCase, piece: str) -> None:
    track = extract_clean(_mix(piece, case.lead, case.others, case.others_db), case.voice)  # type: ignore[arg-type]
    score = _score(track, piece, case.target, 1)
    assert score.within_50 > case.floor


# -- The full pipeline on real reference/take pairs ------------------------

PAIRS = [(piece, section, singer) for piece, section, singer in TRACKS if singer != 1]


@dataclass(frozen=True)
class PairMeasurement:
    reported_bias: float
    true_bias: float
    reported_relative_mae: float
    true_relative_mae: float
    median_frame_deviation: float
    annotated_share: float
    median_pairing_lag: float
    region_deviations: tuple[float, ...]
    matched_seconds: float


def _measure_pair(
    artifact: dict[str, Any], piece: str, section: str, singer: int
) -> PairMeasurement:
    """Compare what the pipeline reported with what the annotations say.

    The truth is read on the pipeline's own pairing of reference and take
    frames, so this isolates measurement from alignment; the alignment itself
    is judged by how far apart in time it pairs synchronised singers.
    """
    frames = artifact["comparison"]["frames"]
    valid = np.asarray(frames["valid"], dtype=bool)
    reference_times = np.asarray(frames["reference_time"])[valid]
    performance_times = np.asarray(frames["performance_time"])[valid]
    reported = np.asarray(frames["absolute_error_cents"])[valid]

    reference_hz = nearest(*_annotation(piece, section, 1), reference_times)
    performance_hz = nearest(*_annotation(piece, section, singer), performance_times)
    annotated = (reference_hz > 0.0) & (performance_hz > 0.0)
    truth = 100.0 * (hz_to_midi(performance_hz[annotated]) - hz_to_midi(reference_hz[annotated]))
    true_bias = float(np.median(truth))

    deviations = []
    for region in artifact["comparison"]["stable_pitch_regions"]:
        inside = (reference_times >= region["reference_start"]) & (
            reference_times < region["reference_end"]
        )
        both = inside & annotated
        if np.count_nonzero(both) < 10:
            continue
        true_error = 100.0 * (
            float(np.median(hz_to_midi(performance_hz[both])))
            - float(np.median(hz_to_midi(reference_hz[both])))
        )
        deviations.append(region["error_cents"] - true_error)

    summary = artifact["comparison"]["summary"]
    return PairMeasurement(
        reported_bias=summary["global_bias_cents"],
        true_bias=true_bias,
        reported_relative_mae=summary["relative_mean_absolute_error_cents"],
        true_relative_mae=float(np.mean(np.abs(truth - true_bias))),
        median_frame_deviation=float(np.median(np.abs(reported[annotated] - truth))),
        annotated_share=float(np.mean(annotated)),
        median_pairing_lag=float(np.median(np.abs(performance_times - reference_times))),
        region_deviations=tuple(deviations),
        matched_seconds=summary["matched_seconds"],
    )


@pytest.fixture(scope="module")
def pair_measurements(
    tmp_path_factory: pytest.TempPathFactory,
) -> dict[tuple[str, str, int], PairMeasurement]:
    """Analyse singer 2, 3 and 4 of every section against singer 1, as the app would."""
    _root()
    working = tmp_path_factory.mktemp("csd-pairs")
    measurements = {}
    for piece, section, singer in PAIRS:
        artifact_path = run_analysis(
            _audio_path(piece, section, 1),
            _audio_path(piece, section, singer),
            working / f"{piece}_{section}_{singer}",
            reference_is_vocal=True,
            cache_directory=working / "cache",
        )
        artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
        measurements[(piece, section, singer)] = _measure_pair(artifact, piece, section, singer)
    return measurements


@pytest.mark.parametrize("pair", PAIRS, ids=_track_id)
def test_pipeline_reports_the_true_intonation_difference_between_two_singers(
    pair: tuple[str, str, int],
    pair_measurements: dict[tuple[str, str, int], PairMeasurement],
) -> None:
    """Bias, per-frame error and per-note error all match the hand-corrected truth.

    Measured on upper voices: bias within 0.8 cents of the truth, frames
    within 3.9 cents (median), and stable notes within 3.8 cents (median).
    Basses track less tightly -- their low fundamentals are harder to
    measure, and ND bass 1, the reference there, is the worst case of
    second-voice search -- with bias within 2.8 cents and frames within 5.6.
    """
    measured = pair_measurements[pair]
    bass = pair[1] == "bass"

    assert abs(measured.reported_bias - measured.true_bias) < (5.0 if bass else 2.0)
    assert measured.median_frame_deviation < (7.0 if bass else 4.5)
    assert np.median(np.abs(measured.region_deviations)) < (5.0 if bass else 4.5)
    assert np.max(np.abs(measured.region_deviations)) < 30.0
    # The pipeline compares frames where both really sang...
    assert measured.annotated_share > 0.94
    # ...and, since the singers were synchronised, pairs them close in time.
    assert measured.median_pairing_lag < 0.15
    assert measured.matched_seconds > 70.0


def test_pipeline_ranks_takes_as_the_truth_does(
    pair_measurements: dict[tuple[str, str, int], PairMeasurement],
) -> None:
    """Across all pairs, the reported numbers order takes the way the truth does."""
    measurements = list(pair_measurements.values())

    def rank_correlation(left: list[float], right: list[float]) -> float:
        return float(np.corrcoef(np.argsort(np.argsort(left)), np.argsort(np.argsort(right)))[0, 1])

    bias = rank_correlation(
        [m.reported_bias for m in measurements], [m.true_bias for m in measurements]
    )
    spread = rank_correlation(
        [m.reported_relative_mae for m in measurements],
        [m.true_relative_mae for m in measurements],
    )
    region_deviations = np.abs(np.concatenate([m.region_deviations for m in measurements]))

    # Measured: 0.993, 0.969 and 7.7 cents.
    assert bias > 0.97
    assert spread > 0.92
    assert float(np.percentile(region_deviations, 95)) < 10.0


# -- Practice scoring on real held notes and intervals -----------------------


def _annotated_centre(
    piece: str, section: str, singer: int, start: float, end: float, trim: float
) -> np.ndarray:
    """The singer's hand-corrected pitch inside a note, its onset and release trimmed."""
    times, frequency = _annotation(piece, section, singer)
    inside = (times >= start) & (times < end) & (frequency > 0.0)
    values = hz_to_midi(frequency[inside])
    margin = int(values.size * trim)
    return values[margin : values.size - margin]


def _clip(piece: str, section: str, singer: int, start: float, end: float, path: Path) -> Path:
    audio, rate = sf.read(_audio_path(piece, section, singer))
    sf.write(path, audio[int(start * rate) : int(end * rate)], rate)
    return path


@pytest.fixture(scope="module")
def held_notes(tmp_path_factory: pytest.TempPathFactory) -> list[dict[str, Any]]:
    """Score up to six long notes of every singer against the nearest tempered note."""
    _root()
    working = tmp_path_factory.mktemp("csd-held")
    rows = []
    for piece, section, singer in TRACKS:
        notes = [(start, hz, length) for start, hz, length in _section_notes(piece, section)]
        long_notes = [note for note in notes if note[2] >= 1.0][:6]
        for start, hz, length in long_notes:
            target = float(np.round(hz_to_midi(np.array([hz]))[0]))
            clip = _clip(piece, section, singer, start, start + length, working / "note.wav")
            score = score_held_note(clip, target)
            core = _annotated_centre(piece, section, singer, start, start + length, 0.15)
            centre = float(np.median(core))
            true_centre = 100.0 * (centre - target)
            true_steadiness = 100.0 * float(np.mean(np.abs(core - centre)))
            rows.append(
                {
                    "score": score,
                    "true_centre": true_centre,
                    "true_steadiness": true_steadiness,
                    "true_verdict": verdict_for(true_centre, true_steadiness),
                }
            )
    return rows


def test_held_note_scores_match_the_hand_corrected_pitch(held_notes: list[dict[str, Any]]) -> None:
    """The practice score of a real sung note: centre, steadiness and verdict.

    Measured over 254 notes: centre within 1.0 cent of the annotation
    (median; 8.7 worst), steadiness within 0.6 (median), and the verdict the
    annotation implies on 96% of notes -- the rest all on a verdict boundary.
    """
    assert len(held_notes) > 200
    assert all(row["score"].verdict != "not-heard" for row in held_notes)
    centre = np.array([abs(row["score"].centre_cents - row["true_centre"]) for row in held_notes])
    steadiness = np.array(
        [abs(row["score"].steadiness_cents - row["true_steadiness"]) for row in held_notes]
    )
    agreement = np.mean([row["score"].verdict == row["true_verdict"] for row in held_notes])

    assert float(np.median(centre)) < 2.0
    assert float(np.max(centre)) < 12.0
    assert float(np.percentile(steadiness, 90)) < 4.0
    assert agreement > 0.92


@pytest.fixture(scope="module")
def sung_intervals(tmp_path_factory: pytest.TempPathFactory) -> list[tuple[float, float]]:
    """(reported, true) interval error in cents, for up to ten leaps per singer.

    A leap is two consecutive notes of at least 0.6 s, at most 0.3 s apart,
    that land on different tempered notes.
    """
    _root()
    working = tmp_path_factory.mktemp("csd-intervals")
    results = []
    for piece, section, singer in TRACKS:
        notes = _section_notes(piece, section)
        taken = 0
        for (start1, hz1, length1), (start2, hz2, length2) in zip(
            notes[:-1], notes[1:], strict=True
        ):
            if taken == 10:
                break
            if length1 < 0.6 or length2 < 0.6 or start2 - (start1 + length1) > 0.3:
                continue
            from_midi, to_midi = (float(np.round(m)) for m in hz_to_midi(np.array([hz1, hz2])))
            if from_midi == to_midi:
                continue
            clip = _clip(piece, section, singer, start1, start2 + length2, working / "leap.wav")
            reported = score_interval(clip, from_midi, to_midi)["interval_error_cents"]
            first = _annotated_centre(piece, section, singer, start1, start1 + length1, 0.2)
            second = _annotated_centre(piece, section, singer, start2, start2 + length2, 0.2)
            sung = float(np.median(second)) - float(np.median(first))
            results.append((reported, 100.0 * (sung - (to_midi - from_midi))))
            taken += 1
    return results


def test_interval_scores_match_the_hand_corrected_leap(
    sung_intervals: list[tuple[float, float]],
) -> None:
    """The practice score of a real sung leap, against the annotated one.

    score_interval splits the attempt at the largest frame-to-frame pitch
    move. A legato singer glides into the second note over many frames, so
    a vibrato swing inside the first note can be the larger move and the
    split lands in the wrong place, and a correctly sung leap is reported
    hundreds of cents off. It is rare -- 3 of 401 leaps in a wider sample;
    none of the 463 sampled here, where 98.9% land within 25 cents of the
    truth -- and pinned so it cannot become common.
    """
    assert len(sung_intervals) > 300
    assert all(reported is not None for reported, _ in sung_intervals)
    deviations = np.array([abs(reported - truth) for reported, truth in sung_intervals])

    assert float(np.median(deviations)) < 6.5
    assert float(np.mean(deviations <= 25.0)) > 0.97
    assert float(np.mean(deviations > 100.0)) < 0.01

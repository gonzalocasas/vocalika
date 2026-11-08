from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf
from open_data import (
    DATA_ROOT,
    dataset_root,
    extract_clean,
    frame_errors,
    hz_to_midi,
    load_mono,
    octave_error_share,
)

from vocalika.analysis.alignment import align_pitch_tracks
from vocalika.analysis.comparison import ComparisonResult, compare_alignment
from vocalika.analysis.pitch import PitchTrack
from vocalika.audio.decode import decode_for_analysis
from vocalika.practice.notes import segment_notes
from vocalika.practice.scoring import score_held_note, verdict_for

pytestmark = pytest.mark.open_data

VOCADITO_BASELINE_PATH = Path(__file__).parent / "vocadito_pitch_baseline.csv"
with VOCADITO_BASELINE_PATH.open(newline="", encoding="utf-8") as _source:
    VOCADITO_BASELINE = {int(row["track_id"]): row for row in csv.DictReader(_source)}

# Tolerances applied to the recorded per-track baseline. They are wide enough to
# absorb numerical drift across torch builds and CPUs -- RMVPE is not
# bit-exact between them -- while still failing on a genuine accuracy
# regression. Regenerate the baseline after an intended change with:
#     uv run python tests/integration/test_open_datasets.py
CENTS_TOLERANCE_FACTOR = 1.5
CENTS_TOLERANCE_FLOOR = 3.0
WITHIN_50_TOLERANCE = 0.08
FRAMES_TOLERANCE_FACTOR = 0.8
# The mean is only stable on tracks free of octave errors, so it carries a
# looser factor and is asserted only for those. It exists to catch a regression
# in the error tail, which the median cannot see.
MEAN_CENTS_TOLERANCE_FACTOR = 1.4
VOICING_RECALL_TOLERANCE = 0.03

# Tracks on which the pitch track makes a few octave errors -- under 1% of
# frames on each, against up to ~8% on the pyin it replaced. Kept as an
# explicit set so a regression names the tracks it spreads to.
VOCADITO_OCTAVE_ERROR_TRACKS = {5, 6, 33, 34, 40}


@dataclass(frozen=True)
class VocaditoMeasurement:
    track_id: int
    frames: int
    median_cents: float
    mean_cents: float
    within_50: float
    within_25: float
    octave_errors: float
    voicing_recall: float


def _vocadito_track(root: Path, track_id: int) -> PitchTrack:
    """One track through the production reference path, exactly as a song gets it.

    Second-voice search included, which on a solo recording must change nothing.
    """
    return extract_clean(load_mono(root / "Audio" / f"vocadito_{track_id}.wav"))


def _vocadito_f0(root: Path, track_id: int) -> tuple[np.ndarray, np.ndarray]:
    annotation = np.loadtxt(
        root / "Annotations" / "F0" / f"vocadito_{track_id}_f0.csv", delimiter=","
    )
    return annotation[:, 0], annotation[:, 1]


def _measure_vocadito_track(
    arguments: tuple[Path, int], track: PitchTrack | None = None
) -> VocaditoMeasurement:
    """Score one track against the published F0."""
    root, track_id = arguments
    track = track if track is not None else _vocadito_track(root, track_id)
    cents_error, voicing_recall = frame_errors(track, *_vocadito_f0(root, track_id))
    return VocaditoMeasurement(
        track_id=track_id,
        frames=int(cents_error.size),
        median_cents=float(np.median(cents_error)),
        mean_cents=float(np.mean(cents_error)),
        within_50=float(np.mean(cents_error <= 50.0)),
        within_25=float(np.mean(cents_error <= 25.0)),
        octave_errors=octave_error_share(cents_error),
        voicing_recall=voicing_recall,
    )


@pytest.fixture(scope="session")
def vocadito_tracks() -> dict[int, PitchTrack]:
    """Every vocadito track's pitch, extracted once for the whole session.

    RMVPE runs the full 13.6 minutes of audio in well under a minute, so
    tracks are extracted in turn.
    """
    root = dataset_root("vocadito")
    return {track_id: _vocadito_track(root, track_id) for track_id in sorted(VOCADITO_BASELINE)}


@pytest.fixture(scope="session")
def vocadito_measurements(vocadito_tracks: dict[int, PitchTrack]) -> dict[int, VocaditoMeasurement]:
    root = dataset_root("vocadito")
    return {
        track_id: _measure_vocadito_track((root, track_id), track)
        for track_id, track in vocadito_tracks.items()
    }


@pytest.mark.parametrize("track_id", sorted(VOCADITO_BASELINE))
def test_vocadito_pitch_matches_frame_level_f0(
    track_id: int,
    vocadito_measurements: dict[int, VocaditoMeasurement],
) -> None:
    """Every track must stay within tolerance of its recorded accuracy.

    Keying off the median rather than the mean keeps the bar meaningful on the
    tracks where a few octave errors dominate the average.
    """
    measured = vocadito_measurements[track_id]
    baseline = VOCADITO_BASELINE[track_id]

    frames_floor = int(float(baseline["frames"]) * FRAMES_TOLERANCE_FACTOR)
    cents_ceiling = float(baseline["median_cents"]) * CENTS_TOLERANCE_FACTOR + CENTS_TOLERANCE_FLOOR
    within_50_floor = float(baseline["within_50"]) - WITHIN_50_TOLERANCE

    assert measured.frames >= frames_floor
    assert measured.median_cents <= cents_ceiling
    assert measured.within_50 >= within_50_floor
    # Recorded but long unasserted: a stricter voicing gate would pass every
    # other bar here while silently dropping sung frames.
    assert measured.voicing_recall >= float(baseline["voicing_recall"]) - VOICING_RECALL_TOLERANCE
    if track_id not in VOCADITO_OCTAVE_ERROR_TRACKS:
        assert measured.mean_cents <= float(baseline["mean_cents"]) * MEAN_CENTS_TOLERANCE_FACTOR


def test_vocadito_accuracy_holds_across_the_whole_dataset(
    vocadito_measurements: dict[int, VocaditoMeasurement],
) -> None:
    """Dataset-wide bars over 40 tracks, 29 singers, and 9 languages."""
    measurements = list(vocadito_measurements.values())
    median_cents = np.array([m.median_cents for m in measurements])
    within_50 = np.array([m.within_50 for m in measurements])
    within_25 = np.array([m.within_25 for m in measurements])

    # Bars sit roughly 20-35% off the recorded baseline: far outside the drift
    # numerical differences produce, well inside a real regression. For
    # scale, pyin measured 9.8 / 16.0 / 0.937 / 0.839 / 0.810 on these.
    assert len(measurements) == 40
    assert float(np.median(median_cents)) < 4.0
    assert float(np.max(median_cents)) < 8.0
    assert float(np.median(within_50)) > 0.97
    assert float(np.min(within_50)) > 0.92
    assert float(np.median(within_25)) > 0.93
    # Every track must contribute enough confident frames to be meaningful.
    assert min(m.frames for m in measurements) >= 400


def test_vocadito_octave_errors_stay_confined_to_known_tracks(
    vocadito_measurements: dict[int, VocaditoMeasurement],
) -> None:
    """Pin the residual octave errors so they cannot spread silently.

    The worst track (33) errs on about 1% of frames. Under pyin, track 34
    tracked a sub-harmonic for long enough to push its mean error to 87 cents.
    """
    affected = {
        track_id
        for track_id, measurement in vocadito_measurements.items()
        if measurement.octave_errors > 0.0
    }
    assert affected <= VOCADITO_OCTAVE_ERROR_TRACKS, (
        f"octave errors appeared on new tracks: {sorted(affected - VOCADITO_OCTAVE_ERROR_TRACKS)}"
    )
    for track_id in affected:
        assert vocadito_measurements[track_id].octave_errors < 0.02
    unaffected = [
        measurement
        for track_id, measurement in vocadito_measurements.items()
        if track_id not in VOCADITO_OCTAVE_ERROR_TRACKS
    ]
    assert max(measurement.mean_cents for measurement in unaffected) < 30.0


def _mast_track(root: Path, stem: str) -> PitchTrack:
    f0_path = root / "f0data_crepe" / "MAST_melody_f0" / f"{stem}.f0.npy"
    frequency = np.asarray(np.load(f0_path, allow_pickle=False), dtype=np.float64)
    voiced = np.isfinite(frequency) & (frequency > 0.0)
    midi = np.full_like(frequency, np.nan)
    midi[voiced] = 69.0 + 12.0 * np.log2(frequency[voiced] / 440.0)
    return PitchTrack(
        times=np.arange(frequency.size, dtype=np.float64) * 0.01,
        raw_frequency_hz=frequency,
        raw_midi=midi.copy(),
        midi=midi,
        confidence=voiced.astype(np.float64),
        voiced=voiced,
        extractor="MAST-published-CREPE",
        sample_rate=8_000,
        hop_length=80,
    )


def _mast_comparison(root: Path, performance_stem: str) -> ComparisonResult:
    reference_stem = performance_stem.replace("_per", "_ref", 1)
    alignment = align_pitch_tracks(
        _mast_track(root, reference_stem),
        _mast_track(root, performance_stem),
    )
    return compare_alignment(alignment)


def _mast_unanimous_score(root: Path, performance_stem: str) -> float:
    annotations = root / "annotations" / "annotations.csv"
    with annotations.open(newline="", encoding="utf-8") as source:
        for row in csv.DictReader(source):
            if Path(row["file"]).stem == performance_stem:
                assert row["fullAgree"] == "True"
                return float(row["fullAgree_score"])
    raise AssertionError(f"MAST annotation is missing for {performance_stem}")


def test_mast_expert_ratings_separate_perfect_and_completely_off_performances() -> None:
    root = dataset_root("mast-melody")
    completely_off_stem = "59_mel1_per160759"
    perfect_stem = "55_mel1_per172159"

    assert _mast_unanimous_score(root, completely_off_stem) == 1.0
    assert _mast_unanimous_score(root, perfect_stem) == 4.0

    completely_off = _mast_comparison(root, completely_off_stem)
    perfect = _mast_comparison(root, perfect_stem)

    assert perfect.relative_mean_absolute_error_cents < 50.0
    assert perfect.relative_within_50_percent > 75.0
    assert completely_off.relative_mean_absolute_error_cents > 100.0
    assert perfect.relative_mean_absolute_error_cents < (
        completely_off.relative_mean_absolute_error_cents / 3.0
    )


def test_mast_unanimous_ratings_rank_across_the_paired_dataset() -> None:
    root = dataset_root("mast-melody")
    f0_root = root / "f0data_crepe" / "MAST_melody_f0"
    annotations = root / "annotations" / "annotations.csv"
    scores: dict[int, list[float]] = {1: [], 4: []}

    with annotations.open(newline="", encoding="utf-8") as source:
        for row in csv.DictReader(source):
            if row["fullAgree_score"] not in {"1.0", "4.0"}:
                continue
            performance_stem = Path(row["file"]).stem
            if "_per" not in performance_stem:
                continue
            reference_stem = performance_stem.replace("_per", "_ref", 1)
            if not (f0_root / f"{reference_stem}.f0.npy").is_file():
                continue
            score = int(float(row["fullAgree_score"]))
            comparison = _mast_comparison(root, performance_stem)
            scores[score].append(comparison.relative_mean_absolute_error_cents)

    completely_off = np.asarray(scores[1])
    perfect = np.asarray(scores[4])
    pairwise_ranking_accuracy = float(
        np.mean(perfect[:, np.newaxis] < completely_off[np.newaxis, :])
    )

    assert completely_off.size == 197
    assert perfect.size == 192
    assert np.median(perfect) < 40.0
    assert np.median(completely_off) > 120.0
    assert pairwise_ranking_accuracy > 0.96


def test_mast_melodic_motion_regression_case_aligns_correctly() -> None:
    root = dataset_root("mast-melody")

    comparison = _mast_comparison(root, "55_mel2_per161659")

    assert comparison.relative_mean_absolute_error_cents < 50.0
    assert comparison.relative_within_50_percent > 75.0


def test_mast_ratings_rank_takes_measured_by_vocalika(tmp_path: Path) -> None:
    """The expert-rating benchmark again, with each sung take measured by Vocalika.

    The tests above score MAST's published CREPE tracks, which checks
    alignment and comparison but not the extractor. Here every performance
    goes through the take path from its 8 kHz recording. The references stay
    on the published track: they are piano, and Vocalika's references are
    always a voice -- RMVPE, trained on singing, keeps only a fifth to a half
    of a piano's frames, which is out of scope rather than a regression.
    Measured: pairwise ranking accuracy 0.980, medians 32 and 136 cents.
    """
    root = dataset_root("mast-melody")
    f0_root = root / "f0data_crepe" / "MAST_melody_f0"
    audio_root = root / "audioFiles" / "MAST_melody_audio"
    annotations = root / "annotations" / "annotations.csv"
    scores: dict[int, list[float]] = {1: [], 4: []}

    with annotations.open(newline="", encoding="utf-8") as source:
        rows = list(csv.DictReader(source))
    for row in rows:
        if row["fullAgree_score"] not in {"1.0", "4.0"}:
            continue
        performance_stem = Path(row["file"]).stem
        if "_per" not in performance_stem:
            continue
        reference_stem = performance_stem.replace("_per", "_ref", 1)
        if not (f0_root / f"{reference_stem}.f0.npy").is_file():
            continue
        decoded = decode_for_analysis(audio_root / f"{performance_stem}.m4a", tmp_path / "take.wav")
        performance = extract_clean(load_mono(decoded), "single")
        comparison = compare_alignment(
            align_pitch_tracks(_mast_track(root, reference_stem), performance)
        )
        scores[int(float(row["fullAgree_score"]))].append(
            comparison.relative_mean_absolute_error_cents
        )

    completely_off = np.asarray(scores[1])
    perfect = np.asarray(scores[4])
    pairwise_ranking_accuracy = float(
        np.mean(perfect[:, np.newaxis] < completely_off[np.newaxis, :])
    )
    assert completely_off.size == 197
    assert perfect.size == 192
    assert np.median(perfect) < 40.0
    assert np.median(completely_off) > 120.0
    assert pairwise_ranking_accuracy > 0.96


def _vocadito_notes(root: Path, track_id: int, annotator: str) -> list[tuple[float, float, float]]:
    """One annotator's notes as (start, end, MIDI)."""
    rows = np.loadtxt(
        root / "Annotations" / "Notes" / f"vocadito_{track_id}_notes{annotator}.csv",
        delimiter=",",
        ndmin=2,
    )
    return [
        (start, start + length, float(hz_to_midi(np.array([hz]))[0])) for start, hz, length in rows
    ]


def _matched_cents(
    note: tuple[float, float, float], candidates: list[tuple[float, float, float]]
) -> float | None:
    """Cents from ``note`` to the candidate covering most of it, if one covers over half."""
    start, end, midi = note
    best: tuple[float, float] | None = None
    for other_start, other_end, other_midi in candidates:
        overlap = min(end, other_end) - max(start, other_start)
        if overlap > 0.5 * (end - start) and (best is None or overlap > best[0]):
            best = (overlap, other_midi)
    return None if best is None else 100.0 * (midi - best[1])


def _note_agreement(
    found: list[tuple[float, float, float]], annotated: list[tuple[float, float, float]]
) -> tuple[list[bool], list[bool], list[float]]:
    """Per found note: a real note at its pitch? Per long annotated note: found? And cents."""
    found_hits, cents = [], []
    for note in found:
        error = _matched_cents(note, annotated)
        found_hits.append(error is not None and abs(error) <= 50.0)
        if error is not None:
            cents.append(abs(error))
    long_notes = [note for note in annotated if note[1] - note[0] >= 0.5]
    recalled = []
    for note in long_notes:
        error = _matched_cents(note, found)
        recalled.append(error is not None and abs(error) <= 50.0)
    return found_hits, recalled, cents


def test_vocadito_practice_notes_agree_with_human_transcriptions(
    vocadito_tracks: dict[int, PitchTrack],
) -> None:
    """The notes offered for practice are real notes, at the pitch a transcriber heard.

    Vocadito has two independent note transcriptions; the second annotator,
    scored against the first the same way, shows what agreement between
    people looks like. segment_notes is deliberately conservative -- it wants
    whole notes steady enough to practise -- so it is held to human
    precision and pitch but finds fewer of the annotated notes. Measured over
    314 notes: 96% are real and within 2.0 cents (median) of the
    transcription, against 94% for the second annotator; it recovers 70% of
    the 209 notes of 0.5 s or longer, against 95% for the second annotator.
    """
    root = dataset_root("vocadito")
    found_hits: list[bool] = []
    recalled: list[bool] = []
    cents: list[float] = []
    human_hits: list[bool] = []
    human_recalled: list[bool] = []
    for track_id, track in vocadito_tracks.items():
        first = _vocadito_notes(root, track_id, "A1")
        found = [
            (note.start_seconds, note.end_seconds, note.midi)
            for note in segment_notes(track.times, track.midi)
        ]
        hits, recall, errors = _note_agreement(found, first)
        found_hits += hits
        recalled += recall
        cents += errors
        hits, recall, _ = _note_agreement(_vocadito_notes(root, track_id, "A2"), first)
        human_hits += hits
        human_recalled += recall

    precision = float(np.mean(found_hits))
    human_precision = float(np.mean(human_hits))
    assert len(found_hits) > 250
    assert precision > 0.92
    assert precision > human_precision - 0.03
    assert float(np.median(cents)) < 3.0
    assert float(np.mean(recalled)) > 0.62
    assert float(np.mean(human_recalled)) > 0.9


def test_vocadito_held_notes_score_as_the_annotation_does(tmp_path: Path) -> None:
    """The practice score of notes both transcribers agree on, sung by 29 amateurs.

    A note counts when both annotators mark it, at least 0.8 s long, within
    20 cents of each other. Its true centre and steadiness come from the
    published F0 with the same 15% onset and release trim the scorer applies.
    Measured over 55 notes: centre within 1.1 cents of the truth (median; 4.9
    worst), and the verdict the annotation implies on 91% -- the rest on a
    verdict boundary.
    """
    root = dataset_root("vocadito")
    centre_errors, steadiness_errors, agreement = [], [], []
    for track_id in sorted(VOCADITO_BASELINE):
        first = _vocadito_notes(root, track_id, "A1")
        second = _vocadito_notes(root, track_id, "A2")
        times, frequency = _vocadito_f0(root, track_id)
        audio, rate = sf.read(root / "Audio" / f"vocadito_{track_id}.wav")
        for note in first:
            start, end, midi = note
            if end - start < 0.8:
                continue
            other = _matched_cents(note, second)
            if other is None or abs(other) > 20.0:
                continue
            inside = (times >= start) & (times < end) & (frequency > 0.0)
            values = hz_to_midi(frequency[inside])
            margin = int(values.size * 0.15)
            core = values[margin : values.size - margin]
            if core.size < 20:
                continue
            target = float(np.round(midi))
            clip = tmp_path / "note.wav"
            sf.write(clip, audio[int(start * rate) : int(end * rate)], rate)
            score = score_held_note(clip, target)
            centre = float(np.median(core))
            true_centre = 100.0 * (centre - target)
            true_steadiness = 100.0 * float(np.mean(np.abs(core - centre)))
            if score.centre_cents is None:
                centre_errors.append(float("inf"))
                continue
            centre_errors.append(abs(score.centre_cents - true_centre))
            steadiness_errors.append(abs(score.steadiness_cents - true_steadiness))
            agreement.append(score.verdict == verdict_for(true_centre, true_steadiness))

    centre = np.asarray(centre_errors)
    assert centre.size > 50
    assert float(np.median(centre)) < 2.0
    assert float(np.max(centre)) < 10.0
    assert float(np.percentile(steadiness_errors, 90)) < 4.0
    assert float(np.mean(agreement)) > 0.85


def _write_vocadito_baseline() -> None:
    """Re-measure every Vocadito track and overwrite the recorded baseline."""
    root = DATA_ROOT / "vocadito"
    with VOCADITO_BASELINE_PATH.open(newline="", encoding="utf-8") as source:
        rows = list(csv.DictReader(source))
    for row in rows:
        measured = _measure_vocadito_track((root, int(row["track_id"])))
        row.update(
            frames=measured.frames,
            median_cents=round(measured.median_cents, 2),
            mean_cents=round(measured.mean_cents, 2),
            within_50=round(measured.within_50, 4),
            within_25=round(measured.within_25, 4),
            octave_errors=round(measured.octave_errors, 4),
            voicing_recall=round(measured.voicing_recall, 4),
        )
        print(row, flush=True)
    with VOCADITO_BASELINE_PATH.open("w", newline="", encoding="utf-8") as target:
        writer = csv.DictWriter(target, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    _write_vocadito_baseline()

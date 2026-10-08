from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np
import soundfile as sf

from vocalika.api.lyrics import build_lyrics_timing
from vocalika.cache.manager import CacheManager
from vocalika.lyrics.alignment import (
    WordTiming,
    align_lyrics,
    is_section_label,
    parse_lyrics,
    spell,
)
from vocalika.lyrics.lrclib import rank_candidates
from vocalika.projects.models import Project, ProjectReference


class FakeAligner:
    """Places word n at n seconds, and records what it was asked to align."""

    name = "fake"

    def __init__(self) -> None:
        self.calls: list[tuple[list[str], set[int]]] = []

    def align(self, audio_path: Path, words: list[str], line_breaks: set[int]) -> list[WordTiming]:
        self.calls.append((words, line_breaks))
        return [WordTiming(start=float(i), end=i + 0.5, score=0.9) for i in range(len(words))]


def test_spelling_folds_accents_and_drops_what_the_model_cannot_spell() -> None:
    assert spell("Canción,") == "cancion"
    assert spell("Don’t") == "don't"
    assert spell("'cause") == "cause"
    assert spell("1984") == ""


def test_section_labels_are_told_apart_from_bracketed_singing() -> None:
    assert is_section_label("[Chorus]")
    assert is_section_label("[Verse 1]")
    assert is_section_label("[Father:]")
    assert is_section_label("Pre-Chorus:")
    assert not is_section_label("[you were only waiting for this moment to arrive]")
    assert not is_section_label("(Away, away, away)")
    assert not is_section_label("Chorus girls are dancing in the moonlight tonight")


def test_parsing_keeps_every_line_so_timings_index_the_typed_text() -> None:
    lines = parse_lyrics("[Verse 1]\nHello, world\n\n1984")

    assert [line.text for line in lines] == ["[Verse 1]", "Hello, world", "", "1984"]
    assert [line.sung for line in lines] == [False, True, False, False]
    assert [word.token for word in lines[1].words] == ["hello", "world"]


def test_alignment_maps_timings_back_onto_written_words() -> None:
    aligner = FakeAligner()

    result = align_lyrics(Path("vocal.wav"), "[Chorus]\nOne two\n\nThree 4 four", aligner)

    assert aligner.calls == [(["one", "two", "three", "four"], {0, 2})]
    lines = result["lines"]
    assert len(lines) == 4
    assert lines[0]["start"] is None
    assert (lines[1]["start"], lines[1]["end"]) == (0.0, 1.5)
    words = lines[3]["words"]
    assert [word["text"] for word in words] == ["Three", "4", "four"]
    assert [word["start"] for word in words] == [2.0, None, 3.0]
    assert (lines[3]["start"], lines[3]["end"]) == (2.0, 3.5)


def make_project(tmp_path: Path, lyrics: str) -> Project:
    vocal = tmp_path / "vocals.wav"
    sf.write(vocal, np.zeros(16_000, dtype=np.float32), 16_000)
    return Project(
        id="p1",
        title="Song - Artist",
        created_at="2026-10-08",
        updated_at="2026-10-08",
        reference=ProjectReference(
            title="Song",
            source_type="local",
            source_url=None,
            original_path=str(vocal),
            vocal_path=str(vocal),
            instrumental_path=None,
            duration_seconds=1.0,
            sample_rate=16_000,
            separation_model=None,
            separation_cached=False,
        ),
        lyrics=lyrics,
    )


def test_timing_is_cached_per_lyric_text(tmp_path: Path) -> None:
    cache = CacheManager(tmp_path / "cache")
    aligner = FakeAligner()
    project = make_project(tmp_path, "one two")

    first = build_lyrics_timing(project, cache, aligner=aligner)
    second = build_lyrics_timing(project, cache, aligner=aligner)
    build_lyrics_timing(replace(project, lyrics="one two three"), cache, aligner=aligner)

    assert first == second
    assert len(aligner.calls) == 2


def test_empty_lyrics_skip_the_aligner(tmp_path: Path) -> None:
    aligner = FakeAligner()

    project = make_project(tmp_path, "  \n")

    result = build_lyrics_timing(project, CacheManager(tmp_path / "cache"), aligner=aligner)

    assert result["lines"] == []
    assert aligner.calls == []


def test_lrclib_ranking_prefers_the_matching_song_over_a_closer_duration() -> None:
    rows = [
        {"id": 1, "trackName": "HV123 - GRAVITY", "artistName": "GRAVITY", "duration": 248.0,
         "plainLyrics": "karaoke text"},
        {"id": 2, "trackName": "Gravity", "artistName": "John Mayer", "duration": 245.0,
         "plainLyrics": "Gravity is working against me"},
        {"id": 3, "trackName": "Gravity", "artistName": "John Mayer", "duration": 246.0,
         "plainLyrics": "Gravity is working against me"},
        {"id": 4, "trackName": "Gravity", "artistName": "John Mayer", "duration": 245.0,
         "plainLyrics": None, "instrumental": True},
    ]

    ranked = rank_candidates(rows, "Gravity John Mayer", 248.0)

    assert [candidate.id for candidate in ranked] == [3, 1]

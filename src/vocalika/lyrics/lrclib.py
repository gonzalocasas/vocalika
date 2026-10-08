from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from difflib import SequenceMatcher
from typing import Any

from vocalika import __version__

LRCLIB_SEARCH_URL = "https://lrclib.net/api/search"
# LRCLIB asks clients to identify themselves so it can tell apps apart.
USER_AGENT = f"Vocalika/{__version__} (https://github.com/gonzalocasas/vocalika)"


class LyricsLookupError(RuntimeError):
    pass


@dataclass(frozen=True)
class LyricsCandidate:
    id: int
    track: str
    artist: str
    album: str | None
    duration_seconds: float | None
    lyrics: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _similarity(left: str, right: str) -> float:
    def clean(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()

    return SequenceMatcher(None, clean(left), clean(right)).ratio()


def rank_candidates(
    rows: list[dict[str, Any]],
    query: str,
    duration_seconds: float | None,
) -> list[LyricsCandidate]:
    """Order LRCLIB results by how likely they are this recording's lyrics.

    LRCLIB is crowd-sourced, so a search returns the album track next to
    karaoke uploads titled "HV123 - GRAVITY". Closest duration alone picks
    those as readily as the real one; the title and artist have to agree with
    the project too, and duration then only breaks near-ties between releases.
    """
    scored: list[tuple[float, LyricsCandidate]] = []
    for row in rows:
        text = (row.get("plainLyrics") or "").strip()
        if not text or row.get("instrumental"):
            continue
        track = str(row.get("trackName") or "")
        artist = str(row.get("artistName") or "")
        duration = row.get("duration")
        score = _similarity(f"{track} {artist}", query)
        if duration_seconds and duration:
            # A few seconds apart is the same song in another release; a
            # minute apart is a live version or a different song.
            score -= min(0.3, abs(float(duration) - duration_seconds) / 60)
        scored.append((
            score,
            LyricsCandidate(
                id=int(row["id"]),
                track=track,
                artist=artist,
                album=row.get("albumName") or None,
                duration_seconds=float(duration) if duration else None,
                lyrics=text,
            ),
        ))
    scored.sort(key=lambda item: item[0], reverse=True)
    # The same lyric is often uploaded once per album it appears on.
    unique: list[LyricsCandidate] = []
    seen: set[str] = set()
    for _, candidate in scored:
        key = re.sub(r"\s+", " ", candidate.lyrics.lower())
        if key not in seen:
            seen.add(key)
            unique.append(candidate)
    return unique


def search_lyrics(
    query: str,
    duration_seconds: float | None = None,
    *,
    limit: int = 6,
    timeout: float = 15.0,
) -> list[LyricsCandidate]:
    """Search LRCLIB, the open lyrics database, for a song's text."""
    # Project titles are "Song - Artist"; LRCLIB's free-text search matches
    # words, so the dash only gets in the way.
    cleaned = re.sub(r"\s+-\s+", " ", query).strip()
    if not cleaned:
        return []
    url = f"{LRCLIB_SEARCH_URL}?{urllib.parse.urlencode({'q': cleaned})}"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            rows = json.load(response)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
        raise LyricsLookupError(f"Could not reach LRCLIB: {error}") from error
    if not isinstance(rows, list):
        raise LyricsLookupError("LRCLIB returned an unexpected response.")
    return rank_candidates(rows, cleaned, duration_seconds)[:limit]

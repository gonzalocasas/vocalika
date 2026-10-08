from __future__ import annotations

import re
import threading
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import numpy as np
import soundfile as sf

ALIGNMENT_VERSION = 1

# Words that open a section label rather than a sung line, as lyric sites
# write them: "[Chorus]", "Verse 2:", "[Father:]".
_LABEL_WORDS = {
    "intro", "outro", "verse", "chorus", "pre-chorus", "prechorus", "post-chorus",
    "bridge", "hook", "refrain", "interlude", "instrumental", "solo", "break",
    "breakdown", "coda", "repeat", "spoken",
}


class LyricsAlignmentError(RuntimeError):
    pass


@dataclass(frozen=True)
class LyricWord:
    text: str
    """The word as written, punctuation included, for display."""
    token: str
    """Lowercase a-z and apostrophes: what the acoustic model can spell."""


@dataclass(frozen=True)
class LyricLine:
    text: str
    words: tuple[LyricWord, ...]
    sung: bool


@dataclass(frozen=True)
class WordTiming:
    start: float
    end: float
    score: float


def spell(word: str) -> str:
    """Reduce a written word to the alphabet the aligner was trained on.

    Accents are folded rather than dropped, so "canción" is aligned as
    "cancion" instead of "cancin". Digits and other scripts have no spelling
    here and come back empty; those words stay on screen, just untimed.
    """
    folded = unicodedata.normalize("NFKD", word.lower())
    folded = "".join(char for char in folded if not unicodedata.combining(char))
    folded = folded.replace("’", "'").replace("‘", "'")
    return re.sub(r"[^a-z']", "", folded).strip("'")


def is_section_label(line: str) -> bool:
    """Whether a lyric line names a section instead of being sung.

    Brackets alone do not decide it: lyric sites also bracket sung backing
    lines ("[you were only waiting for this moment to arrive]"). A label is
    short, or ends in a colon, or opens with a word like "chorus".
    """
    stripped = line.strip()
    inner = stripped
    bracketed = stripped.startswith("[") and stripped.endswith("]")
    if bracketed:
        inner = stripped[1:-1].strip()
    words = inner.split()
    if not words:
        return bracketed
    first = re.sub(r"[^a-z-]", "", words[0].lower())
    if first in _LABEL_WORDS and len(words) <= 4:
        return True
    if inner.endswith(":") and len(words) <= 4:
        return True
    return bracketed and len(words) <= 2


def parse_lyrics(text: str) -> list[LyricLine]:
    """Split lyrics into lines and words, keeping every line for display.

    Blank lines and section labels are kept, marked unsung, so the timed
    result lines up index for index with the text the singer typed.
    """
    lines: list[LyricLine] = []
    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped or is_section_label(stripped):
            lines.append(LyricLine(text=stripped, words=(), sung=False))
            continue
        words = tuple(LyricWord(text=word, token=spell(word)) for word in stripped.split())
        lines.append(LyricLine(text=stripped, words=words, sung=any(word.token for word in words)))
    return lines


class LyricsAligner(Protocol):
    name: str

    def align(self, audio_path: Path, words: list[str], line_breaks: set[int]) -> list[WordTiming]:
        """Time each spelled word; `line_breaks` holds the word indices that open a line."""
        ...


class MmsLyricsAligner:
    """CTC forced alignment with Meta's multilingual MMS model, via torchaudio.

    Alignment, not transcription: the words are known, so the model only has
    to say *when* each is sung. That stays reliable on singing, where
    transcribing the same audio would mishear held vowels and melisma.
    """

    name = "mms_fa"
    sample_rate = 16000
    # wav2vec2 attends over the whole input at once, so a full song does not
    # fit in memory. Each window sees a little audio either side so words cut
    # by the boundary are still heard whole.
    window_seconds = 30.0
    context_seconds = 2.0
    line_wildcards = True

    _model: Any = None
    _lock = threading.Lock()

    def _load(self) -> Any:
        with MmsLyricsAligner._lock:
            if MmsLyricsAligner._model is None:
                try:
                    from torchaudio.pipelines import MMS_FA
                except ImportError as error:
                    raise LyricsAlignmentError(
                        "Lyric timing needs torchaudio. Run `uv sync --extra real-input`."
                    ) from error
                MmsLyricsAligner._model = MMS_FA.get_model(with_star=True).eval()
            return MmsLyricsAligner._model

    def _read(self, audio_path: Path) -> Any:
        import torch
        import torchaudio

        audio, rate = sf.read(str(audio_path), dtype="float32", always_2d=True)
        wave = torch.from_numpy(np.ascontiguousarray(audio.mean(axis=1)))
        return torchaudio.functional.resample(wave, int(rate), self.sample_rate)

    def _emission(self, wave: Any) -> Any:
        import torch

        model = self._load()
        window = int(self.window_seconds * self.sample_rate)
        context = int(self.context_seconds * self.sample_rate)
        pieces = []
        with torch.inference_mode():
            for start in range(0, wave.numel(), window):
                low = max(0, start - context)
                high = min(wave.numel(), start + window + context)
                emission, _ = model(wave[low:high].unsqueeze(0))
                frames_per_sample = emission.shape[1] / (high - low)
                first = round((start - low) * frames_per_sample)
                last = first + round(min(window, wave.numel() - start) * frames_per_sample)
                pieces.append(emission[0, first:last])
        return torch.cat(pieces).unsqueeze(0)

    def align(self, audio_path: Path, words: list[str], line_breaks: set[int]) -> list[WordTiming]:
        import torch
        import torchaudio
        from torchaudio.pipelines import MMS_FA

        dictionary = MMS_FA.get_dict(star="*")
        star = dictionary["*"]
        wave = self._read(audio_path)
        if wave.numel() < self.sample_rate:
            raise LyricsAlignmentError("The reference vocal is too short to time lyrics against.")
        emission = self._emission(wave)

        # A wildcard before every line gives singing that is not in the text
        # -- an ad-lib, a repeat the lyric sheet leaves out -- somewhere to go,
        # instead of dragging the neighbouring words onto it.
        tokens: list[int] = []
        owners: list[int] = []
        for index, word in enumerate(words):
            if self.line_wildcards and index in line_breaks:
                tokens.append(star)
                owners.append(-1)
            for char in word:
                tokens.append(dictionary[char])
                owners.append(index)
        if self.line_wildcards:
            tokens.append(star)
            owners.append(-1)
        if len(tokens) > emission.shape[1]:
            raise LyricsAlignmentError("The lyrics are longer than the vocal can hold.")

        aligned, scores = torchaudio.functional.forced_align(
            emission, torch.tensor([tokens], dtype=torch.int32), blank=0
        )
        spans = torchaudio.functional.merge_tokens(aligned[0], scores[0].exp())
        seconds_per_frame = wave.numel() / self.sample_rate / emission.shape[1]

        starts: dict[int, float] = {}
        ends: dict[int, float] = {}
        totals: dict[int, list[float]] = {}
        for span, owner in zip(spans, owners, strict=True):
            if owner < 0:
                continue
            starts.setdefault(owner, span.start * seconds_per_frame)
            ends[owner] = span.end * seconds_per_frame
            totals.setdefault(owner, []).append(float(span.score))
        return [
            WordTiming(
                start=round(starts[index], 3),
                end=round(ends[index], 3),
                score=round(float(np.mean(totals[index])), 3),
            )
            for index in range(len(words))
        ]


def align_lyrics(audio_path: Path, lyrics: str, aligner: LyricsAligner) -> dict[str, Any]:
    """Time every sung word of `lyrics` against an isolated vocal.

    The result keeps one entry per line of the input, so a client can render
    the text exactly as typed and look timings up by position. Lines with
    nothing to align -- blanks, section labels, words in another script --
    carry null times.
    """
    lines = parse_lyrics(lyrics)
    spelled: list[str] = []
    line_breaks: set[int] = set()
    for line in lines:
        first = True
        for word in line.words:
            if not word.token:
                continue
            if first:
                line_breaks.add(len(spelled))
                first = False
            spelled.append(word.token)
    timings = aligner.align(audio_path, spelled, line_breaks) if spelled else []

    cursor = 0
    payload_lines: list[dict[str, Any]] = []
    for line in lines:
        payload_words: list[dict[str, Any]] = []
        for word in line.words:
            timing = None
            if word.token:
                timing = timings[cursor]
                cursor += 1
            payload_words.append({
                "text": word.text,
                "start": timing.start if timing else None,
                "end": timing.end if timing else None,
                "score": timing.score if timing else None,
            })
        timed = [word for word in payload_words if word["start"] is not None]
        payload_lines.append({
            "text": line.text,
            "sung": line.sung,
            "start": timed[0]["start"] if timed else None,
            "end": timed[-1]["end"] if timed else None,
            "words": payload_words,
        })
    return {"version": ALIGNMENT_VERSION, "aligner": aligner.name, "lines": payload_lines}

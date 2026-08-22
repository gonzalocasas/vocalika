# Vocalika

Vocalika is a web application for comparing a singer's performance with a
reference recording. It focuses on measurable pitch and timing
differences rather than subjective scoring.

The audio-analysis core follows the original
[product requirements](docs/PRD-001-MVP.md). The project/take workspace and its
feature boundaries are documented in
[feature architecture](docs/FEATURE_ARCHITECTURE.md).

## Status

The application now combines continuous pitch extraction and temporal alignment
with persistent reference projects, reusable vocal/instrumental stems, uploaded
or browser-recorded takes, plain-text lyrics, aligned diagnostics, and
synchronized playback and mix export.

## Development setup

Requirements:

- macOS on Apple Silicon (the initial target)
- Python 3.12
- `uv`
- Node.js and npm
- ffmpeg and ffprobe

```bash
uv sync --extra dev
npm --prefix frontend install
npm --prefix frontend run build
```

Install real-input support and explicitly fetch the source-separation model:

```bash
uv sync --extra dev --extra real-input
uv run vocalika setup-models
```

Analyze a full local mix and an Ableton FLAC:

```bash
uv run vocalika analyze \
  --reference ./reference-mix.mp3 \
  --performance ./ableton-take.flac \
  --output ./analysis-output

uv run vocalika plot ./analysis-output/analysis.json
uv run vocalika serve
```

Or use a public YouTube reference directly:

```bash
uv run vocalika analyze \
  --reference "https://www.youtube.com/watch?v=..." \
  --performance ./ableton-take.flac \
  --isolate-performance \
  --output ./analysis-output
```

If the reference is already an isolated vocal, bypass source separation:

```bash
uv run vocalika analyze \
  --reference ./reference-vocal.wav \
  --reference-is-vocal \
  --reference-mix ./original-reference.mp3 \
  --performance ./ableton-take.flac \
  --output ./analysis-output

uv run vocalika plot ./analysis-output/analysis.json
uv run vocalika serve
```

Then open <http://127.0.0.1:8000>. Original source files are never modified.
Working audio and large pitch arrays live beside the generated analysis JSON.
`--output` accepts either an output directory or an explicit `.json` artifact
path.

The web interface is project-centric. Create one project from a reference file
or public YouTube URL; Vocalika stores the source and reusable stems below
`analysis-output/projects/<project-id>/`. Each uploaded or microphone-recorded
take belongs to that project and stores its own analysis. Project lyrics are
plain text that can be pasted once and kept visible while recording. Browser
recording uses the best Opus container supported by the browser and follows the
same upload/analysis path as any other take.

The Reference transpose control renders duration-preserving pitch-shifted stems
on demand. Preview and recording playback use the selected key, and each new
take remembers that setting for analysis, comparison playback, and export.

The Export tab places the selected take on the reference timeline using the
analysis correspondence, mixes it with the isolated instrumental at an
adjustable level, and provides a short preview or MP3/WAV/FLAC download.
Browser-recorded WebM/Opus takes are decoded through ffmpeg during mixdown.

The older standalone CLI analysis and artifact-library endpoints remain
available for scripts and compatibility. A positional artifact remains optional,
so `vocalika serve ./analysis-output/example/analysis.json` still loads that
artifact through the legacy API.

If a performance contains instruments, enable **Isolate my vocal from
instruments before analysis** in the web form or pass `--isolate-performance`
to the CLI. Vocalika analyzes the separated vocal stem, retains the uploaded mix
for listening, and caches the separation for subsequent runs.

To make the server available on a trusted network, bind it to all interfaces:

```bash
uv run vocalika serve --host 0.0.0.0
```

This development server does not include authentication, so do not expose it to
the public internet as-is.

## Pitch metrics

Vocalika first estimates a global performance-versus-reference displacement.
It compares direct audio cross-correlation, phonetic/spectral-change matching,
and a smoothed vocal-energy-envelope fallback. Spectral changes help distinguish
different lyrics sung to a repeated melody, while the energy envelope can still
locate a short performance inside a longer reference when timbres differ.
High-confidence offsets are applied before the pitch-DTW stage, preventing
leading silence or omitted instrumental sections from causing unrelated phrases
to be paired. The artifact records every candidate plus the chosen method,
detected offset, correlation confidence, peak uniqueness, and whether the offset
was applied.

Vocalika reports two complementary error families:

- **Contour MAE** compares all confident aligned pitch frames, including
  transitions, scoops, and other pitch movement.
- **Stable-note center MAE** detects sustained reference regions, rejects
  regions with inadequate performance coverage or implausible time warping,
  and compares median pitch centers. The artifact records the number and total
  duration of included regions so a small subset is not mistaken for a general
  score.

Both are available in absolute mode and with global transposition compensated
in relative mode. The graphs render a lightly median-smoothed display contour,
bridge only unobserved gaps up to 120 ms, and leave longer unvoiced passages
open. Stable-note pitch centers appear as thick bars inside the lightly green
regions. The aligned-contour chart can also overlay simplified vertical-line
envelopes from the isolated reference and performance vocals; toggle **Vocal
waveforms**, **Reference**, or **Mine** to isolate the desired layers. The linked
confidence chart shows each
track's independent pYIN voicing probability, the configured acceptance
threshold, and the mutually accepted comparison frames. Enable **Accepted frame
points** to inspect the individual measurements used by the contours.
During listening, a shared playhead crosses the pitch, confidence, and error
charts and remains synchronized when the charts are zoomed.

Use **Metric scope → Selected range** to recalculate the cards for the current
chart zoom or listening From/To range. Local absolute metrics use only confident
paired frames inside that reference-time interval; local relative metrics also
recenter on the interval's own median pitch bias.

## Models and cache

pYIN pitch extraction does not require learned model parameters. Vocalika first
uses harmonic/percussive separation to give pYIN a harmonic-only analysis signal;
the listening audio is unchanged. Demucs uses a pretrained source-separation
model; `vocalika setup-models` downloads its weights explicitly before the first
analysis.

YouTube audio, normalized working audio, Demucs stems, and compatible cleaned
pitch tracks are cached locally. Cache keys include input content, processing
parameters, model versions, and pipeline version where relevant.

```bash
uv run vocalika cache-path
uv run vocalika cache-clear
```

Use `--refresh-cache` on `vocalika analyze` to recompute compatible entries, or
`--cache-directory` to choose a different cache root.

## Quality checks

```bash
uv run ruff check src tests
uv run ruff format --check src tests
uv run mypy
uv run pytest
npm --prefix frontend run build
npm --prefix frontend test
```

The repository also has opt-in regression coverage backed by the Vocadito and
MAST melody open datasets. See [Open test datasets](docs/OPEN_DATASETS.md) for
the pinned downloads, test commands, licenses, and acknowledgements. Dataset
files are downloaded locally and ignored by Git.

## License

[MIT](LICENSE)

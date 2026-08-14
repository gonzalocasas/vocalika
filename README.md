# Vocalika

Vocalika is a local-first web application for comparing a singer's performance
with a reference recording. It focuses on measurable pitch and timing
differences rather than subjective scoring.

The project is currently at the feasibility-spike stage described in the
[product requirements](docs/PRD-001-MVP.md) and
[technical architecture](docs/ARCHITECTURE.md).

## Status

The first milestone proves the core path: continuous pitch extraction,
temporal alignment, an aligned pitch overlay, a cents-error curve, and
synchronized playback.

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
uv run vocalika serve ./analysis-output/analysis.json
```

Or use a public YouTube reference directly:

```bash
uv run vocalika analyze \
  --reference "https://www.youtube.com/watch?v=..." \
  --performance ./ableton-take.flac \
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
uv run vocalika serve ./analysis-output/analysis.json
```

Then open <http://127.0.0.1:8000>. Original source files are never modified.
Working audio and large pitch arrays live beside the generated analysis JSON.
`--output` accepts either an output directory or an explicit `.json` artifact
path.

The web interface can start another analysis from either a local reference file
or a public YouTube URL plus a local performance file. Uploaded audio is saved
under `samples/uploads/<analysis-id>/`; its artifact is written under
`analysis-output/web/<analysis-id>/`. Both locations are intentionally ignored
by Git.

## Pitch metrics

Vocalika reports two complementary error families:

- **Contour MAE** compares all confident aligned pitch frames, including
  transitions, scoops, and other pitch movement.
- **Stable-note center MAE** detects sustained reference regions, rejects
  regions with inadequate performance coverage or implausible time warping,
  and compares median pitch centers. The artifact records the number and total
  duration of included regions so a small subset is not mistaken for a general
  score.

Both are available in absolute mode and with global transposition compensated
in relative mode. Stable-note regions are highlighted lightly in green in the
pitch graph.

## Models and cache

pYIN pitch extraction does not require learned model parameters. Demucs uses a
pretrained source-separation model; `vocalika setup-models` downloads its
weights explicitly before the first analysis.

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
```

## License

[MIT](LICENSE)

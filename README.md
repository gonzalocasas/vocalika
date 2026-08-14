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

The Milestone 0 comparator accepts local files. Its reference should ideally be
an already isolated vocal; automatic separation is a later pipeline milestone.

```bash
uv run vocalika analyze \
  --reference ./reference-vocal.wav \
  --performance ./ableton-take.flac \
  --output ./analysis-output \
  --reference-is-vocal

uv run vocalika plot ./analysis-output/analysis.json
uv run vocalika serve ./analysis-output/analysis.json
```

Then open <http://127.0.0.1:8000>. Original source files are never modified.
Working audio and large pitch arrays live beside the generated analysis JSON.

## Model downloads

Milestone 0 uses pYIN and does not require learned model parameters. Later
milestones will use pretrained models for source separation and may use one for
pitch extraction. Their weights will be installed explicitly and cached on the
local machine rather than downloaded silently during an analysis.

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

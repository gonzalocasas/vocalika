# Vocalika

**Technical Architecture**  
**Version:** 0.1  
**Status:** Proposed MVP architecture

## 1. Architectural Principle

Treat vocal comparison as a pipeline of independent transformations:

```text
Source
  ↓
Acquisition
  ↓
Audio preprocessing
  ↓
Vocal isolation
  ↓
Feature extraction
  ↓
Pitch cleaning
  ↓
Temporal alignment
  ↓
Musical segmentation
  ↓
Comparison
  ↓
Observation detection
  ↓
Visualization
```

Each stage should produce inspectable intermediate artifacts.

The analysis library must remain independent of the UI.

Avoid premature application architecture.

The central technical question is:

> Can we reliably align two vocal performances and produce continuous pitch contours whose differences correspond to what a human hears?

Everything else depends on this.

---

# 2. Technology Stack

## Core

- Python 3.12+
- NumPy
- SciPy
- librosa where useful
- ffmpeg

## Pitch extraction

Initial candidate:

- `torchcrepe`

Alternative implementations should remain possible.

## Vocal separation

Initial candidate:

- Demucs

## Optional note transcription

Candidate:

- Spotify Basic Pitch

## Reference acquisition

- `yt-dlp`

## API

- FastAPI

## Visualization

Initially:

- Plotly

A minimal browser frontend is preferred.

Gradio may be used for a feasibility prototype but must not become coupled to the analysis layer.

---

# 3. Audio Source Abstraction

Input acquisition must be separate from analysis.

Define conceptually:

```python
class AudioSource(Protocol):
    def acquire(self) -> AudioAsset:
        ...
```

Initial implementations:

```text
LocalAudioSource
YouTubeAudioSource
```

Both produce the same downstream representation.

Example:

```python
@dataclass
class AudioAsset:
    path: Path
    source_type: str
    title: str | None
    source_url: str | None
    duration_seconds: float | None
    sample_rate: int | None
    content_hash: str
```

Downstream analysis must not care whether audio originated from:

- YouTube;
- FLAC;
- WAV;
- MP3;
- another supported source.

---

# 4. Local Audio Input

`LocalAudioSource` should explicitly support:

```text
FLAC
WAV
MP3
M4A
```

FLAC is a first-class format because user performances are expected to originate from Ableton Live.

The original FLAC must remain untouched.

Do not convert the source in place.

---

# 5. YouTube Input

`YouTubeAudioSource` should use `yt-dlp`.

Conceptually:

```text
YouTube URL
     │
     ▼
   yt-dlp
     │
     ▼
source audio
     │
     ▼
 AudioAsset
```

Preserve where available:

```text
video ID
URL
title
duration
```

`yt-dlp` must be treated as an external integration.

No downstream component should import or depend on it.

Suggested location:

```text
audio/
└── sources/
    ├── base.py
    ├── local.py
    └── youtube.py
```

Failure to retrieve YouTube audio should produce a clear error suggesting local-file input.

---

# 6. Canonical Audio Representation

Source files should remain untouched.

For analysis, produce normalized working audio.

Conceptually:

```text
original source
      │
      ▼
    ffmpeg
      │
      ▼
analysis WAV
```

Suggested representation:

```text
mono
float32 PCM
canonical sample rate
```

Do not unnecessarily enforce one sample rate at ingestion.

Record:

```text
original_sample_rate
analysis_sample_rate
conversion_parameters
```

Individual ML models may resample internally.

---

# 7. Reference Processing

For a complete-song reference:

```text
AudioAsset
    │
    ▼
normalized audio
    │
    ▼
  Demucs
    │
    ├── vocals.wav
    └── accompaniment.wav
```

Only `vocals.wav` enters vocal analysis.

Define:

```python
class VocalSeparator(Protocol):
    def separate(self, audio: AudioAsset) -> SeparationResult:
        ...
```

Example:

```python
@dataclass
class SeparationResult:
    vocals: Path
    accompaniment: Path | None
    model: str
    model_version: str | None
```

Already-isolated vocal references bypass this stage.

The user's performance bypasses separation for the MVP.

---

# 8. Fundamental Frequency Extraction

Initial implementation:

```text
torchcrepe
```

For each analysis frame produce approximately:

```python
@dataclass
class PitchFrame:
    time_seconds: float
    frequency_hz: float | None
    midi: float | None
    confidence: float
    voiced: bool
```

Represent pitch internally primarily as continuous MIDI:

```text
midi = 69 + 12 × log2(f / 440)
```

Therefore:

```text
69.00 = A4
69.25 = A4 + 25 cents
68.82 = A4 - 18 cents
```

And:

```text
1 MIDI unit = 100 cents
```

Never round the internal MIDI representation.

---

# 9. Pitch Extraction Interface

Avoid hard-coding torchcrepe throughout the application.

Conceptually:

```python
class PitchExtractor(Protocol):

    def extract(
        self,
        audio: AudioData,
    ) -> PitchTrack:
        ...
```

`PitchTrack` should contain:

- frames;
- extractor identifier;
- extractor/model version;
- parameters;
- source hash.

This allows later comparison between CREPE-like models or alternative F0 estimators.

---

# 10. Pitch Cleaning

Raw F0 estimates require post-processing.

Pipeline:

```text
raw F0
  ↓
confidence filtering
  ↓
voicing detection
  ↓
octave-error detection
  ↓
short-gap handling
  ↓
optional smoothing
  ↓
clean F0
```

Do not over-smooth.

Real vocal characteristics must survive, especially:

- vibrato;
- scoops;
- transitions;
- drift.

Always retain both:

```text
raw_pitch
clean_pitch
```

for debugging and algorithm development.

---

# 11. Temporal Alignment

This is the most important algorithmic stage after pitch extraction.

Naive comparison:

```text
reference[t] vs performance[t]
```

will fail.

Initial approach:

```text
Dynamic Time Warping
```

Candidate alignment features include:

```text
pitch
pitch derivative
voicing
onsets
```

Start with the simplest robust pitch-based representation.

Do not prematurely construct a complex multi-feature alignment model.

The result should expose a monotonic mapping:

```text
performance_time = f(reference_time)
```

or equivalent alignment pairs:

```python
@dataclass
class AlignmentPoint:
    reference_time: float
    performance_time: float
```

The alignment path must itself be visualizable for debugging.

---

# 12. Alignment Edge Cases

Alignment should tolerate:

- silence before singing;
- different phrase-start times;
- slightly different tempo;
- different note lengths;
- brief missed notes;
- pitch transitions occurring at different speeds.

Avoid allowing DTW to hide genuine timing mistakes.

Alignment exists to establish correspondence, not to make performances artificially identical.

Timing metrics should therefore retain information about the warp required.

---

# 13. Global Pitch Bias

Calculate:

```text
median(
    user_aligned_pitch
    -
    reference_aligned_pitch
)
```

expressed in cents.

This supports two conceptual comparison modes.

## Absolute

```text
error = user - reference
```

## Relative

```text
error =
    user
    - reference
    - global_transposition
```

Store both where practical even if the MVP UI initially exposes only absolute comparison.

---

# 14. Frame-Level Comparison

For every aligned, sufficiently confident voiced pair calculate:

```python
@dataclass
class PitchComparisonFrame:
    reference_time: float
    performance_time: float

    reference_pitch: float
    performance_pitch: float

    error_cents: float
    absolute_error_cents: float

    confidence: float
```

Primary formula:

```text
error_cents =
    100 × (performance_midi - reference_midi)
```

Equivalent frequency formulation:

```text
1200 × log2(f_user / f_reference)
```

---

# 15. Note / Region Segmentation

Continuous F0 remains the primary representation.

A secondary process may generate:

```python
@dataclass
class NoteRegion:
    start: float
    end: float
    pitch_center: float
    confidence: float
```

Possible implementations:

- Basic Pitch;
- segmentation derived directly from cleaned F0;
- onset-assisted segmentation.

Do not make note transcription a prerequisite for basic pitch comparison.

---

# 16. Region-Level Comparison

For corresponding regions calculate where possible:

```text
median_pitch_error
mean_absolute_pitch_error
pitch_stddev
onset_error_ms
offset_error_ms
duration_ratio
percentage_within_15_cents
percentage_within_25_cents
percentage_within_50_cents
```

Thresholds must remain configuration rather than hard-coded semantics.

---

# 17. Observation Engine

Higher-level feedback should initially be deterministic.

Define conceptually:

```python
@dataclass
class SingingObservation:
    type: ObservationType
    reference_start: float
    reference_end: float

    severity: float
    confidence: float

    metrics: dict[str, float]
```

Candidate types:

```text
FLAT
SHARP

PITCH_DRIFT_UP
PITCH_DRIFT_DOWN

UNSTABLE_PITCH

SLOW_PITCH_APPROACH
OVERSHOOT
UNDERSHOOT

LATE_ONSET
EARLY_ONSET
```

Example internal representation:

```json
{
  "type": "PITCH_DRIFT_DOWN",
  "reference_start": 34.2,
  "reference_end": 36.8,
  "confidence": 0.91,
  "metrics": {
    "drift_cents": -41
  }
}
```

The UI can deterministically render:

> Your pitch falls approximately 41 cents during this sustained note.

No LLM is required.

---

# 18. Vibrato Analysis

For sufficiently long sustained regions:

1. estimate slow pitch trend;
2. detrend the pitch contour;
3. analyze residual modulation;
4. estimate dominant modulation frequency;
5. estimate modulation extent;
6. estimate onset and regularity.

Possible methods:

```text
detrending
+
autocorrelation and/or FFT
```

Represent approximately:

```python
@dataclass
class VibratoMetrics:
    rate_hz: float | None
    extent_cents: float | None
    onset_seconds: float | None
    regularity: float | None
```

Do not analyze vibrato when:

- note duration is insufficient;
- voicing confidence is poor;
- pitch tracking is unreliable.

Vibrato analysis must not block the MVP.

---

# 19. Analysis Artifact

The complete analysis should be serializable.

Conceptually:

```text
analysis.json
```

Structure:

```json
{
  "schema_version": "...",

  "reference": {
    "source": {},
    "pitch": [],
    "notes": []
  },

  "performance": {
    "source": {},
    "pitch": [],
    "notes": []
  },

  "alignment": [],

  "comparison": {
    "summary": {},
    "frames": [],
    "regions": [],
    "observations": []
  }
}
```

Large numerical arrays may be stored separately in `.npz` or an equivalent efficient representation.

The persisted artifact should contain enough information to rebuild the UI without rerunning expensive ML inference.

---

# 20. Provenance

Every derived artifact should record relevant provenance:

```text
input hash
pipeline version
model name
model version
parameters
sample rate
timestamp
```

This is particularly important while experimenting with pitch extraction and alignment algorithms.

---

# 21. Cache

Suggested location:

```text
~/.cache/vocalika/
```

Conceptually:

```text
~/.cache/vocalika/
│
├── sources/
│   └── <source-hash>/
│       ├── metadata.json
│       └── source.*
│
├── normalized/
│   └── <processing-hash>.wav
│
├── separation/
│   └── <processing-hash>/
│       ├── vocals.wav
│       └── accompaniment.wav
│
└── analysis/
    └── <analysis-hash>/
```

Repeated analysis against the same YouTube reference should reuse:

- source audio;
- normalized audio;
- separated vocal;
- extracted reference pitch where compatible.

Cache keys must account for model and preprocessing versions.

---

# 22. CLI First

Before significant UI work, implement a usable CLI.

Example:

```bash
vocal-compare analyze \
    --reference "https://youtube.com/watch?v=..." \
    --performance ./ableton-take.flac \
    --output analysis.json
```

Reference input should automatically distinguish:

```text
URL
vs
local path
```

No `--youtube` flag should be necessary.

Also support:

```bash
vocal-compare plot analysis.json
```

This should generate an interactive or static diagnostic visualization.

---

# 23. Repository Structure

Suggested structure:

```text
vocalika/
│
├── pyproject.toml
├── README.md
├── PRD.md
├── ARCHITECTURE.md
│
├── src/
│   └── vocalika/
│
│       ├── audio/
│       │   ├── decode.py
│       │   ├── separation.py
│       │   └── sources/
│       │       ├── base.py
│       │       ├── local.py
│       │       └── youtube.py
│       │
│       ├── analysis/
│       │   ├── pitch.py
│       │   ├── cleaning.py
│       │   ├── voicing.py
│       │   ├── segmentation.py
│       │   ├── alignment.py
│       │   ├── vibrato.py
│       │   └── comparison.py
│       │
│       ├── models/
│       │   └── analysis.py
│       │
│       ├── observations/
│       │   └── detectors.py
│       │
│       ├── cache/
│       │   └── cache.py
│       │
│       ├── api/
│       │   └── app.py
│       │
│       └── cli.py
│
├── frontend/
│
├── tests/
│   ├── unit/
│   ├── synthetic/
│   └── fixtures/
│
└── data/
    └── .gitkeep
```

This is guidance, not a requirement.

Prefer simpler organization if the implementation does not yet justify these modules.

---

# 24. Synthetic Test Harness

Create utilities capable of generating controlled variants of known vocal audio.

Transformations:

```text
global pitch shift
local pitch shift
time shift
time stretch
pitch drift
optional vibrato modification
```

Conceptually:

```python
variant = transform(
    reference,
    pitch_shift_cents=+30,
    delay_ms=120,
)
```

The comparator should recover approximately:

```text
pitch bias ≈ +30 cents
timing difference ≈ +120 ms
```

Synthetic tests should become the primary regression suite for analytical correctness.

---

# 25. UI Architecture

Target:

```text
┌──────────────────────────────────────────┐
│ Browser                                  │
│                                          │
│ source inputs                            │
│ waveform                                 │
│ pitch overlay                            │
│ pitch-error graph                        │
│ observations                             │
│ playback controls                        │
└────────────────────┬─────────────────────┘
                     │
                    HTTP
                     │
┌────────────────────▼─────────────────────┐
│ FastAPI                                  │
│                                          │
│ analysis orchestration                   │
│ artifact serving                         │
│ audio serving                            │
└────────────────────┬─────────────────────┘
                     │
                     ▼
            Python analysis library
```

The browser frontend should contain little analytical logic.

---

# 26. Playback Alignment

Playback introduces an important architectural distinction:

```text
reference time
≠
performance time
```

The UI must use the alignment mapping when switching between Reference and Mine.

Selecting:

```text
reference 34.0 → 38.0
```

might correspond to:

```text
performance 35.1 → 39.5
```

A/B playback should use the appropriate source ranges.

---

# 27. Future Analysis Layers

The architecture should allow future additions without redesigning the pipeline:

```text
                         ┌─ pitch
                         ├─ timing
                         ├─ vibrato
Audio → vocals → features├─ dynamics
                         ├─ timbre
                         ├─ formants
                         ├─ lyrics/pronunciation
                         └─ phrasing
                              │
                              ▼
                      structured metrics
                              │
                              ▼
                       coaching layer
```

The future coaching layer should consume **structured observations**, not attempt to infer measurements directly from raw audio.

For example:

```json
{
  "observation": "pitch_drift_down",
  "range": [34.2, 36.8],
  "magnitude_cents": 41,
  "reference_vibrato_hz": 5.7,
  "performance_vibrato_hz": 4.3
}
```

An LLM could later turn this into useful conversational coaching.

It should not be responsible for measuring the 41-cent drift.

---

# 28. Development Strategy

Development must proceed vertically.

## Milestone 0 — Feasibility Spike

Inputs:

```text
reference-vocal.wav
performance.flac
```

Produce:

```text
F0 extraction
      ↓
alignment
      ↓
interactive overlay
      ↓
cents-difference graph
```

Nothing else.

No Demucs.

No YouTube.

No polished UI.

No note transcription.

No coaching.

### Exit criterion

A human listening to the two recordings should agree that the graph represents the major audible pitch differences.

---

# 29. Milestone 1 — Pitch Comparator

Add:

- robust preprocessing;
- FLAC handling;
- pitch cleaning;
- cents comparison;
- global bias;
- summary statistics;
- synthetic regression tests.

Exit criterion:

Known synthetic pitch transformations are recovered reliably.

---

# 30. Milestone 2 — Real Input Pipeline

Add:

- YouTube source adapter;
- `yt-dlp`;
- caching;
- Demucs;
- reference vocal extraction.

End-to-end input becomes:

```text
YouTube URL
+
Ableton FLAC
```

Exit criterion:

No manual reference preparation is required.

---

# 31. Milestone 3 — Practice UI

Add:

- browser frontend;
- pitch overlay;
- error graph;
- zoom/pan;
- synchronized audio;
- A/B;
- region selection;
- looping.

Exit criterion:

A singer can use the application repeatedly during a practice session without resorting to external analysis tools.

---

# 32. Milestone 4 — Musical Analysis

Add:

- note segmentation;
- onset comparison;
- duration comparison;
- drift detection;
- approach detection;
- overshoot/undershoot;
- vibrato.

---

# 33. Milestone 5 — Coaching Layer

Only after deterministic analysis is reliable, consider:

- prioritization of observations;
- natural-language explanations;
- practice suggestions;
- historical comparison between takes;
- optional LLM coaching.

---

# 34. Critical Engineering Rule

**Do not start by building the application.**

First prove:

```text
reference vocal
      +
user vocal
      │
      ▼
continuous F0
      │
      ▼
robust temporal alignment
      │
      ▼
aligned pitch overlay
      │
      ▼
pitch-error curve
```

The first meaningful deliverable should essentially be:

```text
                 reference
G4 ───────────────╮       ╭────────────
                  │       │
F#4               ╰───────╯

                 performance
G4 ────────────╮            ╭──────────
               ╰──╮      ╭──╯
F#4               ╰──────╯


ERROR
+50c ┤         ╭──╮
  0c ┼─────────╯  ╰────────────────────
-50c ┤
```

alongside synchronized audio playback.

If this representation feels musically meaningful, continue.

If it does not, **stop and improve pitch extraction/alignment rather than adding product features.**

That experiment de-risks the entire project.

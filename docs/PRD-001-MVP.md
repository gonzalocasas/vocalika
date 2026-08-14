# Vocalika

**Product Requirements Document**  
**Version:** 0.1  
**Status:** MVP specification

## 1. Product Vision

Vocalika is a local-first tool for comparing a singer's performance against an existing reference recording.

The fundamental question it should answer is:

> **How does my singing differ from the reference performance, and what should I practice?**

The user provides:

- a reference song, normally as a YouTube URL;
- their own vocal recording, normally a lossless FLAC exported from Ableton Live.

The application automatically extracts the reference vocal, analyzes both performances, aligns them in time, and presents an interactive comparison.

The initial product focuses primarily on:

- pitch accuracy;
- pitch movement and transitions;
- timing;
- sustained-note stability;
- basic vibrato characteristics.

The goal is **not** to assign an arbitrary singing score or determine whether a voice sounds "good."

The reference performance is instead used as a measurable target.

---

# 2. Primary User

The initial product is a single-user desktop/local tool for someone practicing singing by recording themselves in a DAW.

The expected workflow is:

```text
REFERENCE                         PERFORMANCE

YouTube URL                       Ableton Live
     │                                │
     ▼                                ▼
source audio                       FLAC export
     │                                │
     ▼                                │
vocal separation                      │
     │                                │
     └──────────┐        ┌────────────┘
                ▼        ▼
             reference   user
               vocal     vocal
                  │       │
                  └───┬───┘
                      ▼
               pitch extraction
                      │
                      ▼
                  alignment
                      │
                      ▼
                 comparison
                      │
                      ▼
             interactive analysis
```

The desired user experience is approximately:

> Paste YouTube URL → drop Ableton FLAC → Analyze → understand what differs.

---

# 3. Core User Flow

The user provides:

### Reference

Either:

- YouTube URL; or
- local audio file.

### Performance

Normally:

- FLAC exported from Ableton Live.

The application then:

1. acquires the reference audio;
2. isolates the reference vocal if necessary;
3. decodes the user's recording;
4. extracts continuous pitch information from both;
5. aligns the performances temporally;
6. compares their pitch contours;
7. identifies meaningful discrepancies;
8. displays an interactive visual comparison;
9. produces a small set of actionable observations.

---

# 4. Input Requirements

## 4.1 Reference — YouTube

A YouTube URL is a first-class reference input.

Example:

```text
https://www.youtube.com/watch?v=...
```

The application should:

1. recognize the URL;
2. retrieve a suitable audio stream;
3. preserve available source metadata;
4. decode the audio;
5. isolate the vocal;
6. feed the vocal into the normal analysis pipeline.

Metadata should include where available:

- title;
- source URL;
- duration.

The application should fail gracefully if acquisition is unavailable and allow the user to provide a local file instead.

YouTube acquisition should be implemented using `yt-dlp` or an equivalent replaceable adapter.

The user is responsible for using material they are permitted to access and process.

---

## 4.2 Reference — Local File

Support at minimum:

- FLAC;
- WAV;
- MP3;
- M4A.

Other formats supported transparently by ffmpeg may work where practical.

The user should be able to indicate whether a local reference contains:

- the complete song; or
- an already isolated vocal.

Already isolated vocals should bypass source separation.

---

# 5. Performance Input

FLAC is the primary expected input format.

Expected workflow:

```text
Ableton Live
     │
     ▼
Export FLAC
     │
     ▼
Vocalika
```

FLAC must therefore be explicitly tested rather than merely supported incidentally through ffmpeg.

The application must:

- decode FLAC losslessly;
- preserve the original file;
- preserve original sample-rate metadata;
- resample only where required by individual analysis stages;
- never require manual FLAC → WAV conversion.

The MVP assumes the performance recording contains primarily the user's vocal with little or no accompaniment.

---

# 6. Vocal Isolation

When the reference contains a complete song, automatically isolate the vocal.

The expected initial implementation is Demucs or an equivalent source-separation model.

Conceptually:

```text
reference audio
      │
      ▼
source separation
      │
      ├── vocals
      └── accompaniment
```

Only the isolated vocal enters the vocal-analysis pipeline.

The accompaniment may be retained for future playback/practice functionality.

---

# 7. Pitch Analysis

## 7.1 Continuous F0

For both vocal tracks calculate a continuous pitch time series containing approximately:

```text
timestamp
frequency_hz
continuous_midi_pitch
confidence
voiced/unvoiced
```

Pitch analysis must retain sufficient temporal and pitch resolution to expose:

- sharp/flat singing;
- pitch drift;
- scoops;
- overshoot;
- undershoot;
- note transitions;
- vibrato.

The underlying pitch analysis must **not** be quantized to semitones.

Continuous F0 is the primary representation.

Musical-note segmentation is secondary.

---

# 8. Pitch Difference

For aligned voiced frames calculate deviation in cents.

```text
difference_cents =
    1200 × log2(user_frequency / reference_frequency)
```

Interpretation:

```text
   0 cents    exact pitch match
 +25 cents    slightly sharp
 -25 cents    slightly flat
+100 cents    one semitone sharp
```

The application should detect obvious pitch-detector octave errors where practical rather than interpreting them as enormous singing errors.

---

# 9. Temporal Alignment

The reference and user will not:

- start simultaneously;
- maintain exactly identical tempo;
- hold notes for identical durations;
- transition between notes at exactly the same moment.

Direct sample/time comparison is therefore insufficient.

The application must create a temporal mapping between performances.

Example:

```text
reference  13.42 s
     ↕
performance 14.17 s
```

Alignment should tolerate moderate performance differences without incorrectly interpreting them as pitch errors.

The initial expected technique is Dynamic Time Warping or an equivalent sequence-alignment technique.

---

# 10. Global Transposition

The application should calculate global pitch bias.

Example:

```text
median(user pitch - reference pitch)
```

This enables eventual support for:

### Absolute mode

Compare literal pitches.

Useful when practicing in exactly the reference key.

### Relative mode

Compensate for global transposition before comparing melodic accuracy.

For example:

```text
Reference: C major
Performance: entire song one semitone lower

Absolute difference: ≈ -100 cents
Relative melodic difference: ≈ 0 cents
```

The MVP may expose only absolute mode initially, but the analysis artifact should retain enough information to support both.

---

# 11. Note / Region Segmentation

Continuous pitch is the primary analysis.

A secondary stage should group the contour into approximate musical note regions.

For each region calculate where possible:

- reference pitch center;
- user's median pitch;
- median pitch error;
- mean absolute pitch error;
- pitch stability;
- duration;
- onset difference;
- offset difference;
- percentage of frames within tolerance.

Initial heuristic tolerance bands:

```text
excellent       ≤ 15 cents
good            ≤ 30 cents
noticeable      ≤ 50 cents
large error     > 50 cents
```

These thresholds must remain configurable.

---

# 12. Pitch Behavior Detection

The application should eventually identify deterministic patterns such as:

- flat;
- sharp;
- pitch drift upward;
- pitch drift downward;
- unstable pitch;
- slow approach to target;
- overshoot;
- undershoot;
- late onset;
- early onset.

Observations should be grounded in measurable data rather than generated directly by an LLM.

Example:

```text
00:34–00:37

Sustained F#4 averages 38 cents flat.
```

Or:

```text
00:51–00:54

Pitch begins close to the reference but falls approximately
30 cents toward the end of the sustained note.
```

---

# 13. Vibrato

For sufficiently long and stable notes, attempt to estimate:

- vibrato rate in Hz;
- vibrato extent in cents;
- vibrato onset;
- regularity;
- underlying pitch drift.

Vibrato analysis is experimental in v0.1 and must not block delivery of the core comparator.

---

# 14. Visualization

The primary interface is an interactive synchronized pitch graph.

### X axis

Aligned time.

### Y axis

Musical pitch / continuous MIDI pitch.

Display:

- reference pitch contour;
- user pitch contour;
- approximate note boundaries;
- low-confidence regions;
- selected/problem regions.

The user must be able to:

- zoom;
- pan;
- hover to inspect values;
- select a time region;
- play the corresponding audio;
- loop a selected region.

The visualization should make pitch differences immediately apparent.

Conceptually:

```text
REFERENCE        ─────────── G4 ─────────────
                         ╭────────╮

USER            ────────╯        ╰───────────
                       ↑
                  approaches
                  from below
```

---

# 15. Difference Visualization

In addition to the overlaid pitch curves, display pitch error over time.

Conceptually:

```text
 +50c ┤       ╭──╮
 +25c ┤   ╭───╯  ╰─╮
   0c ┼───╯        ╰──────────── target
 -25c ┤
 -50c ┤
```

This should make persistent sharp/flat tendencies easy to recognize.

---

# 16. Summary Results

Show a compact analysis summary.

Example:

```text
PITCH

Mean absolute error       24 cents
Within ±25 cents          71%
Within ±50 cents          89%
Median bias               -11 cents


TIMING

Median onset difference   +43 ms


TENDENCY

Slightly flat overall
```

These statistics are secondary to the interactive visualization.

The purpose is diagnosis, not scoring.

---

# 17. Interesting Regions

Automatically identify the most informative discrepancies.

Examples:

```text
00:34–00:37
Sustained F#4 averages 38 cents flat.

00:42
You reach the G4 approximately 120 ms later than the reference.

00:51–00:54
Pitch center begins accurately but falls ~30 cents before
the end of the note.
```

Clicking an observation should select the corresponding region in the graph.

---

# 18. Audio Playback

Provide:

- Reference;
- Mine;
- A/B;
- optional simultaneous playback;
- Loop selection.

Example:

```text
[Reference] [Mine] [A/B] [Loop selection]
```

Playback should respect the temporal alignment so corresponding regions can be compared easily.

---

# 19. Caching

Reference acquisition and expensive derived artifacts should be cached.

Analyzing another performance against the same YouTube reference should not require:

- downloading the source again;
- rerunning vocal separation unnecessarily.

The application should invalidate derived cache entries when relevant model or preprocessing versions change.

---

# 20. Local-First Requirement

The MVP should be:

- local-first;
- single-user;
- runnable on macOS and preferably Linux;
- usable without cloud services after required models/dependencies are installed;
- deterministic/reproducible where practical.

No authentication.

No user database.

No microservices.

No cloud infrastructure.

No LLM is required for the core analysis.

---

# 21. Non-Goals for v0.1

Do not initially attempt:

- subjective singing-quality scoring;
- AI vocal-coach chat;
- timbre imitation;
- lyric transcription;
- pronunciation analysis;
- breath-support diagnosis;
- resonance/formant coaching;
- real-time microphone analysis;
- mobile applications;
- user accounts;
- cloud synchronization;
- social features.

---

# 22. Suggested MVP Interaction

The target end-to-end interaction is:

```text
Reference

[ https://youtube.com/watch?v=............... ]


My performance

[ Drop Ableton FLAC here ]


                 [ Analyze ]
```

followed by:

```text
┌──────────────────────────────────────────────┐
│ Reference ─────────╮    ╭────────────────   │
│ Mine      ───────╮ ╰────╯  ╭─────────────   │
│                  ╰──────────╯                │
│                                              │
│ Pitch difference                             │
│ +50 ┤          ╭──╮                         │
│   0 ┼──────────╯  ╰────────────────────     │
│ -50 ┤                                        │
└──────────────────────────────────────────────┘

Pitch accuracy      24 cents MAE
Pitch bias         -11 cents

⚠ 00:34–00:37 — sustained note ~38 cents flat
⚠ 00:51–00:54 — pitch falls toward end of note

[Reference] [Mine] [A/B] [Loop]
```

---

# 23. MVP Success Criterion

v0.1 succeeds if the user can provide:

```text
Reference:
https://youtube.com/watch?v=...

Performance:
my-ableton-take.flac
```

and obtain an analysis without manually preparing either audio source.

For a 30–90 second vocal passage, the result should make it visually and audibly obvious:

> **where the user's pitch differs from the reference and approximately how.**

The most important success criterion is not an aggregate score.

It is whether the user can identify a specific singing mistake, retry the phrase, and determine whether they improved.

---

# 24. Synthetic Acceptance Tests

Use a known vocal recording to generate synthetic performances with controlled transformations:

1. global +50 cents;
2. global -25 cents;
3. one region +100 cents;
4. 150 ms timing delay;
5. gradual -50 cent drift across a sustained note;
6. modest global time stretch;
7. octave-error-like pitch discontinuity.

The analyzer should recover these transformations within reasonable tolerances.

This provides a reproducible benchmark before evaluating subjective real-world singing performances.

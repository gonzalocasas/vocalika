# New performance metrics: exploration and implementation handoff

## Purpose

Extend Vocalika from pitch-error reporting into actionable vocal coaching. The
next metrics should explain *what changed during a phrase* and direct the singer
to a specific practice target. They should remain descriptive, preserve
expressive choices, expose confidence, and avoid presenting acoustic proxies as
medical conclusions.

Priority agreed for exploration:

1. Dynamics matching
2. Accuracy by range or register
3. Transition quality
4. Note-level rhythm accuracy
5. Sustained-note stability
6. Note-entry accuracy
7. Advanced experimental voice-quality indicators

## Existing foundations

The current pipeline already provides most of the shared coordinate system:

- Cleaned reference and performance pitch tracks.
- A global audio offset followed by open-ended, temporally regularized pitch
  DTW.
- Aligned `reference_time` and `performance_time` frame pairs.
- Independent voicing and pitch-confidence arrays.
- Absolute and globally transposition-compensated pitch errors.
- Stable reference-pitch regions with aligned performance bounds.
- Full-take and selected-range metric calculation in the frontend.

Relevant implementation points:

- `src/vocalika/pipeline.py`: orchestration and artifact assembly.
- `src/vocalika/analysis/alignment.py`: time correspondence.
- `src/vocalika/analysis/comparison.py`: aligned frame summaries.
- `src/vocalika/analysis/stable_notes.py`: stable-region detection.
- `src/vocalika/audio/preprocessing.py`: normalized analysis audio.
- `frontend/src/shared/types.ts`: artifact contract.
- `frontend/src/metrics.ts`: selected-range recomputation.
- `frontend/src/features/compare/CompareView.vue`: diagnostic presentation.

Do not derive the new metrics only in the browser. Persist the source
measurements and full-take summary in the artifact, then let the frontend
recalculate selection-scoped summaries from those measurements where practical.

## Cross-cutting measurement rules

### Separate measurement from judgment

Store physical or musical measurements first: decibels, milliseconds, cents,
rates, slopes, ratios, and coverage. Convert them into singer-facing language
in a separate interpretation layer. Avoid a single composite score until the
individual dimensions have been validated with singers.

### Confidence and availability

Every regional result should carry enough evidence to decide whether it is
usable:

- Duration and contributing-frame count.
- Voiced coverage for each track.
- Alignment confidence or a defensible proxy.
- A machine-readable unavailable reason when no result is reported.

Summaries must not silently turn unavailable data into zero. Use `null` for
unavailable values and emit a warning only when the missing dimension materially
affects the whole take.

### Reference-relative, not universally ideal

Dynamics, timing, attacks, transitions, and voice quality contain artistic
choices. Report both the measured performance behavior and, where useful, its
difference from the reference. Matching the reference is not inherently better
unless the user has chosen imitation as the goal.

### Artifact evolution

Group new data by dimension rather than adding many unrelated keys to
`comparison.summary`. A possible structure is:

```json
{
  "comparison": {
    "summary": { "...existing": "..." },
    "dimensions": {
      "dynamics": { "summary": {}, "regions": [], "frames": {} },
      "range": { "bands": [] },
      "transitions": { "summary": {}, "events": [] },
      "rhythm": { "summary": {}, "events": [] },
      "stability": { "summary": {}, "regions": [] },
      "attacks": { "summary": {}, "events": [] },
      "voice_quality_experimental": { "summary": {}, "regions": [] }
    }
  }
}
```

Decide deliberately whether this additive change remains schema `0.1.0` or
triggers a schema bump. Golden artifacts compare analytical content strictly,
so update them only after algorithm behavior and tolerances are covered by
focused tests.

## Phase 1: dynamics matching

### User questions

- Did I shape the phrase similarly to the reference?
- Did my crescendo, decrescendo, and emphasis occur at the intended time?
- Was my delivery dynamically flat or unstable?

### Important constraint

Raw amplitude cannot be compared directly. Microphone gain, distance, room,
compression, source separation, and reference mastering can dominate absolute
level. Compare normalized *contour shape* from isolated vocal analysis signals.
Do not claim that the singer was objectively too loud or too quiet.

### Proposed signal

1. Decode the normalized isolated vocal at a fixed sample rate.
2. Compute a short-time loudness proxy using 40–80 ms windows and 10–20 ms
   hops. Start with log RMS; evaluate perceptual weighting or short-term LUFS
   only if it materially improves validation examples.
3. Estimate a local noise floor and gate unreliable/unvoiced frames. Reuse pitch
   voicing where possible, but do not require a valid F0 for every dynamic frame:
   consonants and breathy phonation still carry useful energy.
4. Smooth the dB contour over roughly 150–300 ms to remove individual glottal
   pulses while preserving phrase shape.
5. Sample both contours through the existing reference-to-performance time
   correspondence. Collapse duplicate DTW reference positions before summary
   calculations so heavily warped sections are not overweighted.
6. Normalize each track robustly within the analyzed take or phrase. A useful
   initial representation is `(dB - median) / IQR`, with a fallback when the IQR
   is too small. Also retain a percentile-normalized 0–1 contour for display.

### Candidate outputs

Frame data:

- `reference_time`
- `reference_relative_level`
- `performance_relative_level`
- `valid`

Full-take and selected-range summaries:

- Contour correlation, preferably Spearman as the primary shape measure.
- Median absolute normalized-level difference.
- Dynamic range for each track, using P90 minus P10 rather than max minus min.
- Dynamic-range ratio.
- Percentage of valid frames moving in the same direction after smoothing.
- Valid seconds and coverage.

Phrase or region events:

- Reference and performance start/end.
- Contour correlation.
- Dynamic ranges.
- Peak-emphasis time difference.
- Trend classification: crescendo, decrescendo, arch, flat, or mixed.

Do not expose correlation alone. A performance can correlate well while using a
much smaller dynamic range. Pair shape similarity with range comparison.

### Phrase segmentation

For the first implementation, derive candidate phrase boundaries from sustained
unvoiced gaps in the reference vocal, then map them to the performance through
the alignment. Keep thresholds configurable. Lyrics-aware phrase segmentation
can be explored later and should not block the acoustic MVP.

### Suggested singer-facing presentation

- Add a normalized dynamics contour below the pitch chart, sharing its time
  selection and playhead.
- Add two compact cards: `DYNAMIC SHAPE` and `DYNAMIC RANGE`.
- Rank the weakest phrase regions and make them clickable/listenable.
- Prefer feedback such as “Your phrase shape matched, but used 42% less dynamic
  range” over “Dynamics score: 71.”

### Dynamics validation

Create deterministic synthetic fixtures from one vocal-like signal:

- Identical envelope with a constant gain change: similarity should remain
  high after normalization.
- Matching crescendo and inverted decrescendo: correlation should change sign.
- Compressed versus full-range envelope: shape remains similar while the range
  ratio decreases.
- Added silence and a time offset: valid aligned results should remain stable.
- Low-SNR input: coverage should fall or the metric should become unavailable.

Also test one real vocal at different microphone gains and distances before
assigning UI thresholds.

## Phase 2: accuracy by range or register

Start with neutral pitch bands; do not infer chest, mix, head, or passaggio from
F0 alone.

Recommended first version:

- Partition the singer's analyzed reference range into low, middle, and high
  thirds, with a minimum span requirement.
- Additionally aggregate by named semitone or octave when sufficient data is
  available.
- For each band report median and mean absolute error, within-25-cent coverage,
  voiced coverage, matched seconds, and sample count.
- Support absolute and global-bias-compensated modes.
- Require minimum evidence before ranking a band as weakest.

Later, allow a singer to configure known register boundaries. Label inferred
boundaries as experimental rather than naming vocal registers automatically.

Synthetic validation should distribute identical errors across bands, inject a
known high-range error, and verify that sparse extreme notes do not dominate.

## Phase 3: transition quality

Build a reusable note/region segmentation layer before calculating transition
scores. Stable regions are useful anchors but do not currently describe every
note boundary.

For each eligible reference transition, store:

- Starting and target pitch centers.
- Interval direction and size.
- Reference and performance transition bounds.
- Transition-duration difference.
- Maximum overshoot or undershoot beyond the target.
- Time to enter and remain inside the target tolerance.
- Direction correctness.
- Optional path-shape similarity for intentional slides.

Straight leaps and portamenti require different interpretations. Classify the
reference transition first; do not penalize a slide merely for spending time
between centers when the reference does the same.

Reuse the existing practice interval terminology where possible so take review
and exercises speak the same language.

## Phase 4: note-level rhythm accuracy

Use note or phrase events, not raw DTW frame displacement. DTW is allowed to
warp time and therefore cannot by itself prove that an onset was correct.

Candidate outputs:

- Onset deviation in milliseconds.
- Release deviation in milliseconds.
- Duration ratio.
- Inter-onset-interval ratio.
- Median absolute onset/release error.
- Percentage early, on time, and late.
- Local tempo-drift slope across the phrase.

Detect candidate boundaries independently on both tracks using a combination of
pitch change, energy onset, and voicing. Match those events using the existing
alignment as a search prior. Preserve both raw timing and a version with one
global performance offset removed.

Validation needs repeated-note fixtures because pitch-only boundary detection
cannot distinguish adjacent notes at the same pitch.

## Phase 5: sustained-note stability

Extend `stable_notes.py` rather than creating a competing definition of held
notes. Within each accepted stable reference region, measure the performance:

- Robust pitch slope in cents per second.
- Start-to-end drift.
- Robust spread after detrending.
- Percentage inside ±25 and ±50 cents of its own center and the target center.
- Voiced continuity and longest dropout.

Intentional vibrato must not be scored as instability. For the initial version,
report both raw spread and a detrended/low-frequency drift measure. A later
vibrato model can explicitly separate periodic modulation from irregular
variation.

## Phase 6: note-entry accuracy

Using the note segmentation and target centers created for transitions:

- Measure signed error at a configurable post-onset instant.
- Measure overshoot/undershoot during the attack window.
- Measure settling time: first point after which pitch stays within tolerance
  for a minimum dwell duration.
- Record whether the singer approached from above or below.
- Exclude consonantal/unvoiced lead-in from pitch scoring while retaining it for
  onset timing.

The attack window should scale for very short notes and become unavailable when
there is insufficient confident pitch. Report patterns across notes (“entered
flat on 8 of 11 eligible notes”) rather than overemphasizing one event.

## Phase 7: experimental voice-quality indicators

This dimension must be explicitly opt-in or marked `EXPERIMENTAL`. It is not a
diagnosis, health assessment, or universal quality score.

Candidates to prototype on sustained, isolated-vocal regions:

- Cepstral peak prominence (prefer smoothed CPPS if implemented correctly).
- Harmonics-to-noise ratio.
- Spectral tilt and H1–H2-like source measures.
- Jitter and shimmer on suitable near-periodic sustained vowels.
- Vibrato rate, extent, onset, and cycle regularity.

Guardrails:

- Show recording-quality checks alongside results.
- Require minimum SNR, duration, periodicity, and stable pitch.
- Never compare values across different devices without warning.
- Favor within-person trends across similarly recorded takes.
- Do not label values healthy, unhealthy, good, or bad.
- Keep source separation model/version in provenance because artifacts can
  alter spectral measures.

The most useful initial product may be a consistency view: “CPPS changed from
your recent baseline under similar recording conditions,” not a population
threshold.

## Shared implementation sequence

1. Write a short metric contract with units, eligibility, invariances, failure
   modes, and interpretation before writing the algorithm.
2. Add a focused analysis module and frozen dataclasses for summary plus regional
   or frame evidence.
3. Add configuration fields and include them in cache/provenance behavior.
4. Integrate into `pipeline.py` and persist the evidence in the artifact.
5. Add synthetic unit tests before regenerating any golden artifact.
6. Add at least one adversarial test for low confidence, short duration,
   duplicated DTW indices, and missing data.
7. Extend TypeScript types and selected-range calculation.
8. Add the diagnostic visualization and plain-language interpretation.
9. Validate on real recordings and tune thresholds only after inspecting false
   positives.
10. Regenerate golden artifacts deliberately and document schema changes.

## Definition of done for each metric family

- Units and musical meaning are documented.
- Known invariances are tested (for example, dynamics shape is invariant to
  constant gain).
- Unavailable and low-confidence behavior is explicit.
- Summary values can be traced back to regions or frames.
- Full-take and selected-range results agree when the full range is selected.
- The UI states what the singer can do differently.
- Tests cover synthetic truth, realistic failure modes, serialization, API
  compatibility, and frontend calculation.
- No medical or stylistic claim exceeds what the signal supports.

## Recommended immediate work item

Implement a dynamics-analysis spike behind the artifact boundary, without UI
scoring:

1. Add aligned, normalized log-RMS contours.
2. Persist coverage, contour correlation, and P90–P10 range for each track.
3. Validate constant-gain invariance, inverted envelopes, compression, silence,
   and alignment duplication.
4. Render an internal comparison plot and review it on several real takes.
5. Only then choose interpretation thresholds and expose singer-facing cards.

This isolates the highest-risk question—whether the extracted contour represents
perceived vocal dynamics reliably enough—before committing to product language.

## Research starting points

- D'Amario et al., acoustic singing parameters including vibrato rate, extent,
  duration, and regularity: <https://pubmed.ncbi.nlm.nih.gov/25795355/>
- Bottalico et al., sensitivity of acoustic voice measures to room and
  microphone conditions: <https://pubmed.ncbi.nlm.nih.gov/30471944/>
- European Laryngological Society, multidimensional functional voice assessment
  protocol: <https://pubmed.ncbi.nlm.nih.gov/11307610/>
- Aeroacoustic indicators and singer-reported vocal fatigue, useful as context
  for strict non-diagnostic guardrails: <https://pubmed.ncbi.nlm.nih.gov/37568532/>

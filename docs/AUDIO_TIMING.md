# Audio timing contract

Playback, preview and export use one backend policy: `projects/timing.py`.
The API sends its resolved `playback_timing` to the browser; the browser must
not recompute placement from analysis scores or DTW frame pairs.

The sign convention is `performance_time = reference_time + offset_seconds`.
A positive offset removes recorded lead-in. A negative offset adds silence
before the take. Trimming changes the reference interval, never the take's
stored capture origin. Rendering resamples to the output rate without changing
duration, then places samples once; it never stretches a singer's phrasing.

New studio takes store the recorder's elapsed time minus the backing track's
media position after playback starts. That anchor survives pause/resume,
project trim changes, persistence and reanalysis. The studio checks elapsed
recording time and both backing stems every 100 ms; a discrepancy over 100 ms
stops the take and disables submission with an explanation. It never resets
the anchor on resume to hide a discontinuity.

Imported/legacy takes may use a direct PCM match at confidence >= 0.9, or a
version-2 guarded spectral phrase match at the same threshold. Envelope
similarity and DTW are analysis tools, not recording-latency measurements.
Unknown placement preserves the original timing and says so in Compare and
Export. Legacy partial imports may need reanalysis to establish a guarded
spectral match; there is deliberately no silent DTW fallback. No legacy
metadata is rewritten based on filenames or today's trim settings.

Containment estimators cannot claim confidence from nearly equal file lengths,
a search-boundary maximum, or a search with no alternative peak to compare.
Candidate diagnostics remain in analysis artifacts, even when selection rejects
all candidates. Timing estimator version 2 distinguishes these results from
older, overconfident saved analyses.

Both fresh and cached transpositions must preserve duration within 50 ms,
using the actual source-file sample rate. Unknown durations fail validation.
Isolated export vocals must also preserve the original take duration within
50 ms. Existing no-cache reference responses prevent stale browser copies.

## Regression gate

`.github/workflows/timing.yml` runs the backend timing/audio regressions, all
frontend tests and the production build on pushes and pull requests. Locally:

```sh
.venv/bin/pytest -q tests/unit/test_playback_timing.py tests/unit/test_project_export.py tests/unit/test_reference_audio.py tests/unit/test_projects.py tests/synthetic/test_alignment_offsets.py
(cd frontend && npm test && npm run build)
```

Fixtures cover the Tears in Heaven failure (a high-confidence -100 ms envelope
estimate), uncertain/legacy estimates, captured trim origins, offset signs,
16/44.1/48 kHz placement, WebM decode, preview/export agreement, invalid upload
metadata, repeated phrases, pause/resume, stalled media clocks, independently
desynchronized stems, and stale transpositions. Golden changes require review;
pitch/scoring arrays should not change for a playback-policy-only fix.

## Limits

Browser media clocks do not measure microphone/headphone hardware latency or
Bluetooth buffering. These checks detect application clock divergence, not
sample-accurate acoustic loopback delay. A future latency-calibration feature
must measure that delay explicitly rather than infer it from singing. A stalled
browser event loop can postpone detection. A length check cannot prove that a
transform preserved every internal onset; retain known-onset audio tests when
changing decoding, resampling, isolation or transposition algorithms.

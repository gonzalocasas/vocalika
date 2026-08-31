import assert from "node:assert/strict"
import test from "node:test"

import { calculateRangeSummary } from "../src/metrics.ts"

test("selected-range metrics recompute local bias and count unique matched frames", () => {
  const summary = calculateRangeSummary(
    {
      reference_time: [0, 1, 1, 2, 3, 4],
      reference_midi: [60, 60, 60, 60, 60, 60],
      performance_midi: [60, 61, 62, 60, 59, 60],
      valid: [true, true, true, true, true, true],
    },
    [
      { reference_start: 0.5, reference_end: 1.5, error_cents: 100 },
      { reference_start: 2.5, reference_end: 3.5, error_cents: -100 },
      { reference_start: 4, reference_end: 5, error_cents: 0 },
    ],
    3,
    1,
    10,
  )

  assert.ok(summary)
  assert.equal(summary.global_bias_cents, 50)
  assert.equal(summary.mean_absolute_error_cents, 100)
  assert.equal(summary.relative_mean_absolute_error_cents, 100)
  assert.equal(summary.within_50_percent, 25)
  assert.equal(summary.relative_within_50_percent, 50)
  assert.equal(summary.valid_frame_count, 4)
  assert.equal(summary.matched_seconds, 0.3)
  assert.equal(summary.stable_note_region_count, 2)
  assert.equal(summary.stable_note_total_seconds, 1)
  assert.equal(summary.stable_note_pitch_center_mae_cents, 125)
  assert.equal(summary.relative_stable_note_pitch_center_mae_cents, 125)
})

test("selected-range stable centers use only frames inside the selected overlap", () => {
  const summary = calculateRangeSummary(
    {
      reference_time: [179.6, 180, 181, 181.1, 181.2, 181.3, 181.4, 181.5, 182.8],
      reference_midi: [70, 70, 70.2, 70.1, 70, 70, 70.1, 70.1, 70],
      performance_midi: [65.8, 66, 66.4, 66.3, 66.2, 66.2, 66.3, 66.3, 66.4],
      valid: [true, true, true, true, true, true, true, true, true],
    },
    [
      {
        reference_start: 179.6,
        reference_end: 182.8,
        error_cents: -390,
      },
    ],
    181,
    181.6,
    10,
  )

  assert.ok(summary)
  assert.ok(Math.abs(summary.global_bias_cents + 380) < 1e-9)
  assert.ok(Math.abs(summary.stable_note_pitch_center_mae_cents - 380) < 1e-9)
  assert.ok(summary.relative_stable_note_pitch_center_mae_cents < 1e-9)
  assert.ok(Math.abs(summary.stable_note_total_seconds - 0.6) < 1e-9)
})

test("selected-range metrics are unavailable without confident paired frames", () => {
  const summary = calculateRangeSummary(
    {
      reference_time: [0, 1],
      reference_midi: [60, 60],
      performance_midi: [60, 60],
      valid: [false, false],
    },
    [],
    0,
    1,
  )

  assert.equal(summary, null)
})

test("selected-range metrics report the typical frame as well as the mean", () => {
  // One badly-tracked frame — an octave out — must not be allowed to speak for
  // the whole selection. The mean is dragged; the median is not.
  const summary = calculateRangeSummary(
    {
      reference_time: [0, 1, 2, 3, 4],
      reference_midi: [60, 60, 60, 60, 60],
      performance_midi: [60.1, 60.1, 60.1, 60.1, 72],
      valid: [true, true, true, true, true],
    },
    [],
    0,
    5,
    10,
  )
  assert.ok(summary)
  assert.ok(summary.median_absolute_error_cents < 20, "the typical frame is in tune")
  assert.ok(summary.mean_absolute_error_cents > 200, "the mean carries the octave error")
  assert.ok(
    summary.mean_absolute_error_cents > 10 * summary.median_absolute_error_cents,
    "a wide mean/median gap is the signal that outliers dominate",
  )
})

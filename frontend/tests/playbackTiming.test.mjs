import assert from "node:assert/strict"
import test from "node:test"

import {
  performanceToReferenceTime,
  referenceToPerformanceTime,
  resolvePlaybackOffset,
} from "../src/playbackTiming.ts"

test("take playback uses a continuous global offset instead of stepped DTW points", () => {
  const offset = resolvePlaybackOffset(
    { global_offset_seconds: 0.2, global_offset_confidence: 0.9 },
    [0, 1, 1, 1, 2],
    [0.2, 1.2, 1.3, 1.4, 2.2],
  )

  assert.equal(offset, 0.2)
  assert.equal(referenceToPerformanceTime(1, offset), 1.2)
  assert.equal(performanceToReferenceTime(1.25, offset), 1.05)
  assert.equal(performanceToReferenceTime(1.29, offset), 1.09)
})

test("take playback falls back to the median aligned offset", () => {
  const offset = resolvePlaybackOffset(
    { global_offset_seconds: 8, global_offset_confidence: 0.1 },
    [0, 1, 2, 3],
    [0.3, 1.3, 2.4, Number.NaN],
  )

  assert.ok(Math.abs(offset - 0.3) < 1e-9)
})

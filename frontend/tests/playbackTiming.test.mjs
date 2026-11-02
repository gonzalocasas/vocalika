import assert from "node:assert/strict"
import test from "node:test"

import {
  performanceToReferenceTime,
  referenceToPerformanceTime,
  resolvePlaybackOffset,
} from "../src/playbackTiming.ts"

test("take playback uses a continuous global offset instead of stepped DTW points", () => {
  const offset = resolvePlaybackOffset({
    offset_seconds: 0.2, source: "audio-match", message: "Verified",
  })

  assert.equal(offset, 0.2)
  assert.equal(referenceToPerformanceTime(1, offset), 1.2)
  assert.equal(performanceToReferenceTime(1.25, offset), 1.05)
  assert.equal(performanceToReferenceTime(1.29, offset), 1.09)
})

test("missing or invalid placement preserves original timing", () => {
  assert.equal(resolvePlaybackOffset(undefined), 0)
  assert.equal(resolvePlaybackOffset({ offset_seconds: Number.NaN }), 0)
})

test("trimmed recording uses the server's captured position", () => {
  const offset = resolvePlaybackOffset({ offset_seconds: -19.97, source: "recording" })
  assert.ok(Math.abs(referenceToPerformanceTime(20, offset) - 0.03) < 1e-9)
})

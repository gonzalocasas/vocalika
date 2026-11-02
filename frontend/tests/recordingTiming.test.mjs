import assert from "node:assert/strict"
import test from "node:test"
import { recordingOffset, timingIsConsistent } from "../src/features/recording/recordingTiming.ts"
import { createElapsedClock } from "../src/features/recording/elapsedClock.ts"

test("captures startup delay and trim without inferring them from singing", () => {
  const offset = recordingOffset(.04, 20)
  assert.equal(offset, -19.96)
  assert.ok(timingIsConsistent(offset, 10.04, 30, 30.01))
})

test("pause and resume preserve the original timeline anchor", () => {
  const clock = createElapsedClock()
  clock.start(0)
  const offset = recordingOffset(clock.read(30), 20)
  clock.pause(10030)
  clock.resume(60030)
  assert.ok(timingIsConsistent(offset, clock.read(70030), 40))
  // A lost second on resume must not be concealed by resetting the anchor.
  assert.equal(timingIsConsistent(offset, clock.read(70030), 41), false)
})

test("stalls, clock drift and independent stem desync are rejected", () => {
  assert.equal(timingIsConsistent(0, 30, 29.8), false)
  assert.equal(timingIsConsistent(0, 30, 30, 30.2), false)
  assert.equal(timingIsConsistent(0, 30, Number.NaN), false)
  assert.ok(timingIsConsistent(0, 30, 30.02, 30.03))
})

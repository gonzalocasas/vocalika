import assert from "node:assert/strict"
import test from "node:test"

import { createElapsedClock } from "../src/features/recording/elapsedClock.ts"

test("counts wall time while running", () => {
  const clock = createElapsedClock()
  clock.start(1000)
  assert.equal(clock.read(1000), 0)
  assert.equal(clock.read(3500), 2.5)
  assert.ok(clock.running())
})

test("a paused gap is not counted", () => {
  const clock = createElapsedClock()
  clock.start(0)
  clock.pause(2000)
  // Ten seconds pass with the take held.
  assert.equal(clock.read(12000), 2, "the gap must not accrue")
  clock.resume(12000)
  assert.equal(clock.read(13000), 3, "counting continues from where it stopped")
  assert.ok(clock.running())
})

test("survives several pauses", () => {
  const clock = createElapsedClock()
  clock.start(0)
  clock.pause(1000)
  clock.resume(5000)
  clock.pause(6000)
  clock.resume(9000)
  assert.equal(clock.read(10000), 3, "three one-second segments")
})

test("repeated pause and resume are idempotent", () => {
  // The UI can emit these from a double click or a keyboard repeat; a second
  // pause must not bank the gap twice.
  const clock = createElapsedClock()
  clock.start(0)
  clock.pause(1000)
  clock.pause(4000)
  assert.equal(clock.read(4000), 1)
  clock.resume(4000)
  clock.resume(8000)
  assert.equal(clock.read(5000), 2)
})

test("restarting clears earlier segments", () => {
  const clock = createElapsedClock()
  clock.start(0)
  clock.pause(5000)
  clock.start(10000)
  assert.equal(clock.read(11000), 1)
})

test("a clock that never started reads zero", () => {
  const clock = createElapsedClock()
  assert.equal(clock.read(9999), 0)
  assert.equal(clock.running(), false)
})

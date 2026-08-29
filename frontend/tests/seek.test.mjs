import assert from "node:assert/strict"
import test from "node:test"

import { seekTimeAt } from "../src/features/reference/seek.ts"

const bounds = { left: 100, width: 400 }

test("maps a click across the waveform to a time", () => {
  assert.equal(seekTimeAt(100, bounds, 200, 0, 200), 0)
  assert.equal(seekTimeAt(300, bounds, 200, 0, 200), 100)
  assert.equal(seekTimeAt(500, bounds, 200, 0, 200), 200)
})

test("a click outside the element resolves to its nearest edge", () => {
  assert.equal(seekTimeAt(-50, bounds, 200, 0, 200), 0)
  assert.equal(seekTimeAt(9999, bounds, 200, 0, 200), 200)
})

test("clicks outside the trimmed range clamp to it", () => {
  // Playback is bounded by the trim, so a position outside it would stop the
  // moment it started.
  assert.equal(seekTimeAt(100, bounds, 200, 40, 160), 40, "before the in point")
  assert.equal(seekTimeAt(500, bounds, 200, 40, 160), 160, "after the out point")
  assert.equal(seekTimeAt(300, bounds, 200, 40, 160), 100, "inside is untouched")
})

test("an inverted trim range still clamps sanely", () => {
  const time = seekTimeAt(300, bounds, 200, 160, 40)
  assert.ok(time >= 40 && time <= 160, `got ${time}`)
})

test("degenerate geometry falls back to the in point", () => {
  assert.equal(seekTimeAt(300, { left: 100, width: 0 }, 200, 12, 160), 12)
  assert.equal(seekTimeAt(300, bounds, 0, 12, 160), 12)
})

test("a zero-length selection pins to the single position", () => {
  assert.equal(seekTimeAt(300, bounds, 200, 80, 80), 80)
})

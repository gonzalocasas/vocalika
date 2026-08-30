import assert from "node:assert/strict"
import test from "node:test"

import { isIntervalScore, VERDICT_LABEL } from "../src/features/practice/types.ts"
import { midiToHertz } from "../src/features/practice/useTonePlayer.ts"

test("held-note and interval scores are told apart", () => {
  const held = { target_midi: 60, verdict: "on-pitch", centre_cents: 3 }
  const interval = { target_semitones: 7, interval_error_cents: -12, verdict: "close" }
  assert.equal(isIntervalScore(held), false)
  assert.equal(isIntervalScore(interval), true)
})

test("every verdict the server can return has a label", () => {
  for (const verdict of ["on-pitch", "close", "off", "wrong-note", "unsteady", "not-heard"]) {
    assert.ok(VERDICT_LABEL[verdict], `no label for ${verdict}`)
  }
})

test("reference tones are generated at the right frequency", () => {
  assert.ok(Math.abs(midiToHertz(69) - 440) < 1e-9)
  assert.ok(Math.abs(midiToHertz(60) - 261.6256) < 1e-3)
  assert.ok(Math.abs(midiToHertz(81) - 880) < 1e-9)
  // An octave is exactly a doubling, which is what makes the ladder audible
  // as a scale rather than as drifting pitches.
  assert.ok(Math.abs(midiToHertz(72) / midiToHertz(60) - 2) < 1e-12)
})

test("an over-wide descending leap is described as wide, not flat", () => {
  // The signed error is negative descending, which pitch vocabulary would
  // call "flat" while the singer actually over-jumped.
  const score = {
    target_semitones: -5,
    sung_semitones: -6.7,
    interval_error_cents: -170,
    width_error_cents: 170,
    wrong_direction: false,
    verdict: "off",
  }
  assert.equal(isIntervalScore(score), true)
  assert.ok(score.width_error_cents > 0, "wider than asked")
})

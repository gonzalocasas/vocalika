import assert from "node:assert/strict"
import test from "node:test"

import { centsLabel, leapLabel, leapSpanLabel } from "../src/features/practice/labels.ts"

test("cents are phrased flat or sharp with the sign as direction", () => {
  assert.equal(centsLabel(-40), "40¢ flat")
  assert.equal(centsLabel(130), "130¢ sharp")
  assert.equal(centsLabel(0), "exactly on pitch")
})

test("a missing or unusable cents value never reaches the screen", () => {
  // A server that predates a field sends undefined, not null, and Math.round
  // turns both undefined and NaN into NaN -- which used to render literally.
  for (const value of [null, undefined, Number.NaN, Number.POSITIVE_INFINITY]) {
    assert.equal(centsLabel(value), "—", `${String(value)} leaked through`)
  }
})

test("a leap is described by its width, not as flat or sharp", () => {
  assert.equal(
    leapLabel({ width_error_cents: 170, wrong_direction: false }),
    "170¢ too wide",
  )
  assert.equal(
    leapLabel({ width_error_cents: -150, wrong_direction: false }),
    "150¢ too narrow",
  )
  assert.equal(
    leapLabel({ width_error_cents: 4, wrong_direction: false }),
    "exactly the right distance",
  )
})

test("a leap taken the wrong way says so rather than reporting a size", () => {
  assert.equal(
    leapLabel({ width_error_cents: 5, wrong_direction: true }),
    "you leapt the other way",
  )
})

test("a missing width never renders as NaN", () => {
  for (const value of [null, undefined, Number.NaN]) {
    assert.equal(
      leapLabel({ width_error_cents: value, wrong_direction: false }),
      "—",
      `${String(value)} leaked through`,
    )
  }
})

test("the target span reads as a direction and a size", () => {
  assert.equal(leapSpanLabel(7), "7 semitones up")
  assert.equal(leapSpanLabel(-5), "5 semitones down")
  assert.equal(leapSpanLabel(1), "1 semitone up")
  assert.equal(leapSpanLabel(undefined), "—")
})

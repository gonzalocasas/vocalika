import assert from "node:assert/strict"
import test from "node:test"

import {
  centsToMidi,
  midiToCents,
  noteTicks,
  pitchExtent,
  seriesToCents,
} from "../src/features/compare/pitchAxis.ts"

test("cents are measured from middle C, a semitone being a hundred", () => {
  assert.equal(midiToCents(60), 0)
  assert.equal(midiToCents(61), 100)
  assert.equal(midiToCents(69), 900, "A4 sits 9 semitones above C4")
  assert.equal(midiToCents(48), -1200, "an octave below is -1200")
})

test("the conversion round-trips", () => {
  for (const midi of [36, 55.5, 60, 69.25, 84]) {
    assert.ok(Math.abs(centsToMidi(midiToCents(midi)) - midi) < 1e-9)
  }
})

test("a gap in the contour stays a gap", () => {
  // Nulls break the drawn line at rests; converting must not fill them in.
  assert.deepEqual(
    seriesToCents([60, null, 61, Number.NaN, 59]),
    [0, null, 100, null, -100],
  )
})

test("the extent pads the contour away from the frame", () => {
  const extent = pitchExtent([[57, 60, 62], [58, 61]])
  assert.ok(extent.lowMidi < 57 && extent.highMidi > 62)
})

test("a single held note is not drawn at absurd zoom", () => {
  const extent = pitchExtent([[60, 60, 60]])
  assert.ok(extent.highMidi - extent.lowMidi >= 6, "a flat contour needs a floor on the span")
})

test("an empty contour still yields a usable range", () => {
  const extent = pitchExtent([[], [null, Number.NaN]])
  assert.ok(extent.highMidi > extent.lowMidi)
})

test("note ticks are placed in cents and named", () => {
  const ticks = noteTicks({ lowMidi: 59, highMidi: 62 })
  assert.deepEqual(ticks.ticktext, ["B3", "C4", "C#4", "D4"])
  assert.deepEqual(ticks.tickvals, [-100, 0, 100, 200])
})

test("the step widens with the span so labels never collide", () => {
  for (const [low, high] of [[59, 62], [48, 72], [36, 84], [24, 96]]) {
    const ticks = noteTicks({ lowMidi: low, highMidi: high })
    assert.ok(ticks.tickvals.length <= 14, `${high - low} semitones gave ${ticks.tickvals.length} ticks`)
    assert.ok(ticks.tickvals.length >= 2, "there must be enough ticks to read the scale")
  }
})

test("ticks land on the same notes however the view is scrolled", () => {
  // A wide span steps by more than a semitone; those steps should be anchored
  // to C rather than to wherever the window happens to begin.
  const a = noteTicks({ lowMidi: 48, highMidi: 72 })
  const b = noteTicks({ lowMidi: 49, highMidi: 73 })
  const shared = a.tickvals.filter((value) => b.tickvals.includes(value))
  assert.ok(shared.length >= a.tickvals.length - 2, "tick positions should be stable")
})

test("tick positions agree with the axis they are drawn against", () => {
  const ticks = noteTicks({ lowMidi: 50, highMidi: 70 })
  ticks.tickvals.forEach((cents, index) => {
    assert.equal(ticks.ticktext[index], noteNameFor(centsToMidi(cents)))
  })
})

function noteNameFor(midi) {
  const names = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
  const nearest = Math.round(midi)
  return `${names[((nearest % 12) + 12) % 12]}${Math.floor(nearest / 12) - 1}`
}

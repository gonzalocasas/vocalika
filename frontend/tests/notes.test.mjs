import assert from "node:assert/strict"
import test from "node:test"

import { noteName, transposedRange } from "../src/shared/notes.ts"

test("names notes in scientific pitch notation", () => {
  assert.equal(noteName(60), "C4")
  assert.equal(noteName(69), "A4")
  assert.equal(noteName(54), "F#3")
  assert.equal(noteName(62), "D4")
  assert.equal(noteName(21), "A0")
})

test("rounds to the nearest named note", () => {
  assert.equal(noteName(60.4), "C4")
  assert.equal(noteName(60.6), "C#4")
  assert.equal(noteName(61.5), "D4")
})

test("survives pitches below C-1 and non-finite input", () => {
  // A negative pitch class would index the name table out of bounds.
  assert.equal(noteName(-1), "B-2")
  assert.equal(noteName(0), "C-1")
  assert.equal(noteName(Number.NaN), "—")
  assert.equal(noteName(Number.POSITIVE_INFINITY), "—")
})

const range = {
  low_midi: 54,
  high_midi: 62,
  median_midi: 55,
  low_note: "F#3",
  high_note: "D4",
  median_note: "G3",
  semitones: 8,
}

test("transposing shifts the range and renames it", () => {
  const down = transposedRange(range, -4)
  assert.equal(down.low_note, "D3")
  assert.equal(down.high_note, "A#3")
  assert.equal(down.low_midi, 50)
  assert.equal(down.high_midi, 58)
  // The span is a property of the song, not of the key it is sung in.
  assert.equal(down.semitones, 8)
})

test("transposing up works and zero is a no-op", () => {
  assert.equal(transposedRange(range, 3).high_note, "F4")
  assert.equal(transposedRange(range, 0), range)
  assert.equal(transposedRange(null, -4), null)
})

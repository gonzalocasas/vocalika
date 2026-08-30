import assert from "node:assert/strict"
import test from "node:test"

import {
  midiToHertz,
  nearestSampleMidi,
  playbackRateFor,
  SAMPLE_MIDI,
  sampleUrl,
} from "../src/features/practice/pianoSamples.ts"

test("every recorded note has a file", () => {
  for (const midi of SAMPLE_MIDI) {
    assert.match(sampleUrl(midi), /^\/piano\/[A-G]s?\d\.mp3$/, `bad url for ${midi}`)
  }
})

test("the samples span the range the pitch extractor can report", () => {
  // PyinPitchExtractor runs from MIDI 36 (C2) to 84 (C6); an exercise can
  // never ask for a note outside that.
  assert.equal(Math.min(...SAMPLE_MIDI), 36)
  assert.equal(Math.max(...SAMPLE_MIDI), 84)
})

test("no note is ever more than 1.5 semitones from a real recording", () => {
  for (let midi = 36; midi <= 84; midi += 1) {
    const distance = Math.abs(midi - nearestSampleMidi(midi))
    assert.ok(distance <= 1.5, `MIDI ${midi} is ${distance} semitones from a sample`)
  }
})

test("an exact sample pitch plays back untouched", () => {
  for (const midi of SAMPLE_MIDI) {
    assert.equal(nearestSampleMidi(midi), midi)
    assert.equal(playbackRateFor(midi, midi), 1)
  }
})

test("notes outside the sampled range clamp to the nearest end", () => {
  assert.equal(nearestSampleMidi(20), 36)
  assert.equal(nearestSampleMidi(120), 84)
})

test("the playback rate shifts pitch by the right amount", () => {
  assert.ok(Math.abs(playbackRateFor(72, 60) - 2) < 1e-12, "an octave doubles the rate")
  assert.ok(Math.abs(playbackRateFor(48, 60) - 0.5) < 1e-12)
  // The worst case in use: 1.5 semitones, about 9%.
  assert.ok(Math.abs(playbackRateFor(61.5, 60) - 1.0905) < 1e-3)
})

test("resampled pitch lands where it should", () => {
  for (let midi = 36; midi <= 84; midi += 1) {
    const sample = nearestSampleMidi(midi)
    const sounded = midiToHertz(sample) * playbackRateFor(midi, sample)
    const cents = 1200 * Math.log2(sounded / midiToHertz(midi))
    assert.ok(Math.abs(cents) < 1e-9, `MIDI ${midi} sounds ${cents} cents off`)
  }
})

test("reference tones use standard concert pitch", () => {
  assert.ok(Math.abs(midiToHertz(69) - 440) < 1e-9)
  assert.ok(Math.abs(midiToHertz(60) - 261.6256) < 1e-3)
})

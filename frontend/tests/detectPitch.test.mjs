import assert from "node:assert/strict"
import test from "node:test"

import { detectPitch, hertzToMidi, NO_PITCH, rootMeanSquare } from "../src/features/recording/detectPitch.ts"

const SAMPLE_RATE = 44100

function tone(hertz, { seconds = 0.05, harmonics = [1], amplitude = 0.5 } = {}) {
  const length = Math.round(SAMPLE_RATE * seconds)
  const buffer = new Float32Array(length)
  for (let index = 0; index < length; index += 1) {
    const time = index / SAMPLE_RATE
    let value = 0
    harmonics.forEach((weight, harmonic) => {
      value += weight * Math.sin(2 * Math.PI * hertz * (harmonic + 1) * time)
    })
    buffer[index] = amplitude * value
  }
  return buffer
}

function centsApart(hertz, expected) {
  return Math.abs(1200 * Math.log2(hertz / expected))
}

test("detects a pure tone to within a few cents", () => {
  for (const expected of [110, 220, 440, 880]) {
    const { hertz } = detectPitch(tone(expected), SAMPLE_RATE)
    assert.ok(hertz !== NO_PITCH, `no pitch found for ${expected} Hz`)
    assert.ok(centsApart(hertz, expected) < 5, `${expected} Hz read as ${hertz}`)
  }
})

test("locks to the fundamental of a harmonically rich tone", () => {
  // A plain autocorrelation typically reports an octave down here; YIN's
  // cumulative mean normalisation is what prevents it.
  const buffer = tone(196, { harmonics: [1, 0.8, 0.6, 0.4, 0.3] })
  const { hertz } = detectPitch(buffer, SAMPLE_RATE)
  assert.ok(hertz !== NO_PITCH)
  assert.ok(centsApart(hertz, 196) < 15, `expected ~196 Hz, read ${hertz}`)
})

test("reports no pitch for silence and for noise", () => {
  assert.equal(detectPitch(new Float32Array(2048), SAMPLE_RATE).hertz, NO_PITCH)

  const noise = new Float32Array(4096)
  let seed = 7
  for (let index = 0; index < noise.length; index += 1) {
    seed = (seed * 1103515245 + 12345) % 2147483648
    noise[index] = (seed / 2147483648) * 2 - 1
  }
  const { hertz, clarity } = detectPitch(noise, SAMPLE_RATE)
  assert.ok(hertz === NO_PITCH || clarity < 0.6, `noise read as ${hertz} Hz at clarity ${clarity}`)
})

test("treats a very quiet buffer as unvoiced", () => {
  const quiet = tone(440, { amplitude: 0.001 })
  assert.equal(detectPitch(quiet, SAMPLE_RATE).hertz, NO_PITCH)
})

test("respects the configured range", () => {
  const belowRange = detectPitch(tone(50), SAMPLE_RATE)
  assert.equal(belowRange.hertz, NO_PITCH)
})

test("clarity is high for a clean tone", () => {
  const { clarity } = detectPitch(tone(440), SAMPLE_RATE)
  assert.ok(clarity > 0.8, `clarity was ${clarity}`)
})

test("rootMeanSquare and hertzToMidi agree with their definitions", () => {
  const constant = new Float32Array(16).fill(0.5)
  assert.ok(Math.abs(rootMeanSquare(constant) - 0.5) < 1e-9)
  assert.ok(Math.abs(hertzToMidi(440) - 69) < 1e-9)
  assert.ok(Math.abs(hertzToMidi(880) - 81) < 1e-9)
})

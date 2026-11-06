import assert from "node:assert/strict"
import { test } from "node:test"

import {
  CLICK_COUNT,
  CLICK_SPACING_SECONDS,
  makeClickTrack,
  measureLatency,
} from "../src/features/recording/latencyMeasure.ts"

const RATE = 44_100

/** A seeded noise source, so failures reproduce. */
function noise(seed) {
  let state = seed
  return () => {
    state = (state * 1_664_525 + 1_013_904_223) % 2 ** 32
    return state / 2 ** 32 - 0.5
  }
}

/** What a microphone hears: the click track delayed, scaled, maybe inverted, plus noise and an echo. */
function loopback(delaySeconds, { gain = 0.3, noiseLevel = 0.02, echo = 0.1, seed = 1 } = {}) {
  const track = makeClickTrack(RATE)
  const delay = Math.round(delaySeconds * RATE)
  const echoDelay = delay + Math.round(0.012 * RATE)
  const random = noise(seed)
  const out = new Float32Array(track.length)
  for (let i = 0; i < out.length; i += 1) {
    out[i] = noiseLevel * random()
    if (i >= delay) out[i] += gain * track[i - delay]
    if (i >= echoDelay) out[i] += echo * gain * track[i - echoDelay]
  }
  return out
}

test("a known round trip is measured to the sample", () => {
  for (const delay of [0.004, 0.0383, 0.1, 0.25]) {
    const result = measureLatency(loopback(delay), RATE)
    assert.ok(result, `nothing measured for ${delay}`)
    assert.equal(Math.round(result.seconds * RATE), Math.round(delay * RATE))
    assert.equal(result.detected, CLICK_COUNT)
  }
})

test("an inverted signal path is measured the same", () => {
  const result = measureLatency(loopback(0.1, { gain: -0.3 }), RATE)
  assert.equal(Math.round(result.seconds * RATE), Math.round(0.1 * RATE))
})

test("silence (headphones nowhere near the mic) is refused, not guessed", () => {
  const quiet = loopback(0.1, { gain: 0, echo: 0 })
  assert.equal(measureLatency(quiet, RATE), null)
})

test("chirps buried in noise are refused rather than measured wrong", () => {
  const buried = loopback(0.1, { gain: 0.002, noiseLevel: 0.5 })
  assert.equal(measureLatency(buried, RATE), null)
})

test("the click track leaves room for the slowest round trip after the last chirp", () => {
  const track = makeClickTrack(RATE)
  assert.ok(track.length >= (CLICK_COUNT * CLICK_SPACING_SECONDS + 0.4) * RATE - 1)
})

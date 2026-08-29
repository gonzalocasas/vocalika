import assert from "node:assert/strict"
import test from "node:test"

import { createScrollProgress, easeToward } from "../src/features/recording/lyricsScroll.ts"

/** Contour at 10 fps from [voicedSeconds, restSeconds, ...] segments. */
function contour(segments) {
  const times = []
  const midi = []
  let time = 0
  segments.forEach(([seconds, voiced]) => {
    for (let index = 0; index < Math.round(seconds * 10); index += 1) {
      times.push(Number(time.toFixed(4)))
      midi.push(voiced ? 60 : null)
      time += 0.1
    }
  })
  return { times, midi }
}

test("progress tracks sung time, not wall time", () => {
  // 10s sung, 20s instrumental, 10s sung. At the end of the first sung block
  // the singer is half way through the words but only a quarter of the way
  // through the song.
  const progress = createScrollProgress(
    contour([[10, true], [20, false], [10, true]]),
    0,
    40,
  )
  assert.ok(progress.usesVoicedTime)
  assert.ok(Math.abs(progress.at(10) - 0.5) < 0.02, `got ${progress.at(10)}`)
})

test("the page holds still through an instrumental break", () => {
  const progress = createScrollProgress(
    contour([[10, true], [20, false], [10, true]]),
    0,
    40,
  )
  const beforeBreak = progress.at(10.5)
  const middleOfBreak = progress.at(20)
  const endOfBreak = progress.at(29.5)
  assert.ok(Math.abs(endOfBreak - beforeBreak) < 0.02, "progress must not advance over a rest")
  assert.ok(Math.abs(middleOfBreak - beforeBreak) < 0.02)
})

test("runs from 0 to 1 across the take", () => {
  const progress = createScrollProgress(contour([[10, true], [5, false], [10, true]]), 0, 25)
  assert.equal(progress.at(0), 0)
  assert.ok(progress.at(-5) === 0, "before the start")
  assert.ok(Math.abs(progress.at(25) - 1) < 0.02)
  assert.equal(progress.at(999), 1, "after the end")
})

test("progress never goes backwards", () => {
  const progress = createScrollProgress(contour([[5, true], [5, false], [5, true]]), 0, 15)
  let previous = -1
  for (let time = 0; time <= 15; time += 0.1) {
    const value = progress.at(time)
    assert.ok(value >= previous - 1e-9, `dipped at ${time}`)
    previous = value
  }
})

test("falls back to elapsed time without a usable contour", () => {
  for (const bad of [null, { times: [], midi: [] }, contour([[10, false]])]) {
    const progress = createScrollProgress(bad, 0, 10)
    assert.equal(progress.usesVoicedTime, false)
    assert.ok(Math.abs(progress.at(5) - 0.5) < 1e-6, "should be linear in time")
    assert.equal(progress.at(0), 0)
    assert.equal(progress.at(10), 1)
  }
})

test("only voiced frames inside the trimmed window count", () => {
  // Singing before the trim start belongs to a part of the reference the
  // singer never hears, so it must not consume lyric progress.
  const progress = createScrollProgress(contour([[10, true], [10, true]]), 10, 20)
  assert.ok(progress.at(10) < 0.05, `got ${progress.at(10)}`)
  assert.ok(Math.abs(progress.at(20) - 1) < 0.05)
})

test("easing approaches the target and then settles exactly", () => {
  let position = 0
  for (let step = 0; step < 200; step += 1) position = easeToward(position, 100, 16)
  assert.equal(position, 100, "must settle rather than creep")

  const one = easeToward(0, 100, 16)
  assert.ok(one > 0 && one < 100, "a single frame moves part of the way")
})

test("easing is roughly frame-rate independent", () => {
  let fast = 0
  for (let step = 0; step < 20; step += 1) fast = easeToward(fast, 1000, 10)
  let slow = 0
  for (let step = 0; step < 10; step += 1) slow = easeToward(slow, 1000, 20)
  assert.ok(Math.abs(fast - slow) < 5, `${fast} vs ${slow}`)
})

test("easing handles a non-finite starting position", () => {
  assert.equal(easeToward(Number.NaN, 42, 16), 42)
})

import assert from "node:assert/strict"
import test from "node:test"

import {
  activeLineIndex,
  activeWordIndex,
  jumpTime,
  timingMatches,
} from "../src/features/reference/lyricsTiming.ts"

function line(text, words) {
  const timed = words.filter(([, start]) => start !== null)
  return {
    text,
    sung: timed.length > 0,
    start: timed.length ? timed[0][1] : null,
    end: timed.length ? timed[timed.length - 1][2] : null,
    words: words.map(([word, start, end]) => ({ text: word, start, end, score: 0.9 })),
  }
}

const lines = [
  line("[Chorus]", []),
  line("One two", [["One", 1, 1.4], ["two", 2, 2.5]]),
  line("", []),
  line("Three four", [["Three", 10, 10.5], ["four", 11, 11.5]]),
]
const timing = { version: 1, aligner: "test", lines }

test("timing only applies to the text it was measured for", () => {
  assert.equal(timingMatches(timing, "[Chorus]\nOne two\n\nThree four"), true)
  assert.equal(timingMatches(timing, "[Chorus]\r\n  One two  \r\n\r\nThree four"), true)
  assert.equal(timingMatches(timing, "[Chorus]\nOne two\n\nThree four five"), false)
  assert.equal(timingMatches(timing, "One two\n\nThree four"), false)
  assert.equal(timingMatches(null, ""), false)
})

test("the active line is the last one started, held through a break", () => {
  assert.equal(activeLineIndex(lines, 0.5), -1)
  assert.equal(activeLineIndex(lines, 1), 1)
  assert.equal(activeLineIndex(lines, 6), 1)
  assert.equal(activeLineIndex(lines, 10.2), 3)
  assert.equal(activeLineIndex(lines, 500), 3)
})

test("the active word bridges short gaps but not long ones", () => {
  assert.equal(activeWordIndex(lines[1], 0.9), -1)
  assert.equal(activeWordIndex(lines[1], 1.2), 0)
  assert.equal(activeWordIndex(lines[1], 1.6), 0)
  assert.equal(activeWordIndex(lines[1], 1.8), -1)
  assert.equal(activeWordIndex(lines[1], 2.1), 1)
  assert.equal(activeWordIndex(undefined, 2), -1)
})

test("a jump lands a little before the word, never before the song", () => {
  assert.equal(jumpTime(10), 9.65)
  assert.equal(jumpTime(0.1), 0)
})

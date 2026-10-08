/**
 * Word timings for a song's lyrics, measured against the reference vocal by
 * forced alignment on the server. Lines map one to one onto the lyrics text,
 * blank lines and section labels included, with null times where nothing
 * was sung.
 */

export interface TimedWord {
  text: string
  start: number | null
  end: number | null
  score: number | null
}

export interface TimedLine {
  text: string
  sung: boolean
  start: number | null
  end: number | null
  words: TimedWord[]
}

export interface LyricsTiming {
  version: number
  aligner: string
  lines: TimedLine[]
}

/**
 * Whether a timing still describes this text.
 *
 * The timing is fetched for the lyrics the server has saved; while the singer
 * edits, or before a save lands, it would put highlights on the wrong lines.
 */
export function timingMatches(timing: LyricsTiming | null, lyrics: string): timing is LyricsTiming {
  if (!timing) return false
  const lines = lyrics.split(/\r?\n/)
  return timing.lines.length === lines.length
    && timing.lines.every((line, index) => line.text === lines[index].trim())
}

/**
 * The line being sung at `time`: the last one that has started.
 *
 * A line stays current through the gap after it, so an instrumental break
 * leaves the singer on the line they just sang rather than on nothing.
 */
export function activeLineIndex(lines: TimedLine[], time: number): number {
  let active = -1
  for (let index = 0; index < lines.length; index += 1) {
    const start = lines[index].start
    if (start === null) continue
    if (start > time) break
    active = index
  }
  return active
}

/** The word being sung at `time` within a line, or -1 between words. */
export function activeWordIndex(line: TimedLine | undefined, time: number): number {
  if (!line) return -1
  let active = -1
  for (let index = 0; index < line.words.length; index += 1) {
    const { start, end } = line.words[index]
    if (start === null || end === null) continue
    if (start > time) break
    // Hold the word through the short gap to the next one, so the highlight
    // moves word to word instead of flickering off between them.
    if (time < end + 0.25) active = index
  }
  return active
}

/**
 * Where playback should land for a clicked line or word.
 *
 * Alignment marks the first consonant, so starting exactly there clips the
 * breath and the attack. A short lead-in plays into the word instead.
 */
export function jumpTime(start: number, leadIn = 0.35): number {
  return Math.max(0, start - leadIn)
}

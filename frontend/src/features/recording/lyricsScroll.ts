/**
 * Rough lyric follow, without any lyric timing data.
 *
 * Scrolling on elapsed time alone drifts badly: a song's intro, instrumental
 * break and outro consume minutes while consuming no lyrics, so the page runs
 * ahead of the singer and then waits at the bottom.
 *
 * The reference contour already says where the reference vocal is actually
 * singing, so progress is measured in *sung* time rather than wall time. The
 * page then holds still through an instrumental section and moves only while
 * there are words to get through. It is deliberately approximate -- it maps
 * the whole lyric onto the whole vocal evenly, and cannot know that one verse
 * has more words than another.
 */

export interface ProgressContour {
  times: number[]
  midi: (number | null)[]
}

export interface ScrollProgress {
  /** 0..1 through the lyric at this reference time. */
  at(time: number): number
  /** False when there was no voiced reference to measure, and time is used. */
  usesVoicedTime: boolean
}

export function createScrollProgress(
  contour: ProgressContour | null,
  start: number,
  end: number,
): ScrollProgress {
  const span = Math.max(1e-6, end - start)
  const linear = (time: number): number =>
    Math.max(0, Math.min(1, (time - start) / span))

  if (!contour || contour.times.length === 0) {
    return { at: linear, usesVoicedTime: false }
  }

  const { times, midi } = contour
  const step = times.length > 1 ? times[1] - times[0] : 0
  if (step <= 0) return { at: linear, usesVoicedTime: false }

  // Cumulative voiced frames, so progress at any time is one lookup.
  const cumulative = new Float64Array(times.length)
  let running = 0
  for (let index = 0; index < times.length; index += 1) {
    const time = times[index]
    const inRange = time >= start && time <= end
    if (inRange && midi[index] !== null && Number.isFinite(midi[index] as number)) running += 1
    cumulative[index] = running
  }
  const total = running

  // An entirely unvoiced reference (a failed separation, an instrumental)
  // carries no information about pacing, so fall back to elapsed time.
  if (total === 0) return { at: linear, usesVoicedTime: false }

  return {
    usesVoicedTime: true,
    at(time: number): number {
      const index = Math.round((time - times[0]) / step)
      if (index <= 0) return 0
      if (index >= cumulative.length) return 1
      return Math.max(0, Math.min(1, cumulative[index] / total))
    },
  }
}

/**
 * Ease a scroll position toward its target.
 *
 * Assigning the target directly tracks a contour that advances in steps, which
 * reads as twitching. A fixed fraction per frame is frame-rate dependent in
 * principle, but the exponent keeps it stable across the range of frame times
 * a browser actually produces.
 */
export function easeToward(current: number, target: number, deltaMs: number, halfLifeMs = 220): number {
  if (!Number.isFinite(current)) return target
  const factor = 1 - Math.pow(0.5, deltaMs / halfLifeMs)
  const next = current + (target - current) * factor
  // Settle rather than creep forever toward a target a fraction of a pixel away.
  return Math.abs(target - next) < 0.5 ? target : next
}

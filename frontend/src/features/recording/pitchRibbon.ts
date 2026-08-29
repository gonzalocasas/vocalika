/** Geometry and banding for the live pitch ribbon, kept pure so it can be tested. */

export interface ReferenceContour {
  times: number[]
  midi: (number | null)[]
}

export interface ContourPoint {
  time: number
  midi: number | null
}

export type AccuracyBand = "excellent" | "good" | "off" | "unknown"

/** Matches AnalysisConfig's excellent/good tolerances so live and saved agree. */
export const EXCELLENT_CENTS = 15
export const GOOD_CENTS = 25

export function accuracyBand(cents: number | null): AccuracyBand {
  if (cents === null || !Number.isFinite(cents)) return "unknown"
  const magnitude = Math.abs(cents)
  if (magnitude <= EXCELLENT_CENTS) return "excellent"
  if (magnitude <= GOOD_CENTS) return "good"
  return "off"
}

/**
 * Points of the reference contour covering [start, end].
 *
 * One point outside each edge is included so the drawn line runs off the
 * ribbon rather than stopping short of it. `times` is uniformly spaced, so
 * the bounds are arithmetic rather than a scan of 15k frames per animation
 * frame.
 */
export function sliceContour(
  contour: ReferenceContour,
  start: number,
  end: number,
): ContourPoint[] {
  const { times, midi } = contour
  if (times.length === 0 || end <= start) return []
  const step = times.length > 1 ? times[1] - times[0] : 0
  if (step <= 0) return []
  const first = Math.max(0, Math.floor((start - times[0]) / step))
  const last = Math.min(times.length - 1, Math.ceil((end - times[0]) / step))
  const points: ContourPoint[] = []
  for (let index = first; index <= last; index += 1) {
    points.push({ time: times[index], midi: midi[index] ?? null })
  }
  return points
}

/** Reference note at `time`, or null if the reference is silent there. */
export function referenceMidiAt(contour: ReferenceContour, time: number): number | null {
  const { times, midi } = contour
  if (times.length === 0) return null
  const step = times.length > 1 ? times[1] - times[0] : 0
  if (step <= 0) return null
  const index = Math.round((time - times[0]) / step)
  if (index < 0 || index >= times.length) return null
  return midi[index] ?? null
}

/**
 * Vertical extent for the visible window.
 *
 * Padded and floored to a minimum span so a held note does not fill the
 * ribbon top to bottom and make ordinary vibrato look like wild swinging.
 */
export function verticalRange(
  values: (number | null)[],
  { minimumSpan = 12, padding = 2 }: { minimumSpan?: number; padding?: number } = {},
): { low: number; high: number } {
  const present = values.filter((value): value is number => value !== null && Number.isFinite(value))
  if (present.length === 0) return { low: 55, high: 67 }
  let low = Math.min(...present) - padding
  let high = Math.max(...present) + padding
  const span = high - low
  if (span < minimumSpan) {
    const middle = (low + high) / 2
    low = middle - minimumSpan / 2
    high = middle + minimumSpan / 2
  }
  return { low, high }
}

/** Map a value in [low, high] to a y pixel, with high at the top. */
export function midiToY(midi: number, low: number, high: number, height: number): number {
  if (high <= low) return height / 2
  return height - ((midi - low) / (high - low)) * height
}

/** Map a time to an x pixel across the visible window. */
export function timeToX(time: number, start: number, end: number, width: number): number {
  if (end <= start) return 0
  return ((time - start) / (end - start)) * width
}

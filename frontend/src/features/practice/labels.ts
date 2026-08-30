import type { IntervalScore } from "./types"

/**
 * Phrase a cents deviation for a pitch.
 *
 * Every value here comes from the server, so it can be null, absent from an
 * older response, or otherwise not a number. A strict null check misses
 * `undefined` and lets NaN through to the screen, so finiteness is the test.
 */
export function centsLabel(cents: number | null | undefined): string {
  if (!Number.isFinite(cents as number)) return "—"
  const rounded = Math.round(cents as number)
  if (rounded === 0) return "exactly on pitch"
  return `${Math.abs(rounded)}¢ ${rounded < 0 ? "flat" : "sharp"}`
}

/**
 * Describe how a leap missed.
 *
 * An interval is a distance, so it is too wide or too narrow -- "flat" and
 * "sharp" belong to pitches. Descending leaps make the distinction matter:
 * over-jumping downward produces a negative signed error, which the pitch
 * vocabulary would call flat when the singer actually went too far.
 */
export function leapLabel(score: Pick<IntervalScore, "width_error_cents" | "wrong_direction">): string {
  if (score.wrong_direction) return "you leapt the other way"
  const width = score.width_error_cents
  if (!Number.isFinite(width as number)) return "—"
  const rounded = Math.round(width as number)
  if (Math.abs(rounded) < 10) return "exactly the right distance"
  return `${Math.abs(rounded)}¢ too ${rounded > 0 ? "wide" : "narrow"}`
}

/** "5 semitones down" / "7 semitones up", for stating the target leap. */
export function leapSpanLabel(semitones: number | null | undefined): string {
  if (!Number.isFinite(semitones as number)) return "—"
  const value = semitones as number
  const size = Math.abs(value)
  return `${size} semitone${size === 1 ? "" : "s"} ${value < 0 ? "down" : "up"}`
}

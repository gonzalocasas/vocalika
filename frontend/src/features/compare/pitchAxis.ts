import { noteName } from "../../shared/notes.ts"

/**
 * The pitch chart's vertical scale.
 *
 * Plotting MIDI numbers put the chart in semitones while every error the app
 * reports is in cents, so reading one against the other meant dividing by a
 * hundred in your head. In cents the vertical gap between the two contours is
 * the error, directly comparable to the metric tiles beside it.
 *
 * C4 is the zero point: cents are a relative unit and need an anchor, and
 * middle C is the one already built into MIDI numbering.
 */
export const ANCHOR_MIDI = 60

export function midiToCents(midi: number): number {
  return (midi - ANCHOR_MIDI) * 100
}

export function centsToMidi(cents: number): number {
  return cents / 100 + ANCHOR_MIDI
}

/** Convert a plotted series, preserving the nulls that break the line at rests. */
export function seriesToCents(values: Array<number | null>): Array<number | null> {
  return values.map((value) => (value === null || !Number.isFinite(value) ? null : midiToCents(value)))
}

export interface PitchExtent {
  lowMidi: number
  highMidi: number
}

/** The pitch span to show, padded so the contours do not touch the frame. */
export function pitchExtent(series: Array<Array<number | null>>, paddingSemitones = 1.5): PitchExtent {
  const present: number[] = []
  for (const values of series) {
    for (const value of values) {
      if (value !== null && Number.isFinite(value)) present.push(value)
    }
  }
  if (present.length === 0) return { lowMidi: 55, highMidi: 67 }
  let low = Math.min(...present) - paddingSemitones
  let high = Math.max(...present) + paddingSemitones
  // A take that never leaves one note would otherwise be drawn at absurd zoom.
  if (high - low < 6) {
    const middle = (low + high) / 2
    low = middle - 3
    high = middle + 3
  }
  return { lowMidi: low, highMidi: high }
}

// Largest first, because the octave is the interval that reads: every label is
// the same letter, and 1200 cents is the natural unit of the scale. Smaller
// steps are only for views too narrow to fit octaves. A tritone step is
// excluded deliberately -- it alternates C and F# forever, which looks
// regular but tells you nothing.
const TICK_STEPS = [12, 4, 3, 2, 1]

export interface NoteTicks {
  /** Positions in cents, matching the axis the notes are drawn against. */
  tickvals: number[]
  ticktext: string[]
  /** The interval chosen, in semitones -- an octave is 12. */
  stepSemitones: number
  /** First tick, in cents, for a gridline that starts where the labels do. */
  tick0: number
  /** Gridline spacing, in cents. */
  dtick: number
}

/**
 * Note-name ticks across a pitch span.
 *
 * The step widens as the span grows so the labels never collide; zoomed in far
 * enough, every semitone is named.
 */
export function noteTicks(
  { lowMidi, highMidi }: PitchExtent,
  minimumTicks = 3,
): NoteTicks {
  const span = Math.max(0, highMidi - lowMidi)
  // The widest interval that still puts enough lines on the chart to read a
  // scale from. Taking the largest keeps the tick count low by construction.
  const step = TICK_STEPS.find((candidate) => span / candidate >= minimumTicks) ?? 1

  const tickvals: number[] = []
  const ticktext: string[] = []
  // Start from a multiple of the step measured from C, so the labels land on
  // the same notes however the view is scrolled.
  const first = Math.ceil(lowMidi / step) * step
  for (let midi = first; midi <= highMidi; midi += step) {
    tickvals.push(midiToCents(midi))
    ticktext.push(noteName(midi))
  }
  // The cents axis is given the same interval, so its gridlines fall on the
  // notes named opposite rather than on round numbers like 1000 cents, which
  // correspond to nothing musical.
  return {
    tickvals,
    ticktext,
    stepSemitones: step,
    tick0: midiToCents(first),
    dtick: step * 100,
  }
}

const NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

/** Nearest named note in scientific pitch notation; MIDI 60 is C4. */
export function noteName(midi: number): string {
  if (!Number.isFinite(midi)) return "—"
  const nearest = Math.round(midi)
  // JavaScript's % keeps the sign of the dividend, which would produce a
  // negative index for pitches below C-1.
  const pitchClass = ((nearest % 12) + 12) % 12
  return `${NOTE_NAMES[pitchClass]}${Math.floor(nearest / 12) - 1}`
}

export interface VocalRange {
  low_midi: number
  high_midi: number
  median_midi: number
  low_note: string
  high_note: string
  median_note: string
  semitones: number
}

/**
 * The range as the singer would have to sing it.
 *
 * Transposition shifts every pitch by the same amount, so the shifted range is
 * arithmetic. Re-measuring per semitone would mean generating transposed audio
 * and running pyin again for each step of the control.
 */
export function transposedRange(range: VocalRange | null, semitones: number): VocalRange | null {
  if (!range) return null
  if (semitones === 0) return range
  const low = range.low_midi + semitones
  const high = range.high_midi + semitones
  const median = range.median_midi + semitones
  return {
    low_midi: low,
    high_midi: high,
    median_midi: median,
    low_note: noteName(low),
    high_note: noteName(high),
    median_note: noteName(median),
    semitones: range.semitones,
  }
}

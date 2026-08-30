export interface SustainedExercise {
  kind: "sustained"
  id: string
  midi: number
  note: string
  hold_seconds: number
  source_start: number
  source_end: number
}

export interface IntervalExercise {
  kind: "interval"
  id: string
  from_midi: number
  to_midi: number
  from_note: string
  to_note: string
  semitones: number
  name: string
  direction: "up" | "down"
  occurrences: number
  source_start: number
  source_end: number
}

export interface WarmupExercise {
  kind: "warmup"
  id: string
  steps_midi: number[]
  steps_note: string[]
  hold_seconds: number
}

export interface PracticePlan {
  sustained: SustainedExercise[]
  intervals: IntervalExercise[]
  warmup: WarmupExercise | null
  note_count: number
  range: { low_note: string; high_note: string; median_note: string } | null
  transpose_semitones: number
}

export interface HeldNoteScore {
  target_midi: number
  target_note: string
  sung_note: string | null
  centre_cents: number | null
  steadiness_cents: number | null
  held_seconds: number
  coverage: number
  verdict: string
}

export interface IntervalScore {
  first: HeldNoteScore | null
  second: HeldNoteScore | null
  sung_semitones: number | null
  target_semitones: number
  interval_error_cents: number | null
  verdict: string
}

export type AttemptScore = HeldNoteScore | IntervalScore

export function isIntervalScore(score: AttemptScore): score is IntervalScore {
  return "interval_error_cents" in score
}

export const VERDICT_LABEL: Record<string, string> = {
  "on-pitch": "On pitch",
  close: "Close",
  off: "Off",
  "wrong-note": "Wrong note",
  unsteady: "Landed, but wandered",
  "not-heard": "Nothing heard",
}

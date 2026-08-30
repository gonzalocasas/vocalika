/**
 * Sampled grand piano for the practice tones.
 *
 * A recorded piano is far easier to match by ear than a synthesised tone: the
 * harmonics give the ear something to lock onto, where a bare oscillator
 * leaves a singer guessing at an abstract pitch.
 *
 * Samples are spaced every three semitones, so nothing is ever transposed by
 * more than 1.5 semitones from a real recording -- a 9% resampling ratio,
 * where the shift in timbre and decay length is inaudible. Sampling every
 * note would be more faithful and roughly six times the download for a
 * difference nobody could hear.
 *
 * Salamander Grand Piano by Alexander Holm, CC-BY 3.0.
 */

/** MIDI numbers of the recorded notes, C2 to C6, every minor third. */
export const SAMPLE_MIDI = [36, 39, 42, 45, 48, 51, 54, 57, 60, 63, 66, 69, 72, 75, 78, 81, 84]

const FILE_NAMES: Record<number, string> = {
  36: "C2", 39: "Ds2", 42: "Fs2", 45: "A2",
  48: "C3", 51: "Ds3", 54: "Fs3", 57: "A3",
  60: "C4", 63: "Ds4", 66: "Fs4", 69: "A4",
  72: "C5", 75: "Ds5", 78: "Fs5", 81: "A5",
  84: "C6",
}

export function sampleUrl(midi: number): string {
  return `/piano/${FILE_NAMES[midi]}.mp3`
}

/** The recorded note closest to `midi`, so the resampling ratio stays small. */
export function nearestSampleMidi(midi: number): number {
  let best = SAMPLE_MIDI[0]
  let bestDistance = Math.abs(midi - best)
  for (const candidate of SAMPLE_MIDI) {
    const distance = Math.abs(midi - candidate)
    if (distance < bestDistance) {
      best = candidate
      bestDistance = distance
    }
  }
  return best
}

/**
 * Playback rate that shifts a sample to the wanted pitch.
 *
 * Resampling moves pitch and speed together, which is why the note is gated
 * by its own envelope rather than by the sample's length.
 */
export function playbackRateFor(midi: number, sampleMidi: number): number {
  return Math.pow(2, (midi - sampleMidi) / 12)
}

export function midiToHertz(midi: number, concertPitchHertz = 440): number {
  return concertPitchHertz * Math.pow(2, (midi - 69) / 12)
}

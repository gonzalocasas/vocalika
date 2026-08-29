/**
 * Monophonic pitch detection for the live recording display.
 *
 * This is deliberately not the analysis pipeline. pyin runs offline over a
 * whole take with an HMM that revises earlier frames once later ones arrive;
 * a singer needs to see the note while it is still sounding, so this trades
 * that accuracy for a verdict on one buffer with no lookahead. Numbers shown
 * during recording are a guide, and the take's saved analysis remains the
 * authority.
 *
 * The method is YIN's difference function with cumulative mean normalisation,
 * which is what makes it robust to the octave errors a plain autocorrelation
 * makes on strong harmonics.
 */

export const NO_PITCH = 0

export interface PitchReading {
  /** Fundamental in Hz, or NO_PITCH when the buffer is unvoiced. */
  hertz: number
  /** 0..1, from YIN's aperiodicity; higher is more confidently periodic. */
  clarity: number
}

export interface DetectPitchOptions {
  /** Below this, the buffer is treated as silence and never as a note. */
  minimumRms?: number
  /** YIN's absolute threshold on the normalised difference. */
  threshold?: number
  minimumHertz?: number
  maximumHertz?: number
}

const DEFAULTS: Required<DetectPitchOptions> = {
  minimumRms: 0.01,
  threshold: 0.15,
  // C2..C6, matching the analysis pipeline's pitch_min_midi/pitch_max_midi.
  minimumHertz: 65.4,
  maximumHertz: 1046.5,
}

export function rootMeanSquare(buffer: Float32Array): number {
  let total = 0
  for (let index = 0; index < buffer.length; index += 1) total += buffer[index] * buffer[index]
  return Math.sqrt(total / buffer.length)
}

/**
 * Refine an integer lag to sub-sample precision.
 *
 * At 44.1 kHz one sample of lag is already several cents wide around A4, so
 * without this the readout would visibly quantise on held notes.
 */
function parabolicMinimum(values: Float32Array, index: number): number {
  if (index <= 0 || index >= values.length - 1) return index
  const previous = values[index - 1]
  const current = values[index]
  const next = values[index + 1]
  const denominator = 2 * (2 * current - next - previous)
  if (denominator === 0) return index
  return index + (next - previous) / denominator
}

export function detectPitch(
  buffer: Float32Array,
  sampleRate: number,
  options: DetectPitchOptions = {},
): PitchReading {
  const { minimumRms, threshold, minimumHertz, maximumHertz } = { ...DEFAULTS, ...options }

  if (rootMeanSquare(buffer) < minimumRms) return { hertz: NO_PITCH, clarity: 0 }

  const maximumLag = Math.min(Math.floor(sampleRate / minimumHertz), Math.floor(buffer.length / 2))
  const minimumLag = Math.max(2, Math.floor(sampleRate / maximumHertz))
  if (maximumLag <= minimumLag) return { hertz: NO_PITCH, clarity: 0 }

  // Squared difference between the signal and itself delayed by `lag`.
  const difference = new Float32Array(maximumLag + 1)
  for (let lag = minimumLag; lag <= maximumLag; lag += 1) {
    let total = 0
    for (let index = 0; index + lag < buffer.length; index += 1) {
      const delta = buffer[index] - buffer[index + lag]
      total += delta * delta
    }
    difference[lag] = total
  }

  // Cumulative mean normalisation. Dividing by the running mean is what stops
  // the trivial minimum at lag 0 from winning and suppresses the sub-harmonic
  // dips that cause octave-down errors.
  const normalised = new Float32Array(maximumLag + 1)
  normalised[0] = 1
  let runningTotal = 0
  for (let lag = minimumLag; lag <= maximumLag; lag += 1) {
    runningTotal += difference[lag]
    normalised[lag] = runningTotal === 0 ? 1 : (difference[lag] * (lag - minimumLag + 1)) / runningTotal
  }

  // First lag that dips below the threshold, taken at its local minimum --
  // the *first* such dip, not the deepest, because the deepest is usually an
  // octave below.
  let chosen = -1
  for (let lag = minimumLag; lag <= maximumLag; lag += 1) {
    if (normalised[lag] < threshold) {
      while (lag + 1 <= maximumLag && normalised[lag + 1] < normalised[lag]) lag += 1
      chosen = lag
      break
    }
  }
  if (chosen === -1) return { hertz: NO_PITCH, clarity: 0 }

  const refined = parabolicMinimum(normalised, chosen)
  const hertz = sampleRate / refined
  if (hertz < minimumHertz || hertz > maximumHertz) return { hertz: NO_PITCH, clarity: 0 }

  return { hertz, clarity: Math.max(0, Math.min(1, 1 - normalised[chosen])) }
}

export function hertzToMidi(hertz: number, concertPitchHertz = 440): number {
  return 69 + 12 * Math.log2(hertz / concertPitchHertz)
}

/** Signed cents from `midi` to the nearest note of the reference contour. */
export function centsBetween(midi: number, referenceMidi: number): number {
  return (midi - referenceMidi) * 100
}

/**
 * Round-trip latency from a loopback: chirps played, the microphone listening.
 *
 * The studio plays and records on one audio clock, so a chirp scheduled at a
 * known frame and found in the capture at a later frame tells exactly how long
 * sound takes from being rendered to coming back in: output plus input
 * latency, the delay every take carries. A chirp (a short frequency sweep) is
 * used rather than a click because its correlation peak stays sharp through a
 * speaker, the air and a microphone.
 */

export const CHIRP_SECONDS = 0.02
export const CLICK_COUNT = 8
export const CLICK_SPACING_SECONDS = 0.5
/** Longest round trip looked for; Bluetooth headphones stay well under this. */
export const MAX_LATENCY_SECONDS = 0.4

export interface LatencyResult {
  /** Median arrival delay of the chirps that were heard clearly. */
  seconds: number
  /** Spread between the earliest and latest arrival, a measure of trust. */
  spreadSeconds: number
  detected: number
}

/** A Hann-windowed 600 Hz to 5 kHz sweep: audible, and pinpointable. */
export function makeChirp(sampleRate: number): Float32Array {
  const length = Math.round(CHIRP_SECONDS * sampleRate)
  const chirp = new Float32Array(length)
  const [low, high] = [600, 5000]
  for (let i = 0; i < length; i += 1) {
    const t = i / sampleRate
    const phase = 2 * Math.PI * (low * t + ((high - low) / (2 * CHIRP_SECONDS)) * t * t)
    const window = 0.5 - 0.5 * Math.cos((2 * Math.PI * i) / (length - 1))
    chirp[i] = Math.sin(phase) * window
  }
  return chirp
}

/** The sequence played: CLICK_COUNT chirps, CLICK_SPACING_SECONDS apart. */
export function makeClickTrack(sampleRate: number, level = 0.5): Float32Array {
  const chirp = makeChirp(sampleRate)
  const spacing = Math.round(CLICK_SPACING_SECONDS * sampleRate)
  const track = new Float32Array(spacing * CLICK_COUNT + Math.round(MAX_LATENCY_SECONDS * sampleRate))
  for (let k = 0; k < CLICK_COUNT; k += 1) {
    for (let i = 0; i < chirp.length; i += 1) track[k * spacing + i] = chirp[i] * level
  }
  return track
}

function median(values: number[]): number {
  const sorted = [...values].sort((a, b) => a - b)
  const middle = Math.floor(sorted.length / 2)
  return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2
}

/**
 * Find each chirp in `captured`, where capture frame 0 is the frame the first
 * chirp was played at. Returns null when the chirps were not heard clearly
 * enough to trust: too few found, or arrivals that disagree.
 */
export function measureLatency(captured: Float32Array, sampleRate: number): LatencyResult | null {
  const chirp = makeChirp(sampleRate)
  const spacing = Math.round(CLICK_SPACING_SECONDS * sampleRate)
  const reach = Math.round(MAX_LATENCY_SECONDS * sampleRate)
  const arrivals: number[] = []
  for (let k = 0; k < CLICK_COUNT; k += 1) {
    const start = k * spacing
    const scores = new Float32Array(reach)
    for (let lag = 0; lag < reach; lag += 1) {
      const at = start + lag
      if (at + chirp.length > captured.length) break
      let sum = 0
      for (let i = 0; i < chirp.length; i += 1) sum += captured[at + i] * chirp[i]
      // Polarity can flip on the way through a speaker and microphone.
      scores[lag] = Math.abs(sum)
    }
    let best = 0
    for (let lag = 1; lag < reach; lag += 1) if (scores[lag] > scores[best]) best = lag
    const floor = median(Array.from(scores)) || 1e-12
    if (scores[best] >= 8 * floor) arrivals.push(best)
  }
  if (arrivals.length < Math.ceil(CLICK_COUNT * 0.75)) return null
  const spread = Math.max(...arrivals) - Math.min(...arrivals)
  // Chirps from one device pair arrive within a few samples of each other;
  // anything wider is echoes or noise winning some of the time.
  if (spread > 0.002 * sampleRate) return null
  return { seconds: median(arrivals) / sampleRate, spreadSeconds: spread / sampleRate, detected: arrivals.length }
}

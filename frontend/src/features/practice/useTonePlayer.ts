import { onBeforeUnmount, ref } from "vue"

import { midiToHertz, nearestSampleMidi, playbackRateFor, sampleUrl } from "./pianoSamples"

export { midiToHertz }

export interface ToneStep {
  midi: number
  seconds: number
}

/** Decoded samples are shared across every player instance and every visit. */
const decoded = new Map<number, AudioBuffer>()

/**
 * Plays reference pitches for the practice exercises, on a sampled grand piano.
 *
 * A recorded piano is much easier to match by ear than a bare oscillator: the
 * harmonics give the ear something to lock onto. If a sample cannot be loaded
 * the player falls back to a synthesised tone rather than going silent --
 * practice with an imperfect reference beats no reference at all.
 */
export function useTonePlayer() {
  const playing = ref(false)
  const usingSamples = ref(true)
  let context: AudioContext | null = null
  let stopAt = 0
  let sequence = 0

  function ensureContext(): AudioContext {
    if (!context) context = new AudioContext()
    return context
  }

  async function bufferFor(sampleMidi: number, audio: AudioContext): Promise<AudioBuffer | null> {
    const cached = decoded.get(sampleMidi)
    if (cached) return cached
    try {
      const response = await fetch(sampleUrl(sampleMidi))
      if (!response.ok) throw new Error(`sample ${sampleMidi} unavailable`)
      const buffer = await audio.decodeAudioData(await response.arrayBuffer())
      decoded.set(sampleMidi, buffer)
      return buffer
    } catch {
      usingSamples.value = false
      return null
    }
  }

  function stop(): void {
    playing.value = false
    stopAt = 0
    sequence += 1
    if (context) {
      void context.close()
      context = null
    }
  }

  /** A note the sampler could not supply: better than silence. */
  function scheduleSynth(audio: AudioContext, step: ToneStep, at: number): void {
    const oscillator = audio.createOscillator()
    const gain = audio.createGain()
    oscillator.type = "triangle"
    oscillator.frequency.value = midiToHertz(step.midi)
    gain.gain.setValueAtTime(0, at)
    gain.gain.linearRampToValueAtTime(0.22, at + 0.02)
    gain.gain.setValueAtTime(0.22, at + step.seconds - 0.08)
    gain.gain.linearRampToValueAtTime(0, at + step.seconds)
    oscillator.connect(gain)
    gain.connect(audio.destination)
    oscillator.start(at)
    oscillator.stop(at + step.seconds)
  }

  function scheduleSample(
    audio: AudioContext,
    buffer: AudioBuffer,
    step: ToneStep,
    sampleMidi: number,
    at: number,
  ): void {
    const source = audio.createBufferSource()
    const gain = audio.createGain()
    source.buffer = buffer
    source.playbackRate.value = playbackRateFor(step.midi, sampleMidi)
    // The recordings run to 20 seconds of decay, so the note is ended by its
    // own envelope rather than by the sample running out. The release is long
    // enough to sound like a damper rather than a cut.
    const release = Math.min(0.35, step.seconds * 0.3)
    gain.gain.setValueAtTime(0.85, at)
    gain.gain.setValueAtTime(0.85, at + step.seconds - release)
    gain.gain.exponentialRampToValueAtTime(0.0001, at + step.seconds)
    source.connect(gain)
    gain.connect(audio.destination)
    source.start(at)
    source.stop(at + step.seconds + 0.02)
  }

  async function playSequence(steps: ToneStep[], gapSeconds = 0.12): Promise<void> {
    stop()
    if (steps.length === 0) return
    const token = sequence
    const audio = ensureContext()
    if (audio.state === "suspended") await audio.resume()

    // Decoding is async, so every buffer is fetched before anything is
    // scheduled -- otherwise the gap between notes would vary with how long
    // each sample took to arrive.
    const wanted = [...new Set(steps.map((step) => nearestSampleMidi(step.midi)))]
    const buffers = new Map<number, AudioBuffer | null>()
    for (const sampleMidi of wanted) {
      buffers.set(sampleMidi, await bufferFor(sampleMidi, audio))
    }
    // A stop, or another sequence, landed while we were decoding.
    if (token !== sequence || context !== audio) return

    let cursor = audio.currentTime + 0.05
    for (const step of steps) {
      const sampleMidi = nearestSampleMidi(step.midi)
      const buffer = buffers.get(sampleMidi)
      if (buffer) scheduleSample(audio, buffer, step, sampleMidi, cursor)
      else scheduleSynth(audio, step, cursor)
      cursor += step.seconds + gapSeconds
    }

    playing.value = true
    stopAt = cursor
    window.setTimeout(
      () => {
        if (token === sequence) playing.value = false
      },
      Math.max(0, (stopAt - audio.currentTime) * 1000),
    )
  }

  function playNote(midi: number, seconds: number): Promise<void> {
    return playSequence([{ midi, seconds }])
  }

  /** Warm the cache so the first TRY does not wait on a download. */
  async function preload(midiValues: number[]): Promise<void> {
    const audio = ensureContext()
    for (const sampleMidi of new Set(midiValues.map(nearestSampleMidi))) {
      await bufferFor(sampleMidi, audio)
    }
  }

  onBeforeUnmount(stop)

  return { playing, usingSamples, playNote, playSequence, preload, stop }
}

import { ref, shallowRef } from "vue"

import { detectPitch, hertzToMidi, NO_PITCH } from "./detectPitch"

/** One sung moment, in the reference's own timeline. */
export interface LivePitchSample {
  /** Seconds into the reference, so samples line up with its contour. */
  time: number
  /** MIDI note, or null when unvoiced. */
  midi: number | null
  clarity: number
}

const ANALYSIS_WINDOW = 2048
/**
 * Roughly 1.5 s of history at ~60 Hz. Enough to see the phrase you are in
 * without the ribbon becoming a wall of past mistakes.
 */
const MAX_SAMPLES = 96

export function useLivePitch() {
  const samples = shallowRef<LivePitchSample[]>([])
  const current = ref<LivePitchSample | null>(null)
  const active = ref(false)
  const error = ref("")

  let context: AudioContext | null = null
  let analyser: AnalyserNode | null = null
  let source: MediaStreamAudioSourceNode | null = null
  let buffer = new Float32Array(ANALYSIS_WINDOW)
  let frame: number | undefined
  let readClock: (() => number) | null = null

  function loop(): void {
    if (!analyser || !context || !readClock) return
    analyser.getFloatTimeDomainData(buffer)
    const { hertz, clarity } = detectPitch(buffer, context.sampleRate)
    const sample: LivePitchSample = {
      time: readClock(),
      midi: hertz === NO_PITCH ? null : hertzToMidi(hertz),
      clarity,
    }
    current.value = sample
    // Replaced rather than mutated: shallowRef only notifies on reassignment.
    const next = samples.value.concat(sample)
    samples.value = next.length > MAX_SAMPLES ? next.slice(next.length - MAX_SAMPLES) : next
    frame = window.requestAnimationFrame(loop)
  }

  /**
   * @param stream  the same MediaStream being recorded, so the display cannot
   *                drift from what is actually captured.
   * @param clock   reference-time source, normally the monitor audio element's
   *                currentTime. Wall-clock would drift from the backing track.
   */
  async function start(stream: MediaStream, clock: () => number): Promise<void> {
    stop()
    try {
      context = new AudioContext()
      if (context.state === "suspended") await context.resume()
      analyser = context.createAnalyser()
      analyser.fftSize = ANALYSIS_WINDOW
      // Time-domain reads only; smoothing would blur the onsets we want.
      analyser.smoothingTimeConstant = 0
      buffer = new Float32Array(analyser.fftSize)
      source = context.createMediaStreamSource(stream)
      source.connect(analyser)
      // Deliberately not connected to the destination: routing the microphone
      // to the speakers would feed back into the recording.
      readClock = clock
      active.value = true
      error.value = ""
      frame = window.requestAnimationFrame(loop)
    } catch (reason) {
      error.value = reason instanceof Error ? reason.message : String(reason)
      stop()
    }
  }

  function stop(): void {
    if (frame !== undefined) window.cancelAnimationFrame(frame)
    frame = undefined
    source?.disconnect()
    analyser?.disconnect()
    void context?.close()
    source = null
    analyser = null
    context = null
    readClock = null
    active.value = false
  }

  function reset(): void {
    samples.value = []
    current.value = null
  }

  return { samples, current, active, error, start, stop, reset }
}

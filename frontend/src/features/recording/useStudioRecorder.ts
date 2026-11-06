import { computed, onBeforeUnmount, ref, shallowRef } from "vue"

import { latencyForPair, openMicrophone, outputsSettled } from "../../shared/audioDevices"
import { StudioEngine, type StemUrls } from "./studioEngine"

/**
 * The recording studio's take: backing track and microphone on one clock.
 *
 * Replaces the earlier pairing of <audio> elements with a MediaRecorder,
 * whose take offset was a snapshot of two unrelated clocks and drifted by
 * tens of milliseconds from take to take. See StudioEngine.
 */
export function useStudioRecorder() {
  const state = ref<"loading" | "idle" | "requesting" | "recording" | "paused" | "ready" | "error">("loading")
  const error = ref("")
  const elapsedSeconds = ref(0)
  const recordedFile = shallowRef<File | null>(null)
  const stream = shallowRef<MediaStream | null>(null)
  /** Take offset for the server: positive means lead-in. Exact by construction. */
  const offset = ref<number | null>(null)
  /** The round trip compensated in this take, or null when never measured. */
  const latency = ref<number | null>(null)
  const supported = computed(() => typeof AudioWorkletNode !== "undefined")
  let engine: StudioEngine | null = null
  let loadRequest = 0
  let ticker: number | undefined
  let end = 0

  async function load(urls: StemUrls): Promise<void> {
    const request = ++loadRequest
    engine?.close()
    engine = null
    state.value = "loading"
    error.value = ""
    try {
      const loaded = await StudioEngine.load(urls)
      if (request !== loadRequest) {
        loaded.close()
        return
      }
      engine = loaded
      state.value = recordedFile.value ? "ready" : "idle"
    } catch (reason) {
      if (request !== loadRequest) return
      error.value = reason instanceof Error ? reason.message : String(reason)
      state.value = "error"
    }
  }

  function releaseMicrophone(): void {
    stream.value?.getTracks().forEach((track) => track.stop())
    stream.value = null
  }

  function stopTicking(): void {
    if (ticker !== undefined) window.clearInterval(ticker)
    ticker = undefined
  }

  function startTicking(): void {
    stopTicking()
    ticker = window.setInterval(() => {
      if (!engine) return
      elapsedSeconds.value = engine.capturedSeconds()
      if (state.value === "recording" && engine.reachedEnd()) void stop()
    }, 100)
  }

  /** Record from `from` to `to` seconds of the reference. */
  async function start(from: number, to: number, voiceLevel: number): Promise<void> {
    if (!engine || (state.value !== "idle" && state.value !== "ready" && state.value !== "error")) return
    state.value = "requesting"
    error.value = ""
    recordedFile.value = null
    elapsedSeconds.value = 0
    try {
      stream.value = await openMicrophone({
        echoCancellation: false, noiseSuppression: false, autoGainControl: false,
      })
      await engine.attachMicrophone(stream.value)
      // The chosen output must be in place before the first note, or the
      // take would be timed for a path it never played through.
      await outputsSettled()
      engine.setVoiceLevel(voiceLevel)
      end = to
      // Known once the microphone is open: the pair is named by what is in use.
      latency.value = latencyForPair()?.seconds ?? null
      engine.play(from, to)
      // Take sample 0 is rendered at reference time `from`, but the singer
      // hears it, and is heard back, one round trip later. So reference time
      // t is at take[t - from + latency]: offset = latency - from.
      offset.value = (latency.value ?? 0) - from
      state.value = "recording"
      startTicking()
    } catch (reason) {
      engine.abandon()
      releaseMicrophone()
      error.value = reason instanceof Error ? reason.message : String(reason)
      state.value = "error"
    }
  }

  function pause(): void {
    if (!engine || state.value !== "recording") return
    engine.hold()
    state.value = "paused"
  }

  function resume(): void {
    if (!engine || state.value !== "paused") return
    engine.play(engine.position(), end)
    state.value = "recording"
  }

  async function stop(): Promise<void> {
    if (!engine || (state.value !== "recording" && state.value !== "paused")) return
    stopTicking()
    state.value = "requesting"
    try {
      recordedFile.value = await engine.finish()
      elapsedSeconds.value = engine.capturedSeconds()
      state.value = "ready"
    } catch (reason) {
      error.value = reason instanceof Error ? reason.message : String(reason)
      state.value = "error"
    } finally {
      releaseMicrophone()
    }
  }

  function discard(): void {
    recordedFile.value = null
    offset.value = null
    elapsedSeconds.value = 0
    state.value = engine ? "idle" : "loading"
  }

  onBeforeUnmount(() => {
    stopTicking()
    loadRequest += 1
    engine?.close()
    engine = null
    releaseMicrophone()
  })

  return {
    state, error, elapsedSeconds, recordedFile, stream, offset, latency, supported,
    load, start, pause, resume, stop, discard,
    position: () => engine?.position() ?? 0,
    setVoiceLevel: (level: number) => engine?.setVoiceLevel(level),
  }
}

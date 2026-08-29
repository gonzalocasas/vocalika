import { computed, onBeforeUnmount, ref } from "vue"

export function useMicrophoneRecorder() {
  const state = ref<"idle" | "requesting" | "recording" | "ready" | "error">("idle")
  const elapsedSeconds = ref(0)
  const recordedFile = ref<File | null>(null)
  const error = ref("")
  // Exposed so the live pitch display analyses exactly the stream being
  // recorded, rather than opening a second one that could differ in gain or
  // device.
  const stream = ref<MediaStream | null>(null)
  let recorder: MediaRecorder | null = null
  let chunks: Blob[] = []
  let timer: number | undefined
  let startedAt = 0

  const supported = computed(() => typeof MediaRecorder !== "undefined")

  function preferredMimeType(): string {
    const candidates = ["audio/webm;codecs=opus", "audio/ogg;codecs=opus", "audio/webm"]
    return candidates.find((candidate) => MediaRecorder.isTypeSupported(candidate)) ?? ""
  }

  function cleanupStream(): void {
    stream.value?.getTracks().forEach((track) => track.stop())
    stream.value = null
    if (timer !== undefined) window.clearInterval(timer)
    timer = undefined
  }

  async function start(): Promise<void> {
    if (!supported.value) {
      error.value = "This browser does not support microphone recording."
      state.value = "error"
      return
    }
    state.value = "requesting"
    error.value = ""
    recordedFile.value = null
    try {
      stream.value = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false },
      })
      const mimeType = preferredMimeType()
      recorder = new MediaRecorder(stream.value, mimeType ? { mimeType } : undefined)
      chunks = []
      recorder.addEventListener("dataavailable", (event) => {
        if (event.data.size > 0) chunks.push(event.data)
      })
      recorder.addEventListener("stop", () => {
        const type = recorder?.mimeType || mimeType || "audio/webm"
        const extension = type.includes("ogg") ? "ogg" : "webm"
        const timestamp = new Date().toISOString().replace(/[:.]/g, "-")
        recordedFile.value = new File(chunks, `recorded-take-${timestamp}.${extension}`, { type })
        cleanupStream()
        state.value = "ready"
      }, { once: true })
      recorder.start(250)
      startedAt = performance.now()
      elapsedSeconds.value = 0
      timer = window.setInterval(() => {
        elapsedSeconds.value = (performance.now() - startedAt) / 1000
      }, 100)
      state.value = "recording"
    } catch (reason) {
      cleanupStream()
      error.value = reason instanceof Error ? reason.message : String(reason)
      state.value = "error"
    }
  }

  function stop(): void {
    if (recorder?.state === "recording") recorder.stop()
  }

  function discard(): void {
    recordedFile.value = null
    elapsedSeconds.value = 0
    state.value = "idle"
  }

  onBeforeUnmount(() => {
    if (recorder?.state === "recording") recorder.stop()
    cleanupStream()
  })

  return { state, elapsedSeconds, recordedFile, error, supported, stream, start, stop, discard }
}

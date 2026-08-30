import { ref } from "vue"

import { useMicrophoneRecorder } from "../recording/useMicrophoneRecorder"
import type { AttemptScore } from "./types"

/**
 * Record one exercise attempt and have the server score it.
 *
 * Scoring deliberately happens on the server with the analysis extractor, not
 * in the browser with the live estimator. The live display may be approximate
 * because a singer reads it as a hint while singing; a verdict they will act
 * on afterwards has to be right, which is worth the round trip.
 */
export function useAttempt(projectId: string) {
  const recorder = useMicrophoneRecorder()
  const scoring = ref(false)
  const score = ref<AttemptScore | null>(null)
  const error = ref("")
  const activeId = ref<string | null>(null)
  let stopTimer: number | undefined

  async function record(exerciseId: string, seconds: number): Promise<void> {
    reset()
    activeId.value = exerciseId
    await recorder.start()
    if (recorder.state.value !== "recording") {
      error.value = recorder.error.value || "Could not start the microphone."
      activeId.value = null
      return
    }
    // A little longer than the target, so the singer is not cut off mid-note
    // and the release can be trimmed rather than scored.
    stopTimer = window.setTimeout(() => void finish(), (seconds + 0.6) * 1000)
  }

  async function finish(): Promise<void> {
    if (stopTimer !== undefined) window.clearTimeout(stopTimer)
    stopTimer = undefined
    recorder.stop()
  }

  async function submit(
    kind: "sustained" | "interval" | "warmup",
    targetMidi: number,
    toMidi?: number,
  ): Promise<void> {
    const file = recorder.recordedFile.value
    if (!file) return
    scoring.value = true
    error.value = ""
    try {
      const body = new FormData()
      body.append("audio_file", file)
      body.append("kind", kind === "warmup" ? "sustained" : kind)
      body.append("target_midi", String(targetMidi))
      if (toMidi !== undefined) body.append("to_midi", String(toMidi))
      const response = await fetch(`/api/projects/${projectId}/practice/attempt`, {
        method: "POST",
        body,
      })
      const payload = await response.json()
      if (!response.ok) throw new Error(payload.detail ?? "Could not score that attempt.")
      score.value = payload as AttemptScore
    } catch (reason) {
      error.value = reason instanceof Error ? reason.message : String(reason)
    } finally {
      scoring.value = false
      recorder.discard()
    }
  }

  function reset(): void {
    if (stopTimer !== undefined) window.clearTimeout(stopTimer)
    stopTimer = undefined
    score.value = null
    error.value = ""
    activeId.value = null
    recorder.discard()
  }

  return { recorder, scoring, score, error, activeId, record, finish, submit, reset }
}

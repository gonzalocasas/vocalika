import { computed, ref, watch, type Ref } from "vue"

import { apiJson } from "../../shared/api"
import type { Project } from "../../shared/types"
import { activeLineIndex, activeWordIndex, timingMatches, type LyricsTiming } from "./lyricsTiming"

/**
 * Word timings for a project's saved lyrics, and what is being sung at `time`.
 *
 * The first request for a text runs the aligner on the server, which takes
 * some seconds; later ones are a cache read. A request outrun by a newer
 * save is discarded so a slow alignment cannot overwrite a fresh one.
 * `lyrics` is the text on screen: timings only apply while it matches what
 * was timed, so an unsaved edit falls back to plain text.
 */
export function useLyricsTiming(project: Ref<Project>, lyrics: Ref<string>, time: Ref<number>) {
  const timing = ref<LyricsTiming | null>(null)
  const state = ref<"idle" | "aligning" | "ready" | "failed">("idle")
  let request = 0

  async function load(): Promise<void> {
    const current = ++request
    if (!project.value.lyrics.trim()) {
      timing.value = null
      state.value = "idle"
      return
    }
    state.value = "aligning"
    try {
      const payload = await apiJson<LyricsTiming>(`/api/projects/${project.value.id}/lyrics/timing`)
      if (current !== request) return
      timing.value = payload
      state.value = "ready"
    } catch {
      if (current !== request) return
      timing.value = null
      state.value = "failed"
    }
  }

  watch(() => [project.value.id, project.value.lyrics], () => { void load() }, { immediate: true })

  const lines = computed(() => (timingMatches(timing.value, lyrics.value) ? timing.value.lines : null))
  const activeLine = computed(() => (lines.value ? activeLineIndex(lines.value, time.value) : -1))
  const activeWord = computed(() =>
    lines.value ? activeWordIndex(lines.value[activeLine.value], time.value) : -1,
  )
  const label = computed(() => {
    if (lines.value) return "TIMED TO THE VOCAL"
    if (state.value === "aligning") return "TIMING LYRICS…"
    if (state.value === "failed") return "UNTIMED"
    return ""
  })

  /** Scroll offset that puts the sung line a third of the way down `element`. */
  function lineScrollTarget(element: HTMLElement): number | null {
    if (activeLine.value < 0) return 0
    const line = element.querySelector<HTMLElement>(`[data-line="${activeLine.value}"]`)
    return line ? line.offsetTop - element.clientHeight / 3 : null
  }

  return { lines, activeLine, activeWord, label, lineScrollTarget }
}

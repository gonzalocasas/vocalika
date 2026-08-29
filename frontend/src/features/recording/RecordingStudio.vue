<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue"

import { apiJson } from "../../shared/api"
import type { Project } from "../../shared/types"
import PitchRibbon from "./PitchRibbon.vue"
import type { ReferenceContour } from "./pitchRibbon"
import { referenceMidiAt } from "./pitchRibbon"
import { createScrollProgress, easeToward } from "./lyricsScroll"
import { useLivePitch } from "./useLivePitch"
import { useMicrophoneRecorder } from "./useMicrophoneRecorder"

const props = defineProps<{ project: Project; busy: boolean }>()
const emit = defineEmits<{
  submit: [file: File, isolate: boolean]
  updateLyrics: [lyrics: string]
  close: []
}>()

const FONT_STEPS = [20, 24, 28, 34, 40, 48]
const FONT_STORAGE_KEY = "vocalika.lyricsFontStep"

const isolate = ref(false)
const voiceLevel = ref(35)
const lyrics = ref(props.project.lyrics)
const editingLyrics = ref(!props.project.lyrics.trim())
const fontStep = ref(2)
const vocalAudio = ref<HTMLAudioElement | null>(null)
const instrumentalAudio = ref<HTMLAudioElement | null>(null)
const recorder = useMicrophoneRecorder()
const livePitch = useLivePitch()
const recordedUrl = ref("")
const contour = ref<ReferenceContour | null>(null)
const monitorTime = ref(0)
const lyricsView = ref<HTMLElement | null>(null)
const autoScroll = ref(true)
let stopTimer: number | undefined
let scrollFrame: number | undefined
let lastFrameAt = 0
let suspendScrollUntil = 0
let easedScrollTop = Number.NaN

const recording = computed(() => recorder.state.value === "recording")
const paused = computed(() => recorder.state.value === "paused")
// Paused is still mid-take: the reference is held, not finished.
const inTake = computed(() => recording.value || paused.value)
const lyricsFontSize = computed(() => `${FONT_STEPS[fontStep.value]}px`)

function setFontStep(next: number): void {
  fontStep.value = Math.max(0, Math.min(FONT_STEPS.length - 1, next))
  // A singer sets a comfortable reading size once; remembering it per browser
  // saves doing it at the start of every session.
  try {
    window.localStorage.setItem(FONT_STORAGE_KEY, String(fontStep.value))
  } catch {
    // Private windows and blocked site data are fine; the size just resets.
  }
}

// The reference contour is keyed by transposition, so a project retuned
// between takes must not be shown against the old key's contour.
async function loadContour(): Promise<void> {
  contour.value = null
  try {
    contour.value = await apiJson<ReferenceContour>(
      `/api/projects/${props.project.id}/reference/pitch?transpose=${props.project.transpose_semitones}`,
    )
  } catch {
    // A missing contour only costs the live display; recording still works.
    contour.value = null
  }
}

const liveCents = computed(() => {
  const sample = livePitch.current.value
  if (!sample || sample.midi === null || !contour.value) return null
  const target = referenceMidiAt(contour.value, sample.time)
  return target === null ? null : Math.round((sample.midi - target) * 100)
})

const scrollProgress = computed(() =>
  createScrollProgress(contour.value, props.project.trim_start_seconds, referenceEnd()),
)

/**
 * Follow the lyric while a take runs.
 *
 * Position comes from how much of the reference vocal has been sung, so the
 * page holds still through an intro or a solo instead of running ahead. The
 * eased assignment keeps it a drift rather than a series of small jumps.
 */
function scrollLoop(timestamp: number): void {
  const element = lyricsView.value
  const delta = lastFrameAt ? Math.min(100, timestamp - lastFrameAt) : 16
  lastFrameAt = timestamp
  if (element && autoScroll.value && inTake.value && timestamp >= suspendScrollUntil) {
    const range = element.scrollHeight - element.clientHeight
    if (range > 4) {
      const target = scrollProgress.value.at(monitorTime.value) * range
      const from = Number.isFinite(easedScrollTop) ? easedScrollTop : element.scrollTop
      easedScrollTop = easeToward(from, target, delta)
      element.scrollTop = easedScrollTop
    }
  }
  scrollFrame = window.requestAnimationFrame(scrollLoop)
}

/** A singer looking ahead should not have to fight the page back. */
function noteManualScroll(): void {
  suspendScrollUntil = performance.now() + 4000
  easedScrollTop = Number.NaN
}

const timecode = computed(() => {
  const minutes = Math.floor(recorder.elapsedSeconds.value / 60)
  const seconds = recorder.elapsedSeconds.value - minutes * 60
  return `${String(minutes).padStart(2, "0")}:${seconds.toFixed(1).padStart(4, "0")}`
})

function stopMonitor(): void {
  vocalAudio.value?.pause()
  instrumentalAudio.value?.pause()
  if (stopTimer !== undefined) window.clearTimeout(stopTimer)
  stopTimer = undefined
}

function referenceEnd(): number {
  return props.project.trim_end_seconds ?? props.project.reference.duration_seconds
}

function playMonitor(): Promise<unknown> {
  return Promise.all([
    vocalAudio.value?.play(),
    instrumentalAudio.value?.play(),
  ].filter((promise): promise is Promise<void> => promise !== undefined))
}

/**
 * Schedule the automatic stop from where the reference actually is.
 *
 * Deriving the deadline from the monitor's position rather than from a fixed
 * duration set at the start is what lets a take be paused: the remaining time
 * is recomputed on every resume instead of running down during the gap.
 */
function armStopTimer(): void {
  if (stopTimer !== undefined) window.clearTimeout(stopTimer)
  const clockSource = vocalAudio.value ?? instrumentalAudio.value
  const position = clockSource?.currentTime ?? props.project.trim_start_seconds
  stopTimer = window.setTimeout(stopRecording, Math.max(0.1, referenceEnd() - position) * 1000)
}

// Time comes from the monitor element, not the wall clock: the ribbon has to
// stay locked to the backing track the singer is actually hearing, and a
// paused monitor must hold the ribbon still.
async function startLivePitch(): Promise<void> {
  const clockSource = vocalAudio.value ?? instrumentalAudio.value
  const stream = recorder.stream.value
  if (!stream) return
  await livePitch.start(stream, () => {
    monitorTime.value = clockSource?.currentTime ?? 0
    return monitorTime.value
  })
}

async function startRecording(): Promise<void> {
  // Reading and editing are different modes; nobody wants a textarea in front
  // of them while singing.
  editingLyrics.value = false
  livePitch.reset()
  await recorder.start()
  if (recorder.state.value !== "recording") return
  const start = props.project.trim_start_seconds
  if (vocalAudio.value) {
    vocalAudio.value.currentTime = start
    vocalAudio.value.volume = voiceLevel.value / 100
  }
  if (instrumentalAudio.value) {
    instrumentalAudio.value.currentTime = start
    instrumentalAudio.value.volume = 1
  }
  if (lyricsView.value) lyricsView.value.scrollTop = 0
  easedScrollTop = Number.NaN
  suspendScrollUntil = 0
  await playMonitor()
  armStopTimer()
  await startLivePitch()
}

function pauseRecording(): void {
  // The recorder and the reference have to stop together, or the take would
  // resume misaligned against the contour it is scored on.
  recorder.pause()
  stopMonitor()
  livePitch.stop()
}

async function resumeRecording(): Promise<void> {
  await playMonitor()
  recorder.resume()
  armStopTimer()
  await startLivePitch()
}

function stopRecording(): void {
  stopMonitor()
  livePitch.stop()
  recorder.stop()
}

function analyze(): void {
  if (recorder.recordedFile.value) emit("submit", recorder.recordedFile.value, isolate.value)
}

function requestClose(): void {
  // Closing mid-take would otherwise discard the recording silently. A paused
  // take is still a take, so it has to be caught here too.
  if (inTake.value) {
    stopRecording()
    return
  }
  emit("close")
}

function onKeydown(event: KeyboardEvent): void {
  if (event.key === "Escape") requestClose()
}

watch(recorder.recordedFile, (file) => {
  if (recordedUrl.value) window.URL.revokeObjectURL(recordedUrl.value)
  recordedUrl.value = file ? window.URL.createObjectURL(file) : ""
})
watch(voiceLevel, (value) => {
  if (vocalAudio.value) vocalAudio.value.volume = value / 100
})
onMounted(() => {
  void loadContour()
  try {
    const stored = Number(window.localStorage.getItem(FONT_STORAGE_KEY))
    if (Number.isFinite(stored) && stored >= 0 && stored < FONT_STEPS.length) fontStep.value = stored
  } catch {
    // Keep the default size.
  }
  window.addEventListener("keydown", onKeydown)
  document.body.classList.add("modal-open")
  scrollFrame = window.requestAnimationFrame(scrollLoop)
})
watch(() => [props.project.id, props.project.transpose_semitones], loadContour)
onBeforeUnmount(() => {
  stopMonitor()
  livePitch.stop()
  if (recordedUrl.value) window.URL.revokeObjectURL(recordedUrl.value)
  window.removeEventListener("keydown", onKeydown)
  document.body.classList.remove("modal-open")
  if (scrollFrame !== undefined) window.cancelAnimationFrame(scrollFrame)
})
watch(() => props.project.lyrics, (value) => { lyrics.value = value })
</script>

<template>
  <div class="recording-overlay" @click.self="requestClose">
    <section class="recording-modal" :class="{ recording: inTake }" role="dialog" aria-modal="true">
      <header class="recording-modal-header">
        <div>
          <p class="mono-eyebrow accent-text">RECORD A TAKE</p>
          <h3>{{ project.title }}</h3>
        </div>
        <div class="recording-modal-tools">
          <button
            type="button"
            class="tool-button"
            :disabled="inTake"
            @click="editingLyrics = !editingLyrics"
          >{{ editingLyrics ? "DONE" : "EDIT LYRICS" }}</button>
          <button
            type="button"
            class="tool-button"
            :class="{ armed: autoScroll }"
            :title="scrollProgress.usesVoicedTime
              ? 'Follows the reference vocal, so the page waits through instrumental sections'
              : 'No reference contour, so the page follows elapsed time'"
            @click="autoScroll = !autoScroll"
          >FOLLOW {{ autoScroll ? "ON" : "OFF" }}</button>
          <button type="button" class="tool-button" @click="setFontStep(fontStep - 1)">A−</button>
          <button type="button" class="tool-button" @click="setFontStep(fontStep + 1)">A+</button>
          <button type="button" class="tool-button close" @click="requestClose">✕</button>
        </div>
      </header>

      <div class="recording-modal-body">
        <div class="lyrics-stage">
          <textarea
            v-if="editingLyrics"
            v-model="lyrics"
            class="lyrics-editor"
            placeholder="Paste the song lyrics here…"
            @blur="emit('updateLyrics', lyrics)"
          ></textarea>
          <div
            v-else-if="lyrics.trim()"
            ref="lyricsView"
            class="lyrics-read"
            :style="{ fontSize: lyricsFontSize }"
            @wheel="noteManualScroll"
            @touchmove="noteManualScroll"
          >{{ lyrics }}</div>
          <p v-else class="lyrics-empty">
            No lyrics yet. Choose <b>EDIT LYRICS</b> to paste them in — they stay
            with this project.
          </p>
        </div>

        <aside class="recording-controls">
          <PitchRibbon
            :contour="contour"
            :samples="livePitch.samples.value"
            :current="livePitch.current.value"
            :time="monitorTime"
            :active="inTake"
          />
          <p class="live-cents" :class="{ live: recording }">
            <span v-if="liveCents === null">&mdash;</span>
            <span v-else>{{ liveCents > 0 ? "+" : "" }}{{ liveCents }}<small>cents</small></span>
          </p>

          <div class="record-readout" :class="{ live: recording, held: paused }">
            <i></i><span>{{ recording ? "RECORDING" : paused ? "PAUSED" : "MIC READY" }}</span><strong>{{ timecode }}</strong>
          </div>
          <p v-if="recorder.error.value" class="inline-error">{{ recorder.error.value }}</p>

          <button
            v-if="!inTake && !recorder.recordedFile.value"
            class="record-button"
            :disabled="!recorder.supported.value"
            @click="startRecording"
          >● START RECORDING</button>
          <div v-else-if="inTake" class="take-transport">
            <button v-if="recording" class="hold-button" @click="pauseRecording">❚❚ PAUSE</button>
            <button v-else class="hold-button resume" @click="resumeRecording">▶ RESUME</button>
            <button class="record-button live" @click="stopRecording">■ STOP</button>
          </div>

          <template v-if="recorder.recordedFile.value">
            <audio class="recorded-preview" controls :src="recordedUrl"></audio>
            <label class="check-row"><input v-model="isolate" type="checkbox" /> Isolate my vocal first</label>
            <button class="accent-button full" :disabled="busy" @click="analyze">
              {{ busy ? "ANALYZING…" : "SAVE & ANALYZE TAKE →" }}
            </button>
            <button class="text-button" @click="recorder.discard">DISCARD & RECORD AGAIN</button>
          </template>

          <label class="monitor-slider">
            <span>REFERENCE VOICE <b>{{ voiceLevel }}%</b></span>
            <input v-model.number="voiceLevel" type="range" min="0" max="100" />
            <small>Adjust live · 0% is karaoke · instrumental stays at full level</small>
          </label>
          <p class="feature-note">Use headphones. The monitor mix is not embedded in the saved take.</p>
        </aside>
      </div>

      <audio ref="vocalAudio" preload="auto" :src="`/api/projects/${project.id}/audio/vocal?transpose=${project.transpose_semitones}`"></audio>
      <audio
        v-if="project.reference.instrumental_path"
        ref="instrumentalAudio"
        preload="auto"
        :src="`/api/projects/${project.id}/audio/instrumental?transpose=${project.transpose_semitones}`"
      ></audio>
    </section>
  </div>
</template>

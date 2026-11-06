<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, toRef, watch } from "vue"

import { apiJson } from "../../shared/api"
import type { Project } from "../../shared/types"
import PitchRibbon from "./PitchRibbon.vue"
import type { ReferenceContour } from "./pitchRibbon"
import { referenceMidiAt } from "./pitchRibbon"
import { createScrollProgress, easeToward } from "./lyricsScroll"
import TimedLyrics from "../reference/TimedLyrics.vue"
import { useLyricsTiming } from "../reference/useLyricsTiming"
import { useLivePitch } from "./useLivePitch"
import { audioDevices, latencyForPair } from "../../shared/audioDevices"
import { useStudioRecorder } from "./useStudioRecorder"

const props = defineProps<{ project: Project; busy: boolean }>()
const emit = defineEmits<{
  submit: [file: File, isolate: boolean, recordingOffset: number]
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
const recorder = useStudioRecorder()
const livePitch = useLivePitch()
const recordedUrl = ref("")

const contour = ref<ReferenceContour | null>(null)
const monitorTime = ref(0)
const lyricsView = ref<HTMLElement | null>(null)
const autoScroll = ref(true)
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

const {
  lines: timedLines,
  activeLine,
  activeWord,
  lineScrollTarget,
} = useLyricsTiming(toRef(props, "project"), lyrics, monitorTime)

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
  // The live-pitch callback only ticks while there is input to analyse; the
  // highlight has to move every frame the backing track does.
  if (recording.value) monitorTime.value = recorder.position()
  if (element && autoScroll.value && inTake.value && timestamp >= suspendScrollUntil) {
    const range = element.scrollHeight - element.clientHeight
    const wanted = timedLines.value
      ? lineScrollTarget(element)
      : scrollProgress.value.at(monitorTime.value) * range
    if (range > 4 && wanted !== null) {
      const target = Math.max(0, Math.min(range, wanted))
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

function referenceEnd(): number {
  return props.project.trim_end_seconds ?? props.project.reference.duration_seconds
}

/** The stems, in the key the singer has chosen, decoded for the studio's clock. */
function loadBackingTrack(): void {
  const { id, updated_at: version, transpose_semitones: transpose, reference } = props.project
  const url = (kind: string) => `/api/projects/${id}/audio/${kind}?v=${version}&transpose=${transpose}`
  void recorder.load({
    vocal: reference.vocal_path ? url("vocal") : undefined,
    instrumental: reference.instrumental_path ? url("instrumental") : undefined,
  })
}

/** Half the live pitch analysis window: a detected pitch describes its middle. */
const LIVE_ANALYSIS_DELAY = 1024 / 44_100

/**
 * How far behind the rendered position the voice being analysed now was sung:
 * the round trip (heard late, captured late) plus the analysis window.
 */
const liveDelay = computed(() => (recorder.latency.value ?? 0) + LIVE_ANALYSIS_DELAY)

// The ribbon reads the studio's audio clock, shifted back by liveDelay so
// the singer's marker lines up with the note they were hearing as they sang
// it. It holds still while a take is paused.
async function startLivePitch(): Promise<void> {
  const stream = recorder.stream.value
  if (!stream) return
  await livePitch.start(stream, () => {
    monitorTime.value = recorder.position()
    return monitorTime.value - liveDelay.value
  })
}

/** What the studio knows about this setup's round trip, for the mic line. */
const latencyLabel = computed(() => {
  const measured = recorder.latency.value ?? latencyForPair()?.seconds ?? null
  return measured === null ? "latency not measured" : `latency ${Math.round(measured * 1000)} ms`
})

async function startRecording(): Promise<void> {
  // Reading and editing are different modes; nobody wants a textarea in front
  // of them while singing.
  editingLyrics.value = false
  livePitch.reset()
  if (lyricsView.value) lyricsView.value.scrollTop = 0
  easedScrollTop = Number.NaN
  suspendScrollUntil = 0
  const voice = props.project.reference.vocal_path ? voiceLevel.value / 100 : 0
  await recorder.start(props.project.trim_start_seconds, referenceEnd(), voice)
  if (recorder.state.value === "recording") await startLivePitch()
}

function pauseRecording(): void {
  recorder.pause()
  livePitch.stop()
}

async function resumeRecording(): Promise<void> {
  recorder.resume()
  if (recorder.state.value === "recording") await startLivePitch()
}

function stopRecording(): void {
  livePitch.stop()
  void recorder.stop()
}

function analyze(): void {
  if (recorder.recordedFile.value && recorder.offset.value !== null) {
    emit("submit", recorder.recordedFile.value, isolate.value, recorder.offset.value)
  }
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
watch(voiceLevel, (value) => recorder.setVoiceLevel(value / 100))
// A take finishing on its own (the song ended) stops the live display too.
watch(recorder.state, (state) => {
  if (state !== "recording") livePitch.stop()
})
onMounted(() => {
  void loadContour()
  loadBackingTrack()
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
watch(() => [props.project.id, props.project.transpose_semitones, props.project.reference_voice], loadContour)
watch(() => [props.project.id, props.project.transpose_semitones], () => {
  if (!inTake.value) loadBackingTrack()
})
onBeforeUnmount(() => {
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
            :title="timedLines
              ? 'Follows the lyric timings measured on the reference vocal'
              : scrollProgress.usesVoicedTime
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
            v-else-if="timedLines"
            ref="lyricsView"
            class="lyrics-read lyrics-timed"
            :style="{ fontSize: lyricsFontSize }"
            @wheel="noteManualScroll"
            @touchmove="noteManualScroll"
          >
            <TimedLyrics :lines="timedLines" :active-line="activeLine" :active-word="activeWord" />
          </div>
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
            :time="inTake ? monitorTime - liveDelay : monitorTime"
            :active="inTake"
          />
          <p class="live-cents" :class="{ live: recording }">
            <span v-if="liveCents === null">&mdash;</span>
            <span v-else>{{ liveCents > 0 ? "+" : "" }}{{ liveCents }}<small>cents</small></span>
          </p>

          <div class="record-readout" :class="{ live: recording, held: paused }">
            <i></i><span>{{ recording ? "RECORDING" : paused ? "PAUSED" : recorder.state.value === "loading" ? "LOADING SONG" : "MIC READY" }}</span><strong>{{ timecode }}</strong>
          </div>
          <p v-if="recorder.error.value" class="inline-error">{{ recorder.error.value }}</p>

          <button
            v-if="!inTake && !recorder.recordedFile.value"
            class="record-button"
            :disabled="!recorder.supported.value || recorder.state.value === 'requesting' || recorder.state.value === 'loading'"
            @click="startRecording"
          >● START RECORDING</button>
          <div v-else-if="inTake" class="take-transport">
            <button v-if="recording" class="hold-button" @click="pauseRecording">❚❚ PAUSE</button>
            <button v-else class="hold-button resume" @click="resumeRecording">▶ RESUME</button>
            <button class="record-button live" :disabled="recorder.state.value === 'requesting'" @click="stopRecording">■ STOP</button>
          </div>

          <template v-if="recorder.recordedFile.value && !inTake">
            <audio v-audio-output class="recorded-preview" controls :src="recordedUrl"></audio>
            <label v-if="project.reference.vocal_path" class="check-row"><input v-model="isolate" type="checkbox" /> Isolate my vocal first</label>
            <button class="accent-button full" :disabled="busy || recorder.offset.value === null" @click="analyze">
              {{ busy ? "SAVING…" : project.reference.vocal_path ? "SAVE & ANALYZE TAKE →" : "SAVE TAKE →" }}
            </button>
            <button class="text-button" @click="recorder.discard">DISCARD & RECORD AGAIN</button>
          </template>

          <label v-if="project.reference.vocal_path" class="monitor-slider">
            <span>REFERENCE VOICE <b>{{ voiceLevel }}%</b></span>
            <input v-model.number="voiceLevel" type="range" min="0" max="100" />
            <small>Adjust live · 0% is karaoke · instrumental stays at full level</small>
          </label>
          <p v-if="audioDevices.notice" class="inline-error mic-in-use">{{ audioDevices.notice }}</p>
          <p v-else-if="audioDevices.inputInUse" class="feature-note mic-in-use">Mic: {{ audioDevices.inputInUse }} · {{ latencyLabel }}</p>
          <p v-if="audioDevices.outputNotice" class="inline-error">{{ audioDevices.outputNotice }}</p>
          <p class="feature-note">Use headphones. The monitor mix is not embedded in the saved take.</p>
        </aside>
      </div>

    </section>
  </div>
</template>

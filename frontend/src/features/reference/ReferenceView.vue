<script setup lang="ts">
import { computed, onBeforeUnmount, ref, toRef, watch } from "vue"

import { apiJson } from "../../shared/api"
import { transposedRange, type VocalRange } from "../../shared/notes"
import { createScrollProgress, easeToward, type ProgressContour } from "../recording/lyricsScroll"
import { jumpTime } from "./lyricsTiming"
import TimedLyrics from "./TimedLyrics.vue"
import { useLyricsTiming } from "./useLyricsTiming"
import { seekTimeAt } from "./seek"
import type { Project, WaveformEnvelope } from "../../shared/types"

const props = defineProps<{ project: Project }>()
const emit = defineEmits<{
  update: [settings: Partial<Pick<Project, "trim_start_seconds" | "trim_end_seconds" | "transpose_semitones" | "lyrics">>]
}>()

const stem = ref<"vocal" | "instrumental" | "mix">("vocal")
const vocalLevel = ref(70)
const trimStart = ref(props.project.trim_start_seconds)
const trimEnd = ref(props.project.trim_end_seconds ?? props.project.reference.duration_seconds)
const transpose = ref(props.project.transpose_semitones)
const playbackState = ref<"stopped" | "playing" | "paused">("stopped")
const playing = computed(() => playbackState.value === "playing")
const paused = computed(() => playbackState.value === "paused")
const playhead = ref(trimStart.value)
const amplitudes = ref<number[]>([])
const vocalAudio = ref<HTMLAudioElement | null>(null)
const instrumentalAudio = ref<HTMLAudioElement | null>(null)
let animationFrame: number | undefined
let scrubbing = false

const referenceRange = ref<VocalRange | null>(null)
const contour = ref<ProgressContour | null>(null)
// Transposition shifts every pitch equally, so the displayed range follows the
// buttons instantly instead of waiting on a re-measure per semitone.
const sungRange = computed(() => transposedRange(referenceRange.value, transpose.value))

async function loadRange(): Promise<void> {
  try {
    const payload = await apiJson<ProgressContour & { range: VocalRange | null }>(
      `/api/projects/${props.project.id}/reference/pitch`,
    )
    referenceRange.value = payload.range
    contour.value = payload
  } catch {
    referenceRange.value = null
    contour.value = null
  }
}
void loadRange()

const lyrics = ref(props.project.lyrics)
const editingLyrics = ref(false)
const lyricsView = ref<HTMLElement | null>(null)
let lastFrameAt = 0
let suspendFollowUntil = 0
let easedScrollTop = Number.NaN

// Voiced frames do not move with transposition, so the untransposed contour
// paces the lyric just as well as the key being played.
const scrollProgress = computed(() => createScrollProgress(contour.value, trimStart.value, trimEnd.value))

const {
  lines: timedLines,
  activeLine,
  activeWord,
  label: timingLabel,
  lineScrollTarget,
} = useLyricsTiming(toRef(props, "project"), lyrics, playhead)

/** Play from a clicked line or word, whatever the transport was doing. */
async function playFrom(start: number | null): Promise<void> {
  if (start === null) return
  suspendFollowUntil = 0
  easedScrollTop = Number.NaN
  const time = jumpTime(start)
  if (playing.value) {
    seekTo(time)
    return
  }
  await startAudio(time)
}

/** Where to scroll so the sung line sits a third of the way down the panel. */
function followTarget(element: HTMLElement): number | null {
  if (timedLines.value) return lineScrollTarget(element)
  return scrollProgress.value.at(playhead.value) * (element.scrollHeight - element.clientHeight)
}

/**
 * Keep the sung line in view while the reference plays.
 *
 * With word timings the panel follows the actual line; without them it falls
 * back to the studio's voiced-time estimate.
 */
function followLyrics(timestamp: number): void {
  const delta = lastFrameAt ? Math.min(100, timestamp - lastFrameAt) : 16
  lastFrameAt = timestamp
  const element = lyricsView.value
  if (!element || timestamp < suspendFollowUntil) return
  const range = element.scrollHeight - element.clientHeight
  if (range <= 4) return
  const wanted = followTarget(element)
  if (wanted === null) return
  const target = Math.max(0, Math.min(range, wanted))
  const from = Number.isFinite(easedScrollTop) ? easedScrollTop : element.scrollTop
  easedScrollTop = easeToward(from, target, delta)
  element.scrollTop = easedScrollTop
}

/** Reading ahead should not mean fighting the page back. */
function noteManualScroll(): void {
  suspendFollowUntil = performance.now() + 4000
  easedScrollTop = Number.NaN
}

function finishEditingLyrics(): void {
  editingLyrics.value = false
  if (lyrics.value !== props.project.lyrics) emit("update", { lyrics: lyrics.value })
}

interface LyricsCandidate {
  id: number
  track: string
  artist: string
  album: string | null
  duration_seconds: number | null
  lyrics: string
}

const candidates = ref<LyricsCandidate[] | null>(null)
const searching = ref(false)
const searchError = ref("")

async function findLyrics(): Promise<void> {
  searching.value = true
  searchError.value = ""
  try {
    const payload = await apiJson<{ candidates: LyricsCandidate[] }>(
      `/api/projects/${props.project.id}/lyrics/search`,
    )
    candidates.value = payload.candidates
    if (!payload.candidates.length) searchError.value = "LRCLIB has no lyrics for this title."
  } catch (error) {
    candidates.value = null
    searchError.value = error instanceof Error ? error.message : "Lyrics search failed."
  } finally {
    searching.value = false
  }
}

function useCandidate(candidate: LyricsCandidate): void {
  if (
    props.project.lyrics.trim()
    && !window.confirm("Replace this project's lyrics with the ones from LRCLIB?")
  ) return
  lyrics.value = candidate.lyrics
  candidates.value = null
  editingLyrics.value = false
  emit("update", { lyrics: candidate.lyrics })
}

const duration = computed(() => props.project.reference.duration_seconds)
const selectionDuration = computed(() => Math.max(0, trimEnd.value - trimStart.value))
const stemTitle = computed(() => ({
  vocal: "Isolated vocal",
  instrumental: "Reference instrumental",
  mix: "Practice monitor mix",
})[stem.value])

function formatTime(seconds: number): string {
  const minutes = Math.floor(seconds / 60)
  const remainder = Math.max(0, seconds - minutes * 60)
  return `${minutes}:${String(Math.floor(remainder)).padStart(2, "0")}`
}

async function loadWaveform(): Promise<void> {
  const kind = stem.value === "mix" ? "mix" : stem.value
  try {
    const payload = await apiJson<WaveformEnvelope>(
      `/api/projects/${props.project.id}/waveform/${kind}`,
    )
    amplitudes.value = payload.amplitude
  } catch {
    amplitudes.value = []
  }
}

function configureVolumes(): void {
  if (vocalAudio.value) {
    vocalAudio.value.volume = stem.value === "vocal" ? 1 : stem.value === "mix" ? vocalLevel.value / 100 : 0
  }
  if (instrumentalAudio.value) {
    instrumentalAudio.value.volume = stem.value === "vocal" ? 0 : 1
  }
}

function holdTransport(): void {
  vocalAudio.value?.pause()
  instrumentalAudio.value?.pause()
  if (animationFrame !== undefined) cancelAnimationFrame(animationFrame)
  animationFrame = undefined
  lastFrameAt = 0
  easedScrollTop = Number.NaN
}

/** Hold position so playback can pick up where it left off. */
function pausePlayback(): void {
  if (!playing.value) return
  holdTransport()
  playbackState.value = "paused"
}

/** Full stop: the playhead returns to the start of the trimmed range. */
function stop(): void {
  holdTransport()
  playbackState.value = "stopped"
  playhead.value = trimStart.value
}

function updatePlayhead(): void {
  const active = stem.value === "instrumental" ? instrumentalAudio.value : vocalAudio.value
  playhead.value = active?.currentTime ?? trimStart.value
  if (playhead.value >= trimEnd.value) {
    stop()
    return
  }
  followLyrics(performance.now())
  animationFrame = requestAnimationFrame(updatePlayhead)
}

async function startAudio(from: number): Promise<void> {
  configureVolumes()
  for (const audio of [vocalAudio.value, instrumentalAudio.value]) {
    if (audio) audio.currentTime = from
  }
  const promises: Promise<void>[] = []
  if (stem.value !== "instrumental" && vocalAudio.value) promises.push(vocalAudio.value.play())
  if (stem.value !== "vocal" && instrumentalAudio.value) promises.push(instrumentalAudio.value.play())
  await Promise.all(promises)
  playbackState.value = "playing"
  updatePlayhead()
}

/**
 * Move playback to a position on the waveform.
 *
 * Seeking while stopped leaves the transport in the paused state rather than
 * stopped, so the next press resumes from the chosen point instead of
 * rewinding to the trim start.
 */
function seekTo(time: number): void {
  playhead.value = time
  for (const audio of [vocalAudio.value, instrumentalAudio.value]) {
    if (audio) audio.currentTime = time
  }
  if (playbackState.value === "stopped") playbackState.value = "paused"
}

function seekFromPointer(event: PointerEvent): void {
  const element = event.currentTarget as HTMLElement
  const box = element.getBoundingClientRect()
  seekTo(seekTimeAt(event.clientX, box, duration.value, trimStart.value, trimEnd.value))
}

function beginScrub(event: PointerEvent): void {
  const element = event.currentTarget as HTMLElement
  // Capture so a drag that leaves the waveform keeps scrubbing instead of
  // stopping wherever the pointer happened to cross the edge.
  element.setPointerCapture(event.pointerId)
  scrubbing = true
  seekFromPointer(event)
}

function continueScrub(event: PointerEvent): void {
  if (scrubbing) seekFromPointer(event)
}

function endScrub(event: PointerEvent): void {
  if (!scrubbing) return
  scrubbing = false
  const element = event.currentTarget as HTMLElement
  if (element.hasPointerCapture(event.pointerId)) element.releasePointerCapture(event.pointerId)
}

async function play(): Promise<void> {
  if (playing.value) {
    pausePlayback()
    return
  }
  // Resuming keeps the playhead; the trim range may have been dragged past it
  // in the meantime, so a position outside the range restarts instead.
  const inRange = playhead.value > trimStart.value && playhead.value < trimEnd.value
  await startAudio(paused.value && inRange ? playhead.value : trimStart.value)
}

function clampTrim(changed: "start" | "end"): void {
  const gap = Math.min(0.5, duration.value)
  if (changed === "start") trimStart.value = Math.min(trimStart.value, trimEnd.value - gap)
  else trimEnd.value = Math.max(trimEnd.value, trimStart.value + gap)
  emit("update", {
    trim_start_seconds: trimStart.value,
    trim_end_seconds: trimEnd.value,
  })
}

function saveTranspose(): void {
  stop()
  emit("update", { transpose_semitones: transpose.value })
}

watch(stem, () => {
  stop()
  void loadWaveform()
})
watch(vocalLevel, configureVolumes)
watch(() => props.project, (project) => {
  trimStart.value = project.trim_start_seconds
  trimEnd.value = project.trim_end_seconds ?? project.reference.duration_seconds
  transpose.value = project.transpose_semitones
  if (!editingLyrics.value) lyrics.value = project.lyrics
})

void loadWaveform()
onBeforeUnmount(stop)
</script>

<template>
  <div class="reference-layout">
    <section class="feature-panel reference-main">
      <div class="feature-heading">
        <div><p class="mono-eyebrow accent-text">STEM VIEW</p><h2>{{ stemTitle }}</h2></div>
        <div class="segmented graphite-segmented">
          <button :class="{ active: stem === 'vocal' }" @click="stem = 'vocal'">VOCAL</button>
          <button
            :disabled="!project.reference.instrumental_path"
            :class="{ active: stem === 'instrumental' }"
            @click="stem = 'instrumental'"
          >INSTRUMENTAL</button>
          <button
            :disabled="!project.reference.instrumental_path"
            :class="{ active: stem === 'mix' }"
            @click="stem = 'mix'"
          >MIX</button>
        </div>
      </div>

      <div class="waveform-screen">
        <div class="time-ruler"><span>0:00</span><span>{{ formatTime(duration / 2) }}</span><span>{{ formatTime(duration) }}</span></div>
        <div
          class="reference-waveform seekable"
          @pointerdown="beginScrub"
          @pointermove="continueScrub"
          @pointerup="endScrub"
          @pointercancel="endScrub"
        >
          <i
            v-for="(amplitude, index) in amplitudes"
            :key="index"
            :class="{ selected: (index / amplitudes.length) * duration >= trimStart && (index / amplitudes.length) * duration <= trimEnd }"
            :style="{ height: `${Math.max(3, amplitude * 100)}%` }"
          ></i>
          <b :style="{ left: `${(playhead / duration) * 100}%` }"></b>
        </div>
        <div class="trim-meta"><span>TRIM {{ formatTime(trimStart) }} → {{ formatTime(trimEnd) }}</span><span>SELECTION {{ formatTime(selectionDuration) }}</span></div>
        <label class="range-label">IN <input v-model.number="trimStart" type="range" min="0" :max="duration" step="0.1" @change="clampTrim('start')" /></label>
        <label class="range-label">OUT <input v-model.number="trimEnd" type="range" min="0" :max="duration" step="0.1" @change="clampTrim('end')" /></label>
      </div>

      <div v-if="stem === 'mix'" class="monitor-level">
        <label>REFERENCE VOICE <strong>{{ vocalLevel }}%</strong></label>
        <input v-model.number="vocalLevel" type="range" min="0" max="100" />
        <small>Set to 0% for an instrumental-only karaoke monitor.</small>
      </div>

      <div class="reference-transport">
        <button class="solid-button compact" @click="play">
          {{ playing ? "❚❚ PAUSE" : paused ? "▶ RESUME" : "▶ PLAY" }}
        </button>
        <button v-if="playing || paused" class="ghost-button compact" @click="stop">■ STOP</button>
        <span>{{ formatTime(playhead) }} / {{ formatTime(duration) }}</span>
      </div>
      <audio ref="vocalAudio" preload="metadata" :src="`/api/projects/${project.id}/audio/vocal?v=${project.updated_at}&transpose=${transpose}`"></audio>
      <audio
        v-if="project.reference.instrumental_path"
        ref="instrumentalAudio"
        preload="metadata"
        :src="`/api/projects/${project.id}/audio/instrumental?v=${project.updated_at}&transpose=${transpose}`"
      ></audio>
    </section>

    <section class="feature-panel reference-lyrics">
      <div class="feature-heading">
        <div>
          <p class="mono-eyebrow accent-text">LYRICS <span v-if="timingLabel" class="lyrics-timing-state">· {{ timingLabel }}</span></p>
          <h2>Sing along</h2>
        </div>
        <div class="lyrics-tools">
          <button
            type="button"
            class="tool-button"
            :disabled="searching || editingLyrics"
            @click="findLyrics"
          >{{ searching ? "SEARCHING…" : "FIND LYRICS" }}</button>
          <button
            type="button"
            class="tool-button"
            @click="editingLyrics ? finishEditingLyrics() : (editingLyrics = true)"
          >{{ editingLyrics ? "DONE" : "EDIT LYRICS" }}</button>
        </div>
      </div>

      <div v-if="candidates?.length" class="lyrics-candidates">
        <div class="lyrics-candidates-heading">
          <span>FROM LRCLIB</span>
          <button type="button" class="tool-button" @click="candidates = null">CANCEL</button>
        </div>
        <button
          v-for="candidate in candidates"
          :key="candidate.id"
          type="button"
          class="lyrics-candidate"
          @click="useCandidate(candidate)"
        >
          <strong>{{ candidate.track }}</strong>
          <span>{{ candidate.artist }}<template v-if="candidate.album"> · {{ candidate.album }}</template></span>
          <small>
            <template v-if="candidate.duration_seconds">{{ formatTime(candidate.duration_seconds) }} · </template>{{ candidate.lyrics.split("\n")[0] }}…
          </small>
        </button>
      </div>
      <p v-else-if="searchError" class="feature-note lyrics-search-error">{{ searchError }}</p>

      <textarea
        v-if="editingLyrics"
        v-model="lyrics"
        class="lyrics-editor"
        placeholder="Paste the song lyrics here…"
        @blur="finishEditingLyrics"
      ></textarea>
      <div
        v-else-if="timedLines"
        ref="lyricsView"
        class="lyrics-read lyrics-timed"
        @wheel="noteManualScroll"
        @touchmove="noteManualScroll"
      >
        <TimedLyrics
          :lines="timedLines"
          :active-line="activeLine"
          :active-word="activeWord"
          interactive
          @play="playFrom"
        />
      </div>
      <div
        v-else-if="lyrics.trim()"
        ref="lyricsView"
        class="lyrics-read"
        @wheel="noteManualScroll"
        @touchmove="noteManualScroll"
      >{{ lyrics }}</div>
      <p v-else class="lyrics-empty">
        No lyrics yet. <b>FIND LYRICS</b> looks them up on LRCLIB, or <b>EDIT LYRICS</b>
        to paste them in. Once saved they are timed to the reference vocal, and
        any line or word plays the song from there.
      </p>
    </section>

    <aside class="feature-sidebar">
      <section class="feature-panel compact-panel">
        <p class="mono-eyebrow accent-text">TRANSPOSE</p>
        <div class="transpose-value">{{ transpose >= 0 ? "+" : "" }}{{ transpose }} <small>SEMI</small></div>
        <div class="transpose-grid">
          <button
            v-for="step in [-5,-4,-3,-2,-1,0,1,2,3,4]"
            :key="step"
            :class="{ active: transpose === step }"
            @click="transpose = step; saveTranspose()"
          >{{ step > 0 ? `+${step}` : step }}</button>
        </div>
        <div v-if="sungRange" class="range-readout">
          <span>RANGE TO SING</span>
          <strong>{{ sungRange.low_note }} – {{ sungRange.high_note }}</strong>
          <small>{{ sungRange.semitones.toFixed(0) }} semitones · centred on {{ sungRange.median_note }}</small>
        </div>
        <p class="feature-note">Applied to preview and recording playback. New takes remember this key for analysis and export.</p>
      </section>
      <section class="feature-panel compact-panel status-card">
        <p class="mono-eyebrow accent-text">SEPARATION</p>
        <div><span>Vocal stem</span><b>READY</b></div>
        <div><span>Instrumental stem</span><b>{{ project.reference.instrumental_path ? "READY" : "N/A" }}</b></div>
        <p>Prepared stems are reused by every take and by future exports.</p>
      </section>
    </aside>
  </div>
</template>

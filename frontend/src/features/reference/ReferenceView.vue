<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue"

import { apiJson } from "../../shared/api"
import { seekTimeAt } from "./seek"
import type { Project, WaveformEnvelope } from "../../shared/types"

const props = defineProps<{ project: Project }>()
const emit = defineEmits<{
  update: [settings: Partial<Pick<Project, "trim_start_seconds" | "trim_end_seconds" | "transpose_semitones">>]
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

    <aside class="feature-sidebar">
      <section class="feature-panel compact-panel">
        <p class="mono-eyebrow accent-text">TRANSPOSE</p>
        <div class="transpose-value">{{ transpose >= 0 ? "+" : "" }}{{ transpose }} <small>SEMI</small></div>
        <div class="transpose-grid">
          <button
            v-for="step in [-4,-3,-2,-1,0,1,2,3,4]"
            :key="step"
            :class="{ active: transpose === step }"
            @click="transpose = step; saveTranspose()"
          >{{ step > 0 ? `+${step}` : step }}</button>
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

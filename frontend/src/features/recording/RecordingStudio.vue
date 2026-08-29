<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue"

import { apiJson } from "../../shared/api"
import type { Project } from "../../shared/types"
import PitchRibbon from "./PitchRibbon.vue"
import type { ReferenceContour } from "./pitchRibbon"
import { referenceMidiAt } from "./pitchRibbon"
import { useLivePitch } from "./useLivePitch"
import { useMicrophoneRecorder } from "./useMicrophoneRecorder"

const props = defineProps<{ project: Project; busy: boolean }>()
const emit = defineEmits<{
  submit: [file: File, isolate: boolean]
  updateLyrics: [lyrics: string]
}>()

const isolate = ref(false)
const voiceLevel = ref(35)
const lyrics = ref(props.project.lyrics)
const vocalAudio = ref<HTMLAudioElement | null>(null)
const instrumentalAudio = ref<HTMLAudioElement | null>(null)
const recorder = useMicrophoneRecorder()
const livePitch = useLivePitch()
const recordedUrl = ref("")
const contour = ref<ReferenceContour | null>(null)
const monitorTime = ref(0)
let stopTimer: number | undefined

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

async function startRecording(): Promise<void> {
  livePitch.reset()
  await recorder.start()
  if (recorder.state.value !== "recording") return
  const start = props.project.trim_start_seconds
  const end = props.project.trim_end_seconds ?? props.project.reference.duration_seconds
  if (vocalAudio.value) {
    vocalAudio.value.currentTime = start
    vocalAudio.value.volume = voiceLevel.value / 100
  }
  if (instrumentalAudio.value) {
    instrumentalAudio.value.currentTime = start
    instrumentalAudio.value.volume = 1
  }
  await Promise.all([
    vocalAudio.value?.play(),
    instrumentalAudio.value?.play(),
  ].filter((promise): promise is Promise<void> => promise !== undefined))
  stopTimer = window.setTimeout(stopRecording, Math.max(0.1, end - start) * 1000)

  // Time comes from the monitor element, not the wall clock: the ribbon has
  // to stay locked to the backing track the singer is actually hearing.
  const clockSource = vocalAudio.value ?? instrumentalAudio.value
  const stream = recorder.stream.value
  if (stream) {
    await livePitch.start(stream, () => {
      monitorTime.value = clockSource?.currentTime ?? 0
      return monitorTime.value
    })
  }
}

function stopRecording(): void {
  stopMonitor()
  livePitch.stop()
  recorder.stop()
}

function analyze(): void {
  if (recorder.recordedFile.value) emit("submit", recorder.recordedFile.value, isolate.value)
}

watch(recorder.recordedFile, (file) => {
  if (recordedUrl.value) window.URL.revokeObjectURL(recordedUrl.value)
  recordedUrl.value = file ? window.URL.createObjectURL(file) : ""
})
watch(voiceLevel, (value) => {
  if (vocalAudio.value) vocalAudio.value.volume = value / 100
})
onMounted(loadContour)
watch(() => [props.project.id, props.project.transpose_semitones], loadContour)
onBeforeUnmount(() => {
  stopMonitor()
  livePitch.stop()
  if (recordedUrl.value) window.URL.revokeObjectURL(recordedUrl.value)
})
watch(() => props.project.lyrics, (value) => { lyrics.value = value })
</script>

<template>
  <section class="recording-studio">
    <p class="mono-eyebrow accent-text">RECORD A TAKE</p>
    <h3>Sing with the reference</h3>
    <p class="feature-note">Use headphones. The monitor mix is not embedded in the saved microphone take.</p>

    <label class="lyrics-field">
      <span>LYRICS / NOTES</span>
      <textarea
        v-model="lyrics"
        placeholder="Paste the song lyrics here…"
        @blur="emit('updateLyrics', lyrics)"
      ></textarea>
      <small>Saved with this project. Synchronization can be added later.</small>
    </label>

    <label class="monitor-slider">
      <span>REFERENCE VOICE <b>{{ voiceLevel }}%</b></span>
      <input v-model.number="voiceLevel" type="range" min="0" max="100" />
      <small>Adjust live while recording · 0% is karaoke · instrumental remains at full level</small>
    </label>

    <PitchRibbon
      :contour="contour"
      :samples="livePitch.samples.value"
      :current="livePitch.current.value"
      :time="monitorTime"
      :active="recorder.state.value === 'recording'"
    />
    <p class="live-cents" :class="{ live: recorder.state.value === 'recording' }">
      <span v-if="liveCents === null">&mdash;</span>
      <span v-else>{{ liveCents > 0 ? "+" : "" }}{{ liveCents }}<small>cents</small></span>
    </p>

    <div class="record-readout" :class="{ live: recorder.state.value === 'recording' }">
      <i></i><span>{{ recorder.state.value === "recording" ? "RECORDING" : "MIC READY" }}</span><strong>{{ timecode }}</strong>
    </div>
    <p v-if="recorder.error.value" class="inline-error">{{ recorder.error.value }}</p>

    <button
      v-if="recorder.state.value !== 'recording' && !recorder.recordedFile.value"
      class="record-button"
      :disabled="!recorder.supported.value"
      @click="startRecording"
    >● START RECORDING</button>
    <button v-else-if="recorder.state.value === 'recording'" class="record-button live" @click="stopRecording">■ STOP</button>

    <template v-if="recorder.recordedFile.value">
      <audio class="recorded-preview" controls :src="recordedUrl"></audio>
      <label class="check-row"><input v-model="isolate" type="checkbox" /> Isolate my vocal first</label>
      <button class="accent-button full" :disabled="busy" @click="analyze">
        {{ busy ? "ANALYZING…" : "SAVE & ANALYZE TAKE →" }}
      </button>
      <button class="text-button" @click="recorder.discard">DISCARD & RECORD AGAIN</button>
    </template>

    <audio ref="vocalAudio" preload="auto" :src="`/api/projects/${project.id}/audio/vocal?transpose=${project.transpose_semitones}`"></audio>
    <audio
      v-if="project.reference.instrumental_path"
      ref="instrumentalAudio"
      preload="auto"
      :src="`/api/projects/${project.id}/audio/instrumental?transpose=${project.transpose_semitones}`"
    ></audio>
  </section>
</template>

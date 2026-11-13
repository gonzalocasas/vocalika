<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue"

import { sampleUrl } from "../practice/pianoSamples"
import { StudioEngine } from "../recording/studioEngine"
import {
  audioDevices,
  chooseInput,
  chooseOutput,
  latencyForPair,
  openMicrophone,
  outputsSettled,
  pairKey,
  rememberLatency,
  routeNow,
} from "../../shared/audioDevices"

// During first-run setup measuring is the point of the step, so it stands out.
defineProps<{ highlightMeasure?: boolean }>()

// The microphone stays open while this tab is showing: browsers only reveal
// device names to a page using the microphone, and the level meter is how the
// singer can tell the right one is live.
const level = ref(0)
const error = ref("")
const opening = ref(false)
const testing = ref(false)
let stream: MediaStream | null = null
// Created up front, so its output is already routed by the time Measure is
// pressed: WebKit only switches outputs within a click.
let engine: StudioEngine | null = null
const measuring = ref(false)
const measureError = ref("")
const pair = computed(() => pairKey())
const measured = computed(() => latencyForPair(pair.value))
const measuredOn = computed(() =>
  measured.value
    ? new Intl.DateTimeFormat(undefined, { day: "numeric", month: "short" }).format(new Date(measured.value.measuredAt))
    : "",
)

async function measure(): Promise<void> {
  if (!stream) return
  measuring.value = true
  measureError.value = ""
  try {
    engine ??= await StudioEngine.forCalibration()
    await engine.attachMicrophone(stream)
    await outputsSettled()
    const result = await engine.measureRoundTrip()
    if (!result) {
      measureError.value = "The chirps were not heard clearly. Hold your headphones right against the "
        + "microphone (or switch to speakers for a moment), turn the volume up, and try again."
      return
    }
    rememberLatency(result.seconds, pair.value)
  } catch (reason) {
    measureError.value = reason instanceof Error ? reason.message : String(reason)
  } finally {
    engine?.detachMicrophone()
    measuring.value = false
  }
}
let context: AudioContext | null = null
let frame: number | undefined

const inputValue = computed(() => audioDevices.chosenInput?.id ?? "")
const outputValue = computed(() => audioDevices.chosenOutput?.id ?? "")
const systemInput = computed(() =>
  audioDevices.defaultInputLabel ? `System default (${audioDevices.defaultInputLabel})` : "System default",
)
const systemOutput = computed(() =>
  audioDevices.defaultOutputLabel ? `System default (${audioDevices.defaultOutputLabel})` : "System default",
)

function closeMicrophone(): void {
  if (frame !== undefined) window.cancelAnimationFrame(frame)
  frame = undefined
  stream?.getTracks().forEach((track) => track.stop())
  stream = null
  void context?.close()
  context = null
  level.value = 0
}

async function openMeter(): Promise<void> {
  closeMicrophone()
  opening.value = true
  error.value = ""
  try {
    stream = await openMicrophone({ echoCancellation: false, noiseSuppression: false, autoGainControl: false })
    context = new AudioContext()
    const analyser = context.createAnalyser()
    analyser.fftSize = 1024
    context.createMediaStreamSource(stream).connect(analyser)
    const samples = new Float32Array(analyser.fftSize)
    const tick = (): void => {
      analyser.getFloatTimeDomainData(samples)
      let peak = 0
      for (const sample of samples) peak = Math.max(peak, Math.abs(sample))
      // Decibels mapped onto the bar, so speech moves it visibly.
      const decibels = 20 * Math.log10(Math.max(peak, 1e-5))
      level.value = Math.min(1, Math.max(0, (decibels + 60) / 60))
      frame = window.requestAnimationFrame(tick)
    }
    tick()
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : String(reason)
  } finally {
    opening.value = false
  }
}

async function onInput(id: string): Promise<void> {
  chooseInput(id)
  await openMeter()
}

async function playTestNote(): Promise<void> {
  testing.value = true
  const note = new Audio(sampleUrl(69))
  try {
    // Routed inside this click: WebKit only switches outputs during a gesture.
    await routeNow(note)
    await note.play()
    // The sample rings on for seconds; a short note says enough, and the
    // button should be ready again by the time the singer reaches for it.
    await new Promise((resolve) => window.setTimeout(resolve, 1200))
    for (let step = 1; step <= 6; step += 1) {
      note.volume = 1 - step / 6
      await new Promise((resolve) => window.setTimeout(resolve, 50))
    }
    note.pause()
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : String(reason)
  } finally {
    testing.value = false
  }
}

onMounted(() => {
  void openMeter()
  void StudioEngine.forCalibration().then((created) => { engine = created }, () => undefined)
})
onBeforeUnmount(() => {
  closeMicrophone()
  engine?.close()
  engine = null
})
</script>

<template>
  <div class="audio-settings">
    <label class="device-field">
      <span>MICROPHONE</span>
      <select
        class="graphite-select"
        :value="inputValue"
        :disabled="opening || !audioDevices.namesKnown"
        @change="onInput(($event.target as HTMLSelectElement).value)"
      >
        <option value="">{{ systemInput }}</option>
        <option v-for="device in audioDevices.inputs" :key="device.id" :value="device.id">{{ device.label }}</option>
      </select>
    </label>
    <div class="level-meter" role="meter" aria-label="Microphone level" :aria-valuenow="Math.round(level * 100)" aria-valuemin="0" aria-valuemax="100">
      <i :style="{ transform: `scaleX(${level})` }"></i>
    </div>
    <p class="storage-note">
      <template v-if="audioDevices.inputInUse">Listening to <b>{{ audioDevices.inputInUse }}</b>. Sing or speak: the bar should move.</template>
      <template v-else-if="opening">Opening the microphone…</template>
    </p>
    <p v-if="audioDevices.notice" class="inline-error">{{ audioDevices.notice }}</p>
    <p v-if="audioDevices.outputNotice" class="inline-error">{{ audioDevices.outputNotice }}</p>

    <label class="device-field">
      <span>OUTPUT</span>
      <select
        v-if="audioDevices.canChooseOutput"
        class="graphite-select"
        :value="outputValue"
        :disabled="!audioDevices.namesKnown"
        @change="chooseOutput(($event.target as HTMLSelectElement).value)"
      >
        <option value="">{{ systemOutput }}</option>
        <option v-for="device in audioDevices.outputs" :key="device.id" :value="device.id">{{ device.label }}</option>
      </select>
      <output v-else class="device-fixed">System output<small>Change it in the system's sound settings.</small></output>
    </label>
    <button type="button" class="ghost-button compact test-note" :disabled="testing" @click="playTestNote">
      {{ testing ? "PLAYING…" : "▶ PLAY A TEST NOTE" }}
    </button>

    <p v-if="error" class="inline-error">{{ error }}</p>

    <section class="latency-panel" aria-labelledby="latency-title">
      <span id="latency-title" class="device-label">LATENCY</span>
      <p class="latency-value">
        <span v-if="measured"><b>{{ Math.round(measured.seconds * 1000) }} ms</b> · measured {{ measuredOn }}</span>
        <span v-else><b>Not measured</b></span>
        <small>{{ pair }}</small>
      </p>
      <p class="storage-note">
        Sound takes a moment to reach your ears, and your voice a moment to come back in. Takes
        are shifted by this much so they line up with the song. Measure it once per microphone
        and output: put your headphones against the microphone (or switch to speakers for a
        moment) and press Measure. You will hear eight short chirps.
      </p>
      <button
        type="button"
        class="ghost-button compact"
        :class="{ 'accent-button': highlightMeasure && !measured }"
        :disabled="measuring || opening || !audioDevices.inputInUse"
        @click="measure"
      >{{ measuring ? "LISTENING…" : measured ? "MEASURE AGAIN" : "MEASURE LATENCY" }}</button>
      <p v-if="measureError" class="inline-error">{{ measureError }}</p>
    </section>

    <p class="storage-note">Use headphones when recording, so the backing track stays out of your take.</p>
  </div>
</template>

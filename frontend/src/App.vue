<script setup lang="ts">
import Plotly from "plotly.js-dist-min"
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from "vue"

interface Summary {
  global_bias_cents: number
  mean_absolute_error_cents: number
  within_25_percent: number
  within_50_percent: number
  valid_frame_count: number
}

interface Frames {
  reference_time: number[]
  performance_time: number[]
  reference_midi: number[]
  performance_midi: number[]
  confidence: number[]
  valid: boolean[]
  absolute_error_cents: number[]
  relative_error_cents: number[]
}

interface Artifact {
  created_at: string
  reference: { source: { path: string; duration_seconds: number }; is_isolated_vocal: boolean }
  performance: { source: { path: string; duration_seconds: number } }
  comparison: { summary: Summary; frames: Frames }
  warnings: string[]
}

const artifact = ref<Artifact | null>(null)
const error = ref("")
const pitchPlot = ref<HTMLDivElement | null>(null)
const errorPlot = ref<HTMLDivElement | null>(null)
const referenceAudio = ref<HTMLAudioElement | null>(null)
const performanceAudio = ref<HTMLAudioElement | null>(null)
const selectionStart = ref(0)
const selectionEnd = ref(30)
const comparisonMode = ref<"absolute" | "relative">("absolute")
const looping = ref(false)
const activePlayer = ref<"reference" | "performance" | null>(null)
let stopTimer: number | undefined
let sequenceTimer: number | undefined

const summary = computed(() => artifact.value?.comparison.summary)
const fileName = (path: string) => path.split("/").pop() ?? path
const formatCents = (value: number) => `${value >= 0 ? "+" : ""}${value.toFixed(1)}¢`

function mappedPerformanceTime(referenceTime: number): number {
  const frames = artifact.value?.comparison.frames
  if (!frames || frames.reference_time.length === 0) return referenceTime
  let low = 0
  let high = frames.reference_time.length - 1
  while (low < high) {
    const middle = Math.floor((low + high) / 2)
    if (frames.reference_time[middle] < referenceTime) low = middle + 1
    else high = middle
  }
  const current = low
  const previous = Math.max(0, current - 1)
  const index =
    Math.abs(frames.reference_time[previous] - referenceTime) <
    Math.abs(frames.reference_time[current] - referenceTime)
      ? previous
      : current
  return frames.performance_time[index]
}

function clearTimers(): void {
  if (stopTimer !== undefined) window.clearTimeout(stopTimer)
  if (sequenceTimer !== undefined) window.clearTimeout(sequenceTimer)
  stopTimer = undefined
  sequenceTimer = undefined
}

function stopAll(): void {
  clearTimers()
  referenceAudio.value?.pause()
  performanceAudio.value?.pause()
  activePlayer.value = null
}

function scheduleStop(kind: "reference" | "performance", start: number, end: number): void {
  const duration = Math.max(0.05, end - start)
  stopTimer = window.setTimeout(() => {
    const player = kind === "reference" ? referenceAudio.value : performanceAudio.value
    player?.pause()
    activePlayer.value = null
    if (looping.value) void play(kind)
  }, duration * 1000)
}

async function play(kind: "reference" | "performance"): Promise<void> {
  stopAll()
  const player = kind === "reference" ? referenceAudio.value : performanceAudio.value
  if (!player) return
  const start = kind === "reference" ? selectionStart.value : mappedPerformanceTime(selectionStart.value)
  const end = kind === "reference" ? selectionEnd.value : mappedPerformanceTime(selectionEnd.value)
  player.currentTime = start
  activePlayer.value = kind
  await player.play()
  scheduleStop(kind, start, end)
}

async function playAB(): Promise<void> {
  looping.value = false
  await play("reference")
  const duration = Math.max(0.05, selectionEnd.value - selectionStart.value)
  sequenceTimer = window.setTimeout(() => void play("performance"), duration * 1000 + 180)
}

function masked(values: number[], valid: boolean[]): Array<number | null> {
  return values.map((value, index) => (valid[index] ? value : null))
}

async function renderPlots(): Promise<void> {
  if (!artifact.value || !pitchPlot.value || !errorPlot.value) return
  const frames = artifact.value.comparison.frames
  const referencePitch = masked(frames.reference_midi, frames.valid)
  const performancePitch = masked(frames.performance_midi, frames.valid)
  const errorValues = masked(
    comparisonMode.value === "absolute"
      ? frames.absolute_error_cents
      : frames.relative_error_cents,
    frames.valid,
  )
  const baseLayout = {
    paper_bgcolor: "transparent",
    plot_bgcolor: "transparent",
    font: { color: "#dddcd3", family: "Inter, ui-sans-serif, system-ui" },
    margin: { l: 58, r: 22, t: 16, b: 46 },
    hovermode: "x unified" as const,
    xaxis: { gridcolor: "#32352d", title: { text: "Reference time (seconds)" } },
    yaxis: { gridcolor: "#32352d" },
    legend: { orientation: "h" as const, y: 1.12 },
  }
  await Plotly.react(
    pitchPlot.value,
    [
      {
        x: frames.reference_time,
        y: referencePitch,
        name: "Reference",
        type: "scattergl",
        mode: "lines",
        line: { color: "#d5ff74", width: 2 },
      },
      {
        x: frames.reference_time,
        y: performancePitch,
        name: "Mine",
        type: "scattergl",
        mode: "lines",
        line: { color: "#ff8e70", width: 2 },
      },
    ],
    {
      ...baseLayout,
      height: 420,
      yaxis: { ...baseLayout.yaxis, title: { text: "Continuous MIDI" } },
    },
    { responsive: true, displaylogo: false },
  )
  await Plotly.react(
    errorPlot.value,
    [
      {
        x: frames.reference_time,
        y: errorValues,
        name: comparisonMode.value === "absolute" ? "Absolute error" : "Relative error",
        type: "scattergl",
        mode: "lines",
        line: { color: "#77cfff", width: 1.5 },
      },
    ],
    {
      ...baseLayout,
      height: 285,
      shapes: [
        {
          type: "rect",
          xref: "paper",
          x0: 0,
          x1: 1,
          y0: -25,
          y1: 25,
          fillcolor: "rgba(156, 216, 115, 0.10)",
          line: { width: 0 },
          layer: "below",
        },
        {
          type: "line",
          xref: "paper",
          x0: 0,
          x1: 1,
          y0: 0,
          y1: 0,
          line: { color: "#9b9e91", dash: "dot", width: 1 },
        },
      ],
      yaxis: { ...baseLayout.yaxis, title: { text: "Cents" }, range: [-200, 200] },
    },
    { responsive: true, displaylogo: false },
  )
}

async function loadAnalysis(): Promise<void> {
  try {
    const response = await fetch("/api/analysis")
    if (!response.ok) throw new Error(`Analysis request failed (${response.status})`)
    artifact.value = (await response.json()) as Artifact
    const times = artifact.value.comparison.frames.reference_time
    selectionStart.value = times[0] ?? 0
    selectionEnd.value = Math.min(times[times.length - 1] ?? 30, 30)
    await nextTick()
    await renderPlots()
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : String(reason)
  }
}

onMounted(loadAnalysis)
onBeforeUnmount(() => {
  stopAll()
  if (pitchPlot.value) Plotly.purge(pitchPlot.value)
  if (errorPlot.value) Plotly.purge(errorPlot.value)
})
</script>

<template>
  <main>
    <header>
      <div>
        <p class="eyebrow">FEASIBILITY ANALYSIS · MILESTONE 0</p>
        <h1>Vocalika</h1>
        <p class="subtitle">See where your performance moves away from the reference.</p>
      </div>
      <span class="local-badge">Local only</span>
    </header>

    <section v-if="error" class="notice error">{{ error }}</section>

    <template v-if="artifact && summary">
      <section v-if="artifact.warnings.length" class="notice warning">
        {{ artifact.warnings.join(" ") }}
      </section>

      <section class="source-row">
        <article>
          <span>REFERENCE</span>
          <strong>{{ fileName(artifact.reference.source.path) }}</strong>
          <small>{{ artifact.reference.is_isolated_vocal ? "Isolated vocal" : "Full mix" }}</small>
        </article>
        <article>
          <span>MY PERFORMANCE</span>
          <strong>{{ fileName(artifact.performance.source.path) }}</strong>
          <small>Isolated vocal</small>
        </article>
      </section>

      <section class="metrics">
        <article>
          <span>MEAN ABSOLUTE ERROR</span>
          <strong>{{ summary.mean_absolute_error_cents.toFixed(1) }}¢</strong>
        </article>
        <article>
          <span>GLOBAL BIAS</span>
          <strong>{{ formatCents(summary.global_bias_cents) }}</strong>
        </article>
        <article>
          <span>WITHIN ±25 CENTS</span>
          <strong>{{ summary.within_25_percent.toFixed(1) }}%</strong>
        </article>
        <article>
          <span>WITHIN ±50 CENTS</span>
          <strong>{{ summary.within_50_percent.toFixed(1) }}%</strong>
        </article>
      </section>

      <section class="panel graph-panel">
        <div class="panel-heading">
          <div>
            <span class="section-label">ALIGNED CONTOURS</span>
            <h2>Pitch movement</h2>
          </div>
          <div class="segmented">
            <button :class="{ active: comparisonMode === 'absolute' }" @click="comparisonMode = 'absolute'; renderPlots()">
              Absolute
            </button>
            <button :class="{ active: comparisonMode === 'relative' }" @click="comparisonMode = 'relative'; renderPlots()">
              Relative
            </button>
          </div>
        </div>
        <div ref="pitchPlot" class="plot"></div>
        <div class="error-heading">
          <span class="section-label">PITCH DIFFERENCE</span>
          <span>The shaded band is within ±25 cents.</span>
        </div>
        <div ref="errorPlot" class="plot"></div>
      </section>

      <section class="panel playback-panel">
        <div>
          <span class="section-label">LISTENING GATE</span>
          <h2>Compare the same phrase</h2>
        </div>
        <div class="range-controls">
          <label>From <input v-model.number="selectionStart" type="number" min="0" step="0.1" /></label>
          <label>To <input v-model.number="selectionEnd" type="number" min="0" step="0.1" /></label>
          <span>seconds, in reference time</span>
        </div>
        <div class="transport">
          <button :class="{ active: activePlayer === 'reference' }" @click="play('reference')">Reference</button>
          <button :class="{ active: activePlayer === 'performance' }" @click="play('performance')">Mine</button>
          <button @click="playAB">A / B</button>
          <button @click="stopAll">Stop</button>
          <label class="loop"><input v-model="looping" type="checkbox" /> Loop</label>
        </div>
        <audio ref="referenceAudio" preload="metadata" src="/api/audio/reference"></audio>
        <audio ref="performanceAudio" preload="metadata" src="/api/audio/performance"></audio>
      </section>
    </template>

    <section v-else-if="!error" class="loading">Preparing the analysis view…</section>
  </main>
</template>

<script setup lang="ts">
import Plotly, { type PlotlyHTMLElement, type PlotRelayoutEvent } from "plotly.js-dist-min"
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from "vue"

interface Summary {
  global_bias_cents: number
  mean_absolute_error_cents: number
  relative_mean_absolute_error_cents: number
  within_15_percent: number
  within_25_percent: number
  within_50_percent: number
  relative_within_15_percent: number
  relative_within_25_percent: number
  relative_within_50_percent: number
  valid_frame_count: number
  valid_fraction: number
  matched_seconds: number
  stable_note_pitch_center_mae_cents: number | null
  relative_stable_note_pitch_center_mae_cents: number | null
  stable_note_duration_weighted_mae_cents: number | null
  relative_stable_note_duration_weighted_mae_cents: number | null
  stable_note_region_count: number
  stable_note_total_seconds: number
}

interface StablePitchRegion {
  reference_start: number
  reference_end: number
  error_cents: number
  relative_error_cents: number
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
  reference: {
    source: { path: string; duration_seconds: number }
    is_isolated_vocal: boolean
    original_mix: { path: string; duration_seconds: number } | null
  }
  performance: { source: { path: string; duration_seconds: number } }
  comparison: { summary: Summary; frames: Frames; stable_pitch_regions: StablePitchRegion[] }
  warnings: string[]
}

const artifact = ref<Artifact | null>(null)
const error = ref("")
const pitchPlot = ref<HTMLDivElement | null>(null)
const errorPlot = ref<HTMLDivElement | null>(null)
const referenceAudio = ref<HTMLAudioElement | null>(null)
const referenceMixAudio = ref<HTMLAudioElement | null>(null)
const performanceAudio = ref<HTMLAudioElement | null>(null)
const referenceMode = ref<"url" | "file">("file")
const referenceUrl = ref("")
const referenceFile = ref<File | null>(null)
const performanceFile = ref<File | null>(null)
const referenceIsVocal = ref(false)
const analyzing = ref(false)
const analysisStatus = ref("")
const selectionStart = ref(0)
const selectionEnd = ref(30)
const comparisonMode = ref<"absolute" | "relative">("absolute")
const looping = ref(false)
type PlayerKind = "reference" | "reference-mix" | "performance"
const activePlayer = ref<PlayerKind | null>(null)
let stopTimer: number | undefined
let sequenceTimer: number | undefined
let plotsAreLinked = false
let mirroringRange = false

const summary = computed(() => artifact.value?.comparison.summary)
const displayedMeanError = computed(() =>
  comparisonMode.value === "absolute"
    ? summary.value?.mean_absolute_error_cents
    : summary.value?.relative_mean_absolute_error_cents,
)
const displayedWithin25 = computed(() =>
  comparisonMode.value === "absolute"
    ? summary.value?.within_25_percent
    : summary.value?.relative_within_25_percent,
)
const displayedWithin50 = computed(() =>
  comparisonMode.value === "absolute"
    ? summary.value?.within_50_percent
    : summary.value?.relative_within_50_percent,
)
const displayedStableCenterError = computed(() =>
  comparisonMode.value === "absolute"
    ? summary.value?.stable_note_pitch_center_mae_cents
    : summary.value?.relative_stable_note_pitch_center_mae_cents,
)
const audioVersion = computed(() => encodeURIComponent(artifact.value?.created_at ?? "initial"))
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
  referenceMixAudio.value?.pause()
  performanceAudio.value?.pause()
  activePlayer.value = null
}

function playerFor(kind: PlayerKind): HTMLAudioElement | null {
  if (kind === "reference") return referenceAudio.value
  if (kind === "reference-mix") return referenceMixAudio.value
  return performanceAudio.value
}

function scheduleStop(kind: PlayerKind, start: number, end: number): void {
  const duration = Math.max(0.05, end - start)
  stopTimer = window.setTimeout(() => {
    const player = playerFor(kind)
    player?.pause()
    activePlayer.value = null
    if (looping.value) void play(kind)
  }, duration * 1000)
}

async function play(kind: PlayerKind): Promise<void> {
  stopAll()
  const player = playerFor(kind)
  if (!player) return
  const usesReferenceTime = kind !== "performance"
  const start = usesReferenceTime ? selectionStart.value : mappedPerformanceTime(selectionStart.value)
  const end = usesReferenceTime ? selectionEnd.value : mappedPerformanceTime(selectionEnd.value)
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

async function mirrorVisibleRange(
  target: PlotlyHTMLElement,
  event: PlotRelayoutEvent,
): Promise<void> {
  if (mirroringRange) return
  const update = event as unknown as Record<string, unknown>
  const start = Number(update["xaxis.range[0]"])
  const end = Number(update["xaxis.range[1]"])
  mirroringRange = true
  try {
    if (Number.isFinite(start) && Number.isFinite(end)) {
      selectionStart.value = Math.max(0, Math.min(start, end))
      selectionEnd.value = Math.max(start, end)
      await Plotly.relayout(target, { xaxis: { range: [start, end] } })
    } else if (update["xaxis.autorange"] === true) {
      await Plotly.relayout(target, { xaxis: { autorange: true } })
    }
  } finally {
    mirroringRange = false
  }
}

function linkPlotRanges(): void {
  if (plotsAreLinked || !pitchPlot.value || !errorPlot.value) return
  const pitch = pitchPlot.value as unknown as PlotlyHTMLElement
  const pitchError = errorPlot.value as unknown as PlotlyHTMLElement
  pitch.on("plotly_relayout", (event) => void mirrorVisibleRange(pitchError, event))
  pitchError.on("plotly_relayout", (event) => void mirrorVisibleRange(pitch, event))
  plotsAreLinked = true
}

function unlinkPlotRanges(): void {
  if (!plotsAreLinked) return
  ;(pitchPlot.value as unknown as PlotlyHTMLElement | null)?.removeAllListeners("plotly_relayout")
  ;(errorPlot.value as unknown as PlotlyHTMLElement | null)?.removeAllListeners("plotly_relayout")
  plotsAreLinked = false
}

async function renderPlots(): Promise<void> {
  if (!artifact.value || !pitchPlot.value || !errorPlot.value) return
  const frames = artifact.value.comparison.frames
  const referencePitch = masked(frames.reference_midi, frames.valid)
  const performancePitch = masked(frames.performance_midi, frames.valid).map((value) =>
    value === null || comparisonMode.value === "absolute"
      ? value
      : value - artifact.value!.comparison.summary.global_bias_cents / 100,
  )
  const errorValues = masked(
    comparisonMode.value === "absolute"
      ? frames.absolute_error_cents
      : frames.relative_error_cents,
    frames.valid,
  )
  const stableRegionShapes = artifact.value.comparison.stable_pitch_regions.map((region) => ({
    type: "rect" as const,
    x0: region.reference_start,
    x1: region.reference_end,
    yref: "paper" as const,
    y0: 0,
    y1: 1,
    fillcolor: "rgba(182, 227, 92, 0.07)",
    line: { width: 0 },
    layer: "below" as const,
  }))
  const baseLayout = {
    paper_bgcolor: "transparent",
    plot_bgcolor: "transparent",
    font: { color: "#dddcd3", family: "Inter, ui-sans-serif, system-ui" },
    margin: { l: 58, r: 22, t: 16, b: 46 },
    hovermode: "x unified" as const,
    uirevision: artifact.value.created_at,
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
      shapes: stableRegionShapes,
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
  linkPlotRanges()
}

function chooseReferenceFile(event: Event): void {
  referenceFile.value = (event.target as HTMLInputElement).files?.[0] ?? null
}

function choosePerformanceFile(event: Event): void {
  performanceFile.value = (event.target as HTMLInputElement).files?.[0] ?? null
}

async function submitAnalysis(): Promise<void> {
  error.value = ""
  if (!performanceFile.value) {
    error.value = "Choose your performance FLAC or audio file."
    return
  }
  if (referenceMode.value === "url" && !referenceUrl.value.trim()) {
    error.value = "Paste a public YouTube reference URL."
    return
  }
  if (referenceMode.value === "file" && !referenceFile.value) {
    error.value = "Choose a local reference audio file."
    return
  }
  const form = new FormData()
  form.append("performance_file", performanceFile.value)
  form.append("reference_is_vocal", String(referenceMode.value === "file" && referenceIsVocal.value))
  if (referenceMode.value === "url") form.append("reference_url", referenceUrl.value.trim())
  else form.append("reference_file", referenceFile.value!)

  analyzing.value = true
  analysisStatus.value = "Uploading audio and running local analysis…"
  stopAll()
  try {
    const response = await fetch("/api/analyze", { method: "POST", body: form })
    const payload = (await response.json()) as { artifact?: Artifact; detail?: string }
    if (!response.ok || !payload.artifact) {
      throw new Error(payload.detail ?? `Analysis failed (${response.status})`)
    }
    artifact.value = payload.artifact
    unlinkPlotRanges()
    const times = artifact.value.comparison.frames.reference_time
    selectionStart.value = times[0] ?? 0
    selectionEnd.value = Math.min(times[times.length - 1] ?? 30, 30)
    analysisStatus.value = "Analysis complete."
    await nextTick()
    referenceAudio.value?.load()
    referenceMixAudio.value?.load()
    performanceAudio.value?.load()
    await renderPlots()
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : String(reason)
    analysisStatus.value = ""
  } finally {
    analyzing.value = false
  }
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
        <p class="eyebrow">LOCAL VOCAL ANALYSIS</p>
        <h1>Vocalika</h1>
        <p class="subtitle">See where your performance moves away from the reference.</p>
      </div>
      <span class="local-badge">Local only</span>
    </header>

    <section v-if="error" class="notice error">{{ error }}</section>

    <section class="panel new-analysis-panel">
      <div class="panel-heading analysis-heading">
        <div>
          <span class="section-label">NEW ANALYSIS</span>
          <h2>Compare another take</h2>
        </div>
        <span class="saved-note">Files stay local in samples/uploads</span>
      </div>
      <form @submit.prevent="submitAnalysis">
        <div class="input-grid">
          <fieldset>
            <legend>Reference</legend>
            <div class="segmented source-switch">
              <button
                type="button"
                :class="{ active: referenceMode === 'file' }"
                @click="referenceMode = 'file'"
              >
                Local file
              </button>
              <button
                type="button"
                :class="{ active: referenceMode === 'url' }"
                @click="referenceMode = 'url'"
              >
                YouTube URL
              </button>
            </div>
            <input
              v-if="referenceMode === 'file'"
              type="file"
              accept=".flac,.wav,.mp3,.m4a,audio/*"
              @change="chooseReferenceFile"
            />
            <input
              v-else
              v-model="referenceUrl"
              type="url"
              placeholder="https://www.youtube.com/watch?v=..."
            />
            <label v-if="referenceMode === 'file'" class="checkbox-row">
              <input v-model="referenceIsVocal" type="checkbox" />
              This file is already an isolated vocal
            </label>
          </fieldset>
          <fieldset>
            <legend>My performance</legend>
            <input
              type="file"
              accept=".flac,.wav,.mp3,.m4a,audio/*"
              @change="choosePerformanceFile"
            />
            <small>FLAC exported from Ableton is preferred.</small>
          </fieldset>
        </div>
        <div class="analysis-action">
          <span>{{ analysisStatus }}</span>
          <button class="primary-button" type="submit" :disabled="analyzing">
            {{ analyzing ? "Analyzing…" : "Analyze" }}
          </button>
        </div>
      </form>
    </section>

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
          <span>{{ comparisonMode === "absolute" ? "ABSOLUTE MEAN ERROR" : "RELATIVE MEAN ERROR" }}</span>
          <strong>{{ displayedMeanError?.toFixed(1) }}¢</strong>
        </article>
        <article>
          <span>GLOBAL BIAS</span>
          <strong>{{ formatCents(summary.global_bias_cents) }}</strong>
        </article>
        <article>
          <span>WITHIN ±25 CENTS</span>
          <strong>{{ displayedWithin25?.toFixed(1) }}%</strong>
        </article>
        <article>
          <span>WITHIN ±50 CENTS</span>
          <strong>{{ displayedWithin50?.toFixed(1) }}%</strong>
        </article>
        <article class="stable-metric">
          <span>STABLE-NOTE CENTER MAE</span>
          <strong>
            {{ displayedStableCenterError === null ? "—" : `${displayedStableCenterError?.toFixed(1)}¢` }}
          </strong>
          <small>
            {{ summary.stable_note_region_count }} regions ·
            {{ summary.stable_note_total_seconds.toFixed(1) }}s
          </small>
        </article>
      </section>

      <section class="metric-explanation">
        <strong>Contour MAE</strong> includes pitch movement and transitions.
        <strong>Stable-note center MAE</strong> compares median pitch centers only inside the
        green-highlighted sustained regions. It is narrower and should not be read as an overall
        singing score.
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
          <span>
            {{ comparisonMode === "absolute" ? "Literal pitch" : "Global bias compensated" }} ·
            shaded band is within ±25 cents.
          </span>
        </div>
        <p class="graph-hint">Zoom either chart to set the phrase used by the listening controls.</p>
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
          <button :class="{ active: activePlayer === 'reference' }" @click="play('reference')">Reference vocal</button>
          <button
            :class="{ active: activePlayer === 'reference-mix' }"
            @click="play('reference-mix')"
          >
            Original mix
          </button>
          <button :class="{ active: activePlayer === 'performance' }" @click="play('performance')">Mine</button>
          <button @click="playAB">A / B</button>
          <button @click="stopAll">Stop</button>
          <label class="loop"><input v-model="looping" type="checkbox" /> Loop</label>
        </div>
        <audio ref="referenceAudio" preload="metadata" :src="`/api/audio/reference?v=${audioVersion}`"></audio>
        <audio ref="referenceMixAudio" preload="metadata" :src="`/api/audio/reference-mix?v=${audioVersion}`"></audio>
        <audio ref="performanceAudio" preload="metadata" :src="`/api/audio/performance?v=${audioVersion}`"></audio>
      </section>
    </template>

    <section v-else-if="!error" class="loading">Preparing the analysis view…</section>
  </main>
</template>

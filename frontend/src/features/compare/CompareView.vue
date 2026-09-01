<script setup lang="ts">
import type { PlotlyHTMLElement, PlotRelayoutEvent } from "plotly.js-dist-min"
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue"

import { calculateRangeSummary } from "../../metrics"
import {
  performanceToReferenceTime,
  referenceToPerformanceTime,
  resolvePlaybackOffset,
} from "../../playbackTiming"
import { displayContour, rawContour } from "../../plotData"
import { apiJson } from "../../shared/api"
import type { AlignedWaveforms, AnalysisArtifact, Project, Take } from "../../shared/types"
import PitchHeatmapBand from "./PitchHeatmapBand.vue"
import { midiToCents, noteTicks, pitchExtent, seriesToCents } from "./pitchAxis"

const props = defineProps<{ project: Project; take: Take; artifact: AnalysisArtifact }>()
const emit = defineEmits<{ export: [] }>()

const pitchPlot = ref<HTMLDivElement | null>(null)
const confidencePlot = ref<HTMLDivElement | null>(null)
const errorPlot = ref<HTMLDivElement | null>(null)
const waveforms = ref<AlignedWaveforms | null>(null)
const metricScope = ref<"full" | "selection">("full")
const comparisonMode = ref<"absolute" | "relative">("absolute")
const showReference = ref(true)
const showPerformance = ref(true)
const showWaveforms = ref(true)
const showPoints = ref(false)
const times = props.artifact.comparison.frames.reference_time
const takePlaybackOffset = resolvePlaybackOffset(
  props.artifact.alignment,
  props.artifact.comparison.frames.reference_time,
  props.artifact.comparison.frames.performance_time,
)
const selectionStart = ref(times[0] ?? 0)
// The whole take, so SELECTED RANGE and FULL ANALYSIS agree until the range is
// actually narrowed. Defaulting to the first thirty seconds made the two scopes
// disagree on load, with no indication that the selection was not what the
// fully zoomed-out chart was showing.
const selectionEnd = ref(times.at(-1) ?? 30)
const looping = ref(false)
const activePlayer = ref<"reference" | "mix" | "take" | null>(null)
const playbackPosition = ref(selectionStart.value)
const referenceAudio = ref<HTMLAudioElement | null>(null)
const mixAudio = ref<HTMLAudioElement | null>(null)
const takeAudio = ref<HTMLAudioElement | null>(null)
let plotly: typeof import("plotly.js-dist-min")["default"] | null = null
let linked = false
let mirroring = false
let stopTimer: number | undefined
let sequenceTimer: number | undefined
let playbackFrame: number | undefined
let lastCursorUpdate = 0

async function loadPlotly(): Promise<typeof import("plotly.js-dist-min")["default"]> {
  if (!plotly) plotly = (await import("plotly.js-dist-min")).default
  return plotly
}

const selectedSummary = computed(() => calculateRangeSummary(
  props.artifact.comparison.frames,
  props.artifact.comparison.stable_pitch_regions ?? [],
  selectionStart.value,
  selectionEnd.value,
  props.artifact.alignment?.frames_per_second ?? 10,
))
const summary = computed(() => metricScope.value === "full"
  ? props.artifact.comparison.summary
  : selectedSummary.value)
// The mean is shown alongside the median rather than instead of it: a wide
// gap between them is itself the signal that a few badly-tracked frames are
// carrying the score, which is exactly when the mean misleads.
// Naming the interval is the point: a metric scoped to part of a take must say
// which part, or it silently disagrees with the chart beside it.
const scopeLabel = computed(() => {
  if (metricScope.value === "full") return "whole take"
  const start = selectionStart.value
  const end = selectionEnd.value
  return `${start.toFixed(1)}\u2013${end.toFixed(1)}s`
})

const medianError = computed(() => comparisonMode.value === "absolute"
  ? summary.value?.median_absolute_error_cents
  : summary.value?.relative_median_absolute_error_cents)
const meanError = computed(() => comparisonMode.value === "absolute"
  ? summary.value?.mean_absolute_error_cents
  : summary.value?.relative_mean_absolute_error_cents)
const within25 = computed(() => comparisonMode.value === "absolute"
  ? summary.value?.within_25_percent
  : summary.value?.relative_within_25_percent)
const within50 = computed(() => comparisonMode.value === "absolute"
  ? summary.value?.within_50_percent
  : summary.value?.relative_within_50_percent)
const stableError = computed(() => comparisonMode.value === "absolute"
  ? summary.value?.stable_note_pitch_center_mae_cents
  : summary.value?.relative_stable_note_pitch_center_mae_cents)

function metric(value: number | null | undefined, suffix: string): string {
  return value === null || value === undefined ? "—" : `${value.toFixed(1)}${suffix}`
}

function accepted(track: "reference" | "performance"): boolean[] {
  const frames = props.artifact.comparison.frames
  const confidence = track === "reference" ? frames.reference_confidence : frames.performance_confidence
  const voiced = track === "reference" ? frames.reference_voiced : frames.performance_voiced
  if (!confidence || !voiced) return frames.valid
  const threshold = props.artifact.configuration?.pitch_confidence_threshold ?? 0.55
  return frames.reference_time.map((_, index) => Boolean(voiced[index]) && (confidence[index] ?? 0) >= threshold)
}

function shifted(values: Array<number | null>, amount: number): Array<number | null> {
  return values.map((value) => value === null ? null : value - amount)
}

function waveformBars(time: number[], amplitude: number[]): { x: Array<number | null>; y: Array<number | null> } {
  const stride = Math.max(1, Math.ceil(time.length / 240))
  const x: Array<number | null> = []
  const y: Array<number | null> = []
  for (let index = 0; index < time.length; index += stride) {
    const value = amplitude[index] ?? 0
    x.push(time[index], time[index], null)
    y.push(-value, value, null)
  }
  return { x, y }
}

function cursorShape(position: number): Record<string, unknown> {
  return {
    type: "line",
    x0: position,
    x1: position,
    yref: "paper",
    y0: 0,
    y1: 1,
    line: { color: "#f0e9dc", width: 2 },
    layer: "above",
  }
}

function plotElements(): PlotlyHTMLElement[] {
  return [pitchPlot.value, confidencePlot.value, errorPlot.value]
    .filter((value): value is HTMLDivElement => value !== null)
    .map((value) => value as unknown as PlotlyHTMLElement)
}

/**
 * Keep the note-name axis on the same span as the cents axis.
 *
 * The two are separate axes pinned to one range, so a vertical zoom moves the
 * cents scale and would leave the names beside the wrong pitches. Reading the
 * range back from the plot covers zoom, pan and double-click autoscale alike.
 */
async function syncNoteAxis(): Promise<void> {
  const plot = pitchPlot.value as unknown as { layout?: { yaxis?: { range?: number[] } } } | null
  const range = plot?.layout?.yaxis?.range
  if (!plot || !range || range.length !== 2) return
  const Plotly = await loadPlotly()
  // Plotly's typings cover named layout keys, not the dotted update paths its
  // relayout API accepts.
  await Plotly.relayout(
    pitchPlot.value as unknown as PlotlyHTMLElement,
    { "yaxis3.range": [range[0], range[1]] } as unknown as Partial<Plotly.Layout>,
  )
}

async function mirror(source: PlotlyHTMLElement, event: PlotRelayoutEvent): Promise<void> {
  if (source === (pitchPlot.value as unknown as PlotlyHTMLElement)) {
    const update = event as unknown as Record<string, unknown>
    const touchedY = Object.keys(update).some((key) => key.startsWith("yaxis."))
    if (touchedY) void syncNoteAxis()
  }
  if (mirroring) return
  const update = event as unknown as Record<string, unknown>
  const start = Number(update["xaxis.range[0]"])
  const end = Number(update["xaxis.range[1]"])
  mirroring = true
  try {
    const Plotly = await loadPlotly()
    if (Number.isFinite(start) && Number.isFinite(end)) {
      selectionStart.value = Math.max(0, Math.min(start, end))
      selectionEnd.value = Math.max(start, end)
      await Promise.all(plotElements().filter((plot) => plot !== source).map((plot) => Plotly.relayout(plot, { xaxis: { range: [start, end] } })))
    }
  } finally {
    mirroring = false
  }
}

function linkPlots(): void {
  if (linked || plotElements().length !== 3) return
  for (const plot of plotElements()) plot.on("plotly_relayout", (event) => void mirror(plot, event))
  linked = true
}

function unlinkPlots(): void {
  for (const plot of plotElements()) plot.removeAllListeners("plotly_relayout")
  linked = false
}

async function render(): Promise<void> {
  if (!pitchPlot.value || !confidencePlot.value || !errorPlot.value) return
  const Plotly = await loadPlotly()
  const frames = props.artifact.comparison.frames
  const referenceAccepted = accepted("reference")
  const performanceAccepted = accepted("performance")
  const bias = comparisonMode.value === "relative" ? props.artifact.comparison.summary.global_bias_cents / 100 : 0
  const referencePitch = displayContour(frames.reference_time, frames.reference_midi, referenceAccepted)
  const performancePitch = shifted(displayContour(frames.reference_time, frames.performance_midi, performanceAccepted), bias)
  const error = referencePitch.map((value, index) => value === null || performancePitch[index] === null ? null : 100 * (performancePitch[index]! - value))
  const refConfidence = frames.reference_confidence ?? frames.confidence
  const perfConfidence = frames.performance_confidence ?? frames.confidence
  const threshold = 100 * (props.artifact.configuration?.pitch_confidence_threshold ?? 0.55)
  const base = {
    paper_bgcolor: "#0e1112",
    plot_bgcolor: "#0e1112",
    font: { color: "#7c817f", family: "IBM Plex Mono, monospace", size: 10 },
    margin: { l: 62, r: 46, t: 18, b: 42 },
    hovermode: "x unified" as const,
    uirevision: props.artifact.created_at,
    xaxis: { gridcolor: "#262b2c", title: { text: "Reference time (seconds)" } },
    yaxis: { gridcolor: "#262b2c" },
  }
  // Both vertical axes are pinned to the same span; an autoranged pair would
  // drift apart and put the note names beside the wrong pitches.
  const extent = pitchExtent([
    referencePitch,
    performancePitch,
    ...(showPoints.value ? [rawContour(frames.reference_midi, referenceAccepted)] : []),
  ])
  const pitchRange: [number, number] = [midiToCents(extent.lowMidi), midiToCents(extent.highMidi)]
  const ticks = noteTicks(extent)
  const referenceWave = waveforms.value ? waveformBars(waveforms.value.time, waveforms.value.reference_amplitude) : null
  const performanceWave = waveforms.value ? waveformBars(waveforms.value.time, waveforms.value.performance_amplitude) : null
  await Plotly.react(pitchPlot.value, [
    ...(showWaveforms.value && referenceWave ? [{ ...referenceWave, type: "scattergl" as const, mode: "lines" as const, yaxis: "y2", line: { width: 3, color: "rgba(232,226,214,.18)" }, hoverinfo: "skip" as const, showlegend: false }] : []),
    ...(showWaveforms.value && performanceWave ? [{ ...performanceWave, type: "scattergl" as const, mode: "lines" as const, yaxis: "y2", line: { width: 3, color: "rgba(217,153,46,.20)" }, hoverinfo: "skip" as const, showlegend: false }] : []),
    { x: [frames.reference_time[0] ?? 0], y: [pitchRange[0]], yaxis: "y3", type: "scattergl" as const, mode: "markers" as const, marker: { opacity: 0, size: 0.1 }, hoverinfo: "skip" as const, showlegend: false },
    { x: frames.reference_time, y: seriesToCents(referencePitch), name: "Reference", visible: showReference.value, type: "scattergl", mode: "lines", line: { color: "#e8e2d6", width: 2.2 }, connectgaps: false },
    { x: frames.reference_time, y: seriesToCents(performancePitch), name: "Mine", visible: showPerformance.value, type: "scattergl", mode: "lines", line: { color: "#d9992e", width: 2.2 }, connectgaps: false },
    ...(showPoints.value ? [
      { x: frames.reference_time, y: seriesToCents(rawContour(frames.reference_midi, referenceAccepted)), name: "Reference points", type: "scattergl" as const, mode: "markers" as const, marker: { color: "#e8e2d6", size: 3, opacity: .35 } },
      { x: frames.reference_time, y: seriesToCents(shifted(rawContour(frames.performance_midi, performanceAccepted), bias)), name: "Mine points", type: "scattergl" as const, mode: "markers" as const, marker: { color: "#d9992e", size: 3, opacity: .35 } },
    ] : []),
  ], { ...base, height: 320, shapes: [cursorShape(playbackPosition.value)],
    // Cents on the left so the gap between the contours is the error the tiles
    // report; note names on the right so the pitches stay readable as music.
    yaxis: { ...base.yaxis, title: { text: "Cents from C4" }, range: pitchRange, zeroline: false, tick0: ticks.tick0, dtick: ticks.dtick },
    yaxis2: { overlaying: "y", range: [-1.05, 1.05], visible: false, fixedrange: true },
    yaxis3: { overlaying: "y", side: "right" as const, range: pitchRange, tickvals: ticks.tickvals, ticktext: ticks.ticktext, showgrid: false, zeroline: false, tickfont: { color: "#7c817f" } },
  }, { responsive: true, displaylogo: false })

  await Plotly.react(confidencePlot.value, [
    { x: frames.reference_time, y: refConfidence.map((value) => 100 * value), name: "Reference", type: "scattergl", mode: "lines", line: { color: "#4f8d7b", width: 1.6 } },
    { x: frames.reference_time, y: perfConfidence.map((value) => 100 * value), name: "Mine", type: "scattergl", mode: "lines", line: { color: "#c96f3e", width: 1.6 } },
  ], { ...base, height: 220, shapes: [{ type: "line", xref: "paper", x0: 0, x1: 1, y0: threshold, y1: threshold, line: { color: "#3a4040", dash: "dash", width: 1 } }, cursorShape(playbackPosition.value)], yaxis: { ...base.yaxis, range: [0, 100], title: { text: "Confidence %" } } }, { responsive: true, displaylogo: false })

  await Plotly.react(errorPlot.value, [{ x: frames.reference_time, y: error, name: "Pitch difference", type: "scattergl", mode: "lines", line: { color: "#d9992e", width: 1.8 }, connectgaps: false }], { ...base, height: 220, shapes: [{ type: "rect", xref: "paper", x0: 0, x1: 1, y0: -25, y1: 25, fillcolor: "rgba(79,141,123,.16)", line: { width: 0 }, layer: "below" }, cursorShape(playbackPosition.value)], yaxis: { ...base.yaxis, range: [-200, 200], title: { text: "Cents" } } }, { responsive: true, displaylogo: false })
  linkPlots()
}

function mappedPerformanceTime(referenceTime: number): number {
  return referenceToPerformanceTime(referenceTime, takePlaybackOffset)
}

function mappedReferenceTime(performanceTime: number): number {
  return performanceToReferenceTime(performanceTime, takePlaybackOffset)
}

async function drawPlaybackCursor(position: number): Promise<void> {
  playbackPosition.value = position
  const Plotly = await loadPlotly()
  const updates = [
    [pitchPlot.value, 0],
    [confidencePlot.value, 1],
    [errorPlot.value, 1],
  ] as const
  await Promise.all(updates.flatMap(([plot, shapeIndex]) => plot ? [Plotly.relayout(plot, {
    [`shapes[${shapeIndex}].x0`]: position,
    [`shapes[${shapeIndex}].x1`]: position,
  })] : []))
}

function animatePlayback(timestamp: number): void {
  const kind = activePlayer.value
  if (!kind) return
  const player = kind === "reference" ? referenceAudio.value : kind === "mix" ? mixAudio.value : takeAudio.value
  if (player && timestamp - lastCursorUpdate >= 40) {
    lastCursorUpdate = timestamp
    const position = kind === "take" ? mappedReferenceTime(player.currentTime) : player.currentTime
    void drawPlaybackCursor(position)
  }
  playbackFrame = window.requestAnimationFrame(animatePlayback)
}

function stopAudio(): void {
  for (const audio of [referenceAudio.value, mixAudio.value, takeAudio.value]) audio?.pause()
  activePlayer.value = null
  if (stopTimer !== undefined) window.clearTimeout(stopTimer)
  stopTimer = undefined
  if (sequenceTimer !== undefined) window.clearTimeout(sequenceTimer)
  sequenceTimer = undefined
  if (playbackFrame !== undefined) window.cancelAnimationFrame(playbackFrame)
  playbackFrame = undefined
}

async function play(kind: "reference" | "mix" | "take"): Promise<void> {
  stopAudio()
  const player = kind === "reference" ? referenceAudio.value : kind === "mix" ? mixAudio.value : takeAudio.value
  if (!player) return
  const start = kind === "take" ? mappedPerformanceTime(selectionStart.value) : selectionStart.value
  const end = kind === "take" ? mappedPerformanceTime(selectionEnd.value) : selectionEnd.value
  player.currentTime = start
  await drawPlaybackCursor(selectionStart.value)
  activePlayer.value = kind
  await player.play()
  playbackFrame = window.requestAnimationFrame(animatePlayback)
  stopTimer = window.setTimeout(() => {
    player.pause()
    activePlayer.value = null
    if (playbackFrame !== undefined) window.cancelAnimationFrame(playbackFrame)
    playbackFrame = undefined
    void drawPlaybackCursor(selectionEnd.value)
    if (looping.value) void play(kind)
  }, Math.max(.05, end - start) * 1000)
}

/**
 * Frame the charts on a phrase.
 *
 * A little context either side keeps the phrase from sitting flush against
 * the axes, which makes its approach and release readable.
 */
async function zoomPlotsTo(start: number, end: number): Promise<void> {
  const margin = Math.max(0.25, (end - start) * 0.08)
  const Plotly = await loadPlotly()
  // `mirror` writes the selection back whenever a plot is relayed out. This
  // relayout is the selection, so suppress that round trip rather than let it
  // overwrite the exact phrase bounds with the padded view.
  mirroring = true
  try {
    await Promise.all(
      plotElements().map((plot) =>
        Plotly.relayout(plot, { xaxis: { range: [Math.max(0, start - margin), end + margin] } }),
      ),
    )
  } finally {
    mirroring = false
  }
}

async function resetZoom(): Promise<void> {
  const Plotly = await loadPlotly()
  mirroring = true
  try {
    // Only the view resets. The listening range is left alone so the phrase
    // stays armed for playback while the charts show the whole take again.
    await Promise.all(
      plotElements().map((plot) => Plotly.relayout(plot, { xaxis: { autorange: true } })),
    )
  } finally {
    mirroring = false
  }
}

function selectPhrase(start: number, end: number): void {
  selectionStart.value = Number(start.toFixed(2))
  selectionEnd.value = Number(end.toFixed(2))
  // Looping is what turns "this phrase is wrong" into practice, so arm it
  // rather than making the singer reach for a second control.
  looping.value = true
  void zoomPlotsTo(start, end)
}

async function playAB(): Promise<void> {
  looping.value = false
  await play("reference")
  sequenceTimer = window.setTimeout(() => void play("take"), Math.max(.05, selectionEnd.value - selectionStart.value) * 1000 + 160)
}

async function initialize(): Promise<void> {
  waveforms.value = await apiJson<AlignedWaveforms>(`/api/projects/${props.project.id}/takes/${props.take.id}/waveforms`)
  await nextTick()
  await render()
}

watch([comparisonMode, showReference, showPerformance, showWaveforms, showPoints], () => void render())
onMounted(() => void initialize())
onBeforeUnmount(() => {
  stopAudio()
  unlinkPlots()
  if (pitchPlot.value) plotly?.purge(pitchPlot.value)
  if (confidencePlot.value) plotly?.purge(confidencePlot.value)
  if (errorPlot.value) plotly?.purge(errorPlot.value)
})
</script>

<template>
  <section class="compare-view">
    <div class="compare-heading">
      <div><p class="mono-eyebrow accent-text">TAKE · {{ new Date(take.created_at).toLocaleDateString() }}</p><h2>{{ take.name }}</h2></div>
      <div class="compare-switches">
        <div class="segmented graphite-segmented"><button :class="{ active: metricScope === 'full' }" @click="metricScope = 'full'">FULL ANALYSIS</button><button :class="{ active: metricScope === 'selection' }" @click="metricScope = 'selection'">SELECTED RANGE</button></div>
        <div class="segmented graphite-segmented"><button :class="{ active: comparisonMode === 'absolute' }" @click="comparisonMode = 'absolute'">ABSOLUTE</button><button :class="{ active: comparisonMode === 'relative' }" @click="comparisonMode = 'relative'">RELATIVE</button></div>
        <button class="export-take-button" @click="emit('export')">EXPORT THIS TAKE →</button>
      </div>
    </div>

    <div class="metric-strip">
      <article><span>{{ comparisonMode === "absolute" ? "TYPICAL ERROR" : "RELATIVE TYPICAL" }}</span><strong class="accent-text">{{ metric(medianError, "¢") }}</strong><small>median frame · {{ scopeLabel }}</small></article>
      <article><span>{{ comparisonMode === "absolute" ? "MEAN ERROR" : "RELATIVE MEAN" }}</span><strong>{{ metric(meanError, "¢") }}</strong><small>outlier-sensitive · {{ scopeLabel }}</small></article>
      <article><span>{{ metricScope === "selection" ? "LOCAL BIAS" : "GLOBAL BIAS" }}</span><strong>{{ metric(summary?.global_bias_cents, "¢") }}</strong><small>median signed offset</small></article>
      <article><span>WITHIN ±25¢</span><strong>{{ metric(within25, "%") }}</strong><small>good intonation</small></article>
      <article><span>WITHIN ±50¢</span><strong>{{ metric(within50, "%") }}</strong><small>within half a semitone</small></article>
      <article><span>STABLE-NOTE MAE</span><strong>{{ metric(stableError, "¢") }}</strong><small>{{ summary?.stable_note_region_count ?? 0 }} regions · {{ (summary?.stable_note_total_seconds ?? 0).toFixed(1) }}s</small></article>
    </div>

    <div class="alignment-strip"><span>ALIGNMENT</span><strong>Take {{ metric((artifact.alignment?.global_offset_seconds ?? 0) * 1000, " ms") }} relative to reference</strong><i></i><small>{{ ((artifact.alignment?.global_offset_confidence ?? 0) * 100).toFixed(1) }}% confidence · {{ artifact.alignment?.global_offset_method }}</small></div>

    <section class="feature-panel charts-panel">
      <div class="charts-heading"><div><p class="mono-eyebrow accent-text">ALIGNED CONTOURS</p><h2>Pitch movement</h2></div><div class="layer-pills"><button :class="{ active: showReference }" @click="showReference = !showReference">REFERENCE</button><button :class="{ active: showPerformance }" @click="showPerformance = !showPerformance">MINE</button><button :class="{ active: showWaveforms }" @click="showWaveforms = !showWaveforms">VOCAL WAVEFORMS</button><button :class="{ active: showPoints }" @click="showPoints = !showPoints">POINTS</button></div></div>
      <div class="chart-well"><div ref="pitchPlot"></div></div>
      <div class="diagnostic-grid"><div class="chart-well"><p>PITCH CONFIDENCE · THRESHOLD {{ ((artifact.configuration?.pitch_confidence_threshold ?? .55) * 100).toFixed(0) }}%</p><div ref="confidencePlot"></div></div><div class="chart-well"><p>PITCH DIFFERENCE · BAND ±25¢</p><div ref="errorPlot"></div></div></div>
    </section>

    <section class="feature-panel listening-gate">
      <div class="listening-header">
        <div><p class="mono-eyebrow accent-text">LISTENING GATE</p><h2>Compare the same phrase</h2></div>
        <div class="listening-range">FROM <input v-model.number="selectionStart" type="number" step=".1" /> / TO <input v-model.number="selectionEnd" type="number" step=".1" /> / LOOP {{ looping ? "ON" : "OFF" }}
          <button type="button" class="reset-zoom" @click="resetZoom">FULL VIEW</button>
        </div>
      </div>
      <PitchHeatmapBand
        :frames="artifact.comparison.frames"
        :mode="comparisonMode"
        :selection-start="selectionStart"
        :selection-end="selectionEnd"
        @select="selectPhrase"
      />
      <div class="transport-row"><button :class="{ active: activePlayer === 'reference' }" @click="play('reference')">▶ REFERENCE VOCAL</button><button :class="{ active: activePlayer === 'mix' }" @click="play('mix')">▶ ORIGINAL MIX</button><button :class="{ active: activePlayer === 'take' }" @click="play('take')">▶ MY TAKE</button><button @click="playAB">A / B</button><button :class="{ active: looping }" @click="looping = !looping">LOOP</button><button @click="stopAudio">■ STOP</button></div>
      <audio ref="referenceAudio" preload="metadata" :src="`/api/projects/${project.id}/audio/vocal?transpose=${take.reference_transpose_semitones ?? 0}`"></audio>
      <audio ref="mixAudio" preload="metadata" :src="`/api/projects/${project.id}/audio/mix?transpose=${take.reference_transpose_semitones ?? 0}`"></audio>
      <audio ref="takeAudio" preload="metadata" :src="`/api/projects/${project.id}/takes/${take.id}/audio/vocal`"></audio>
    </section>
  </section>
</template>

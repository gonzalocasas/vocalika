<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from "vue"

import type { LivePitchSample } from "./useLivePitch"
import {
  accuracyBand,
  midiToY,
  referenceMidiAt,
  sliceContour,
  timeToX,
  verticalRange,
  type ReferenceContour,
} from "./pitchRibbon"

const props = defineProps<{
  contour: ReferenceContour | null
  samples: LivePitchSample[]
  current: LivePitchSample | null
  /** Current position in the reference, in seconds. */
  time: number
  active: boolean
}>()

/**
 * Seconds of reference shown behind and ahead of the playhead. Ahead matters
 * most: seeing the next note approach is what lets a singer prepare for it
 * rather than only learn afterwards that they missed.
 */
const SECONDS_BEHIND = 1.5
const SECONDS_AHEAD = 2.5

const canvas = ref<HTMLCanvasElement | null>(null)
let frame: number | undefined

const BAND_COLORS: Record<string, string> = {
  excellent: "#3ddc97",
  good: "#f2c14e",
  off: "#ef5d60",
  unknown: "#6b7280",
}

function draw(): void {
  const element = canvas.value
  if (!element) return
  const context = element.getContext("2d")
  if (!context) return

  const ratio = window.devicePixelRatio || 1
  const width = element.clientWidth
  const height = element.clientHeight
  if (element.width !== width * ratio || element.height !== height * ratio) {
    element.width = width * ratio
    element.height = height * ratio
  }
  context.setTransform(ratio, 0, 0, ratio, 0, 0)
  context.clearRect(0, 0, width, height)

  const start = props.time - SECONDS_BEHIND
  const end = props.time + SECONDS_AHEAD
  const reference = props.contour ? sliceContour(props.contour, start, end) : []
  const visibleLive = props.samples.filter((s) => s.time >= start && s.time <= end)
  const { low, high } = verticalRange([
    ...reference.map((point) => point.midi),
    ...visibleLive.map((sample) => sample.midi),
  ])

  // Semitone gridlines give the eye a fixed scale to judge distance against.
  context.strokeStyle = "rgba(255,255,255,0.06)"
  context.lineWidth = 1
  for (let midi = Math.ceil(low); midi <= Math.floor(high); midi += 1) {
    const y = midiToY(midi, low, high, height)
    context.beginPath()
    context.moveTo(0, y)
    context.lineTo(width, y)
    context.stroke()
  }

  // Reference contour, broken at rests so silence is visible as silence.
  context.strokeStyle = "rgba(148,163,184,0.85)"
  context.lineWidth = 3
  context.lineJoin = "round"
  context.lineCap = "round"
  context.beginPath()
  let drawing = false
  for (const point of reference) {
    if (point.midi === null) {
      drawing = false
      continue
    }
    const x = timeToX(point.time, start, end, width)
    const y = midiToY(point.midi, low, high, height)
    if (drawing) context.lineTo(x, y)
    else context.moveTo(x, y)
    drawing = true
  }
  context.stroke()

  // Sung trail, coloured per sample by how far it sat from the reference.
  for (let index = 1; index < visibleLive.length; index += 1) {
    const previous = visibleLive[index - 1]
    const sample = visibleLive[index]
    if (previous.midi === null || sample.midi === null) continue
    const target = props.contour ? referenceMidiAt(props.contour, sample.time) : null
    const cents = target === null ? null : (sample.midi - target) * 100
    context.strokeStyle = BAND_COLORS[accuracyBand(cents)]
    context.lineWidth = 2.5
    context.globalAlpha = 0.35 + 0.65 * (index / visibleLive.length)
    context.beginPath()
    context.moveTo(
      timeToX(previous.time, start, end, width),
      midiToY(previous.midi, low, high, height),
    )
    context.lineTo(timeToX(sample.time, start, end, width), midiToY(sample.midi, low, high, height))
    context.stroke()
  }
  context.globalAlpha = 1

  // Playhead.
  const playheadX = timeToX(props.time, start, end, width)
  context.strokeStyle = "rgba(255,255,255,0.35)"
  context.lineWidth = 1
  context.beginPath()
  context.moveTo(playheadX, 0)
  context.lineTo(playheadX, height)
  context.stroke()

  // The note being sung right now, on the playhead.
  if (props.current?.midi != null) {
    const target = props.contour ? referenceMidiAt(props.contour, props.current.time) : null
    const cents = target === null ? null : (props.current.midi - target) * 100
    context.fillStyle = BAND_COLORS[accuracyBand(cents)]
    context.beginPath()
    context.arc(playheadX, midiToY(props.current.midi, low, high, height), 6, 0, Math.PI * 2)
    context.fill()
  }
}

function loop(): void {
  draw()
  frame = window.requestAnimationFrame(loop)
}

onMounted(() => {
  loop()
})
onBeforeUnmount(() => {
  if (frame !== undefined) window.cancelAnimationFrame(frame)
})
watch(() => props.active, draw)
</script>

<template>
  <div class="pitch-ribbon">
    <canvas ref="canvas"></canvas>
    <p v-if="!contour" class="ribbon-note">Reference contour unavailable — recording still works.</p>
  </div>
</template>

<style scoped>
.pitch-ribbon {
  position: relative;
  width: 100%;
  height: 180px;
  border-radius: 10px;
  background: rgba(10, 12, 18, 0.55);
  overflow: hidden;
}
.pitch-ribbon canvas {
  width: 100%;
  height: 100%;
  display: block;
}
.ribbon-note {
  position: absolute;
  inset: auto 0 8px 0;
  text-align: center;
  font-size: 12px;
  opacity: 0.6;
  margin: 0;
}
</style>

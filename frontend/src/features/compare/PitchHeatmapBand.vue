<script setup lang="ts">
import { computed } from "vue"

import { buildHeatmap, worstCells, type HeatmapCell, type HeatmapFrames } from "./pitchHeatmap"

const props = defineProps<{
  frames: HeatmapFrames
  mode: "absolute" | "relative"
  selectionStart: number
  selectionEnd: number
}>()
const emit = defineEmits<{ select: [start: number, end: number] }>()

const cells = computed(() => buildHeatmap(props.frames, { mode: props.mode }))
const worst = computed(() => new Set(worstCells(cells.value).map((cell) => cell.start)))
const total = computed(() => {
  const list = cells.value
  if (list.length === 0) return 1
  return Math.max(0.001, list[list.length - 1].end - list[0].start)
})

const BAND_LABEL: Record<string, string> = {
  excellent: "on pitch",
  good: "close",
  noticeable: "noticeably off",
  off: "well off",
  missing: "not sung",
}

function isSelected(cell: HeatmapCell): boolean {
  // Highlight any cell the current listening range overlaps, so the band and
  // the transport controls always agree about what is being worked on.
  return cell.start < props.selectionEnd && cell.end > props.selectionStart
}

function describe(cell: HeatmapCell): string {
  const when = `${cell.start.toFixed(1)}–${cell.end.toFixed(1)}s`
  if (cell.band === "missing") {
    return `${when} · not sung (${Math.round(cell.coverage * 100)}% covered)`
  }
  const cents = Math.round(cell.centerCents ?? 0)
  const direction = cents > 0 ? "sharp" : cents < 0 ? "flat" : "centred"
  const spread =
    cell.spreadCents !== null && cell.spreadCents > 30
      ? ` · wandering ±${Math.round(cell.spreadCents)}c`
      : ""
  return `${when} · ${Math.abs(cents)}c ${direction}${spread} · click to loop`
}
</script>

<template>
  <div v-if="cells.length" class="heatmap-band">
    <div class="heatmap-header">
      <span class="mono-eyebrow">WHERE TO PRACTISE</span>
      <span class="heatmap-legend">
        <i class="band-excellent"></i>on pitch
        <i class="band-good"></i>close
        <i class="band-noticeable"></i>off
        <i class="band-off"></i>well off
        <i class="band-missing"></i>not sung
      </span>
    </div>
    <div class="heatmap-cells">
      <button
        v-for="cell in cells"
        :key="cell.start"
        type="button"
        class="heatmap-cell"
        :class="[
          `band-${cell.band}`,
          { selected: isSelected(cell), worst: worst.has(cell.start) },
        ]"
        :style="{ flexGrow: (cell.end - cell.start) / total }"
        :title="describe(cell)"
        @click="emit('select', cell.start, cell.end)"
      >
        <span v-if="worst.has(cell.start)" class="worst-dot"></span>
      </button>
    </div>
    <p class="heatmap-note">
      Colour is how far the phrase sat from the reference on average, so vibrato
      and passing scoops are not counted as errors. Dots mark the phrases worth
      practising first. Click any phrase to set the listening range.
    </p>
  </div>
</template>

<style scoped>
.heatmap-band {
  margin: 18px 0 6px;
}
.heatmap-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  margin-bottom: 7px;
  flex-wrap: wrap;
}
.heatmap-legend {
  display: flex;
  align-items: center;
  gap: 6px;
  font: 500 9px "IBM Plex Mono", monospace;
  letter-spacing: 0.08em;
  color: #7c817f;
}
.heatmap-legend i {
  width: 9px;
  height: 9px;
  border-radius: 2px;
  margin-left: 6px;
}
.heatmap-cells {
  display: flex;
  gap: 2px;
  height: 34px;
}
.heatmap-cell {
  position: relative;
  flex-basis: 0;
  min-width: 3px;
  border: 0;
  border-radius: 3px;
  padding: 0;
  cursor: pointer;
  opacity: 0.72;
  transition: opacity 0.15s, transform 0.15s;
}
.heatmap-cell:hover {
  opacity: 1;
  transform: translateY(-2px);
}
.heatmap-cell.selected {
  opacity: 1;
  box-shadow: inset 0 0 0 2px #e8e2d6;
}
.worst-dot {
  position: absolute;
  left: 50%;
  top: 50%;
  width: 5px;
  height: 5px;
  margin: -2.5px 0 0 -2.5px;
  border-radius: 50%;
  background: #0e1112;
}
/* Four discrete steps rather than a gradient: a continuous ramp reads as
   decoration, while distinct steps read as instruction. */
.band-excellent { background: #3ddc97; }
.band-good { background: #8fd14f; }
.band-noticeable { background: #f2c14e; }
.band-off { background: #ef5d60; }
.band-missing {
  background: repeating-linear-gradient(
    45deg, #2a2f31, #2a2f31 4px, #33383a 4px, #33383a 8px
  );
}
.heatmap-note {
  margin: 8px 0 0;
  font-size: 11px;
  line-height: 1.5;
  color: #7c817f;
}
</style>

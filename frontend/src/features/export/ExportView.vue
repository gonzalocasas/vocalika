<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue"

import type { Project } from "../../shared/types"
import ProjectWaveform from "../projects/ProjectWaveform.vue"
import TakeWaveform from "../takes/TakeWaveform.vue"

const props = defineProps<{ project: Project; selectedTakeId: string | null }>()
const emit = defineEmits<{ select: [takeId: string] }>()

const takeId = ref(props.selectedTakeId ?? props.project.takes.at(-1)?.id ?? "")
const instrumentalDb = ref(-4)
const outputFormat = ref<"mp3" | "wav" | "flac">("mp3")
const busy = ref<"preview" | "render" | null>(null)
const error = ref("")
const previewUrl = ref("")
const previewAudio = ref<HTMLAudioElement | null>(null)
const selectedTake = computed(() => props.project.takes.find((take) => take.id === takeId.value) ?? null)
const trimDuration = computed(() => (
  (props.project.trim_end_seconds ?? props.project.reference.duration_seconds)
  - props.project.trim_start_seconds
))

watch(() => props.selectedTakeId, (value) => {
  if (value) takeId.value = value
})
watch(takeId, (value) => {
  if (value) emit("select", value)
  clearPreview()
}, { immediate: true })

function clearPreview(): void {
  previewAudio.value?.pause()
  if (previewUrl.value) window.URL.revokeObjectURL(previewUrl.value)
  previewUrl.value = ""
}

async function requestExport(preview: boolean): Promise<void> {
  if (!takeId.value) return
  busy.value = preview ? "preview" : "render"
  error.value = ""
  try {
    const response = await fetch(
      `/api/projects/${props.project.id}/exports${preview ? "/preview" : ""}`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          take_id: takeId.value,
          instrumental_db: instrumentalDb.value,
          output_format: outputFormat.value,
        }),
      },
    )
    if (!response.ok) {
      const payload = await response.json().catch(() => ({})) as { detail?: string }
      throw new Error(payload.detail ?? `Export failed (${response.status})`)
    }
    const blob = await response.blob()
    const url = window.URL.createObjectURL(blob)
    if (preview) {
      clearPreview()
      previewUrl.value = url
      await new Promise<void>((resolve) => window.setTimeout(resolve, 0))
      await previewAudio.value?.play()
    } else {
      const disposition = response.headers.get("content-disposition") ?? ""
      const encoded = disposition.match(/filename\*=utf-8''([^;]+)/i)?.[1]
      const plain = disposition.match(/filename="?([^";]+)"?/i)?.[1]
      const filename = encoded ? decodeURIComponent(encoded) : plain ?? `vocalika-mix.${outputFormat.value}`
      const link = document.createElement("a")
      link.href = url
      link.download = filename
      link.click()
      window.setTimeout(() => window.URL.revokeObjectURL(url), 1_000)
    }
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    busy.value = null
  }
}

onBeforeUnmount(clearPreview)
</script>

<template>
  <section class="export-layout">
    <div class="feature-panel mixdown-panel">
      <div class="feature-heading">
        <div><p class="mono-eyebrow accent-text">MIXDOWN</p><h2>Your vocal over the instrumental</h2></div>
        <span class="export-duration">{{ trimDuration.toFixed(1) }} SEC</span>
      </div>

      <label class="export-select">
        <span>TAKE</span>
        <select v-model="takeId">
          <option v-for="take in project.takes" :key="take.id" :value="take.id">
            {{ take.name }} · {{ take.status }}
          </option>
        </select>
      </label>

      <div v-if="selectedTake" class="export-tracks">
        <article class="export-track active">
          <div><span>MY VOCAL</span><strong>{{ selectedTake.name }}</strong></div>
          <TakeWaveform :key="selectedTake.id" :project-id="project.id" :take-id="selectedTake.id" active />
          <b>0 dB</b>
        </article>
        <article class="export-track">
          <div><span>INSTRUMENTAL</span><strong>Reference accompaniment</strong></div>
          <ProjectWaveform :project-id="project.id" kind="instrumental" />
          <b>{{ instrumentalDb > 0 ? "+" : "" }}{{ instrumentalDb }} dB</b>
        </article>
        <article class="export-track muted">
          <div><span>REFERENCE VOICE</span><strong>Not included in export</strong></div>
          <ProjectWaveform :project-id="project.id" kind="vocal" />
          <b>OFF</b>
        </article>
      </div>

      <label class="export-level">
        <span>INSTRUMENTAL LEVEL <b>{{ instrumentalDb > 0 ? "+" : "" }}{{ instrumentalDb }} dB</b></span>
        <input v-model.number="instrumentalDb" type="range" min="-24" max="6" step="1" />
      </label>

      <audio v-if="previewUrl" ref="previewAudio" class="export-preview" controls :src="previewUrl"></audio>
      <p v-if="error" class="inline-error">{{ error }}</p>
      <div class="export-actions">
        <button class="solid-button" :disabled="!selectedTake || !project.reference.instrumental_path || busy !== null" @click="requestExport(true)">
          {{ busy === "preview" ? "PREPARING…" : "▶ PREVIEW 20 SEC" }}
        </button>
        <button class="accent-button" :disabled="!selectedTake || !project.reference.instrumental_path || busy !== null" @click="requestExport(false)">
          {{ busy === "render" ? "RENDERING…" : "RENDER & DOWNLOAD →" }}
        </button>
      </div>
    </div>

    <aside class="feature-sidebar">
      <section class="feature-panel compact-panel">
        <p class="mono-eyebrow">OUTPUT FORMAT</p>
        <div class="format-grid">
          <button v-for="format in (['mp3', 'wav', 'flac'] as const)" :key="format" :class="{ active: outputFormat === format }" @click="outputFormat = format">{{ format.toUpperCase() }}</button>
        </div>
        <p class="export-note">MP3 is convenient for sharing. WAV and FLAC preserve full quality.</p>
      </section>
      <section class="feature-panel compact-panel status-card">
        <p class="mono-eyebrow">EXPORT READINESS</p>
        <div><span>TAKE</span><b>{{ selectedTake ? "READY" : "MISSING" }}</b></div>
        <div><span>INSTRUMENTAL</span><b>{{ project.reference.instrumental_path ? "READY" : "MISSING" }}</b></div>
        <div><span>ALIGNMENT</span><b>{{ selectedTake?.analysis_path ? "ANALYZED" : "BASIC" }}</b></div>
        <p>Alignment places your vocal on the reference timeline. Natural timing is preserved without audible time-stretching.</p>
      </section>
    </aside>
  </section>
</template>

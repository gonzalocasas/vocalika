<script setup lang="ts">
import { ref } from "vue"

import RecordingStudio from "../recording/RecordingStudio.vue"
import type { Project, Take } from "../../shared/types"
import TakeWaveform from "./TakeWaveform.vue"

const props = defineProps<{ project: Project; busy: boolean; selectedTakeId: string | null }>()
const emit = defineEmits<{
  submit: [file: File, isolate: boolean, recordingOffset?: number]
  select: [take: Take]
  delete: [take: Take]
  reanalyze: [take: Take]
  updateLyrics: [lyrics: string]
}>()

const file = ref<File | null>(null)
const isolate = ref(false)
const studioOpen = ref(false)

function chooseFile(event: Event): void {
  file.value = (event.target as HTMLInputElement).files?.[0] ?? null
}

function submitUpload(): void {
  if (file.value) emit("submit", file.value, isolate.value)
}

function takeDate(value: string): string {
  return new Intl.DateTimeFormat(undefined, { day: "2-digit", month: "short" })
    .format(new Date(value)).toUpperCase()
}

/** Analysed against a melody voice other than the one now chosen. */
function voiceChanged(take: Take): boolean {
  return take.status === "analyzed" && (take.reference_voice ?? "louder") !== props.project.reference_voice
}

function requestDelete(take: Take): void {
  if (window.confirm(`Delete “${take.name}”? This cannot be undone.`)) {
    emit("delete", take)
  }
}
</script>

<template>
  <div class="takes-layout">
    <section class="take-list">
      <div class="section-intro"><p class="mono-eyebrow accent-text">TAKES / {{ String(project.takes.length).padStart(2, "0") }}</p><h2>Your recordings</h2></div>
      <article
        v-for="(take, index) in [...project.takes].reverse()"
        :key="take.id"
        class="take-row"
        :class="{ selected: selectedTakeId === take.id }"
      >
        <button
          class="take-select"
          :disabled="take.status !== 'analyzed'"
          @click="emit('select', take)"
        >
          <div class="take-copy">
            <span class="mono-muted">{{ String(project.takes.length - index).padStart(2, "0") }} · {{ takeDate(take.created_at) }}</span>
            <strong>{{ take.name }}</strong>
            <small><b>{{ take.status.toUpperCase() }}</b> · {{ take.isolate_performance ? "vocal isolation" : "direct vocal" }} · {{ (take.reference_transpose_semitones ?? 0) >= 0 ? "+" : "" }}{{ take.reference_transpose_semitones ?? 0 }} semi<template v-if="take.status === 'analyzed'"> · {{ take.reference_voice ?? "louder" }} voice</template></small>
          </div>
          <TakeWaveform :project-id="project.id" :take-id="take.id" :active="selectedTakeId === take.id" />
          <div class="take-mae"><span>MAE</span><strong>{{ take.analysis_summary ? `${take.analysis_summary.mean_absolute_error_cents.toFixed(0)}¢` : "—" }}</strong></div>
        </button>
        <div class="take-actions">
          <button
            v-if="project.reference.vocal_path"
            class="take-reanalyze"
            :class="{ stale: voiceChanged(take) }"
            :disabled="busy"
            :title="voiceChanged(take)
              ? `Analysed against the ${take.reference_voice ?? 'louder'} voice; the song now follows the ${project.reference_voice}`
              : 'Analyse again with the current settings'"
            :aria-label="`Re-analyze ${take.name}`"
            @click="emit('reanalyze', take)"
          >
            RE-ANALYZE
          </button>
          <button
            class="take-delete"
            :disabled="busy"
            :aria-label="`Delete ${take.name}`"
            @click="requestDelete(take)"
          >
            DELETE
          </button>
        </div>
      </article>
      <p v-if="!project.takes.length" class="empty-copy">Upload or record your first take. It will stay grouped with this reference.</p>
    </section>

    <aside class="take-tools">
      <p v-if="!project.reference.vocal_path" class="feature-note">Instrumental backing track: takes are saved without pitch comparison.</p>
      <section class="add-take-panel">
        <p class="mono-eyebrow accent-text">ADD A TAKE</p>
        <label class="drop-target compact-drop">
          <span>{{ file?.name || "DROP AUDIO" }}</span>
          <small>FLAC from Ableton preferred</small>
          <input type="file" accept="audio/*" @change="chooseFile" />
        </label>
        <label v-if="project.reference.vocal_path" class="check-row"><input v-model="isolate" type="checkbox" /> Isolate my vocal from instruments first</label>
        <button class="solid-button full" :disabled="!file || busy" @click="submitUpload">
          {{ busy ? "SAVING…" : project.reference.vocal_path ? "ANALYZE TAKE" : "SAVE TAKE" }}
        </button>
      </section>
      <section class="add-take-panel record-launcher">
        <p class="mono-eyebrow accent-text">RECORD A TAKE</p>
        <p class="feature-note">Sing along with the reference and watch your pitch as you go.</p>
        <button class="record-button" @click="studioOpen = true">● OPEN RECORDING STUDIO</button>
      </section>
    </aside>

    <RecordingStudio
      v-if="studioOpen"
      :project="project"
      :busy="busy"
      @submit="(recording, shouldIsolate, offset) => emit('submit', recording, shouldIsolate, offset)"
      @update-lyrics="(lyrics) => emit('updateLyrics', lyrics)"
      @close="studioOpen = false"
    />
  </div>
</template>

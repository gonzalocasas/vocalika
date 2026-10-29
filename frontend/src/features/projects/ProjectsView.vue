<script setup lang="ts">
import { computed, ref } from "vue"

import type { Project } from "../../shared/types"
import ProjectWaveform from "./ProjectWaveform.vue"
import type { NewProjectInput } from "./useProjects"

const props = defineProps<{ projects: Project[]; busy: boolean }>()
const emit = defineEmits<{
  open: [project: Project]
  create: [input: NewProjectInput]
}>()

const sourceMode = ref<"file" | "url">("file")
const title = ref("")
const referenceFile = ref<File | null>(null)
const referenceUrl = ref("")
const referenceKind = ref<"mix" | "vocal" | "instrumental">("mix")
const canCreate = computed(() => sourceMode.value === "file"
  ? referenceFile.value !== null
  : referenceUrl.value.trim().length > 0)

function chooseFile(event: Event): void {
  referenceFile.value = (event.target as HTMLInputElement).files?.[0] ?? null
}

function submit(): void {
  if (!canCreate.value) return
  emit("create", {
    title: title.value,
    referenceFile: sourceMode.value === "file" ? referenceFile.value : null,
    referenceUrl: sourceMode.value === "url" ? referenceUrl.value : "",
    referenceKind: referenceKind.value,
  })
}

function bestMae(project: Project): string {
  const values = project.takes
    .map((take) => take.analysis_summary?.mean_absolute_error_cents)
    .filter((value): value is number => value !== undefined)
  return values.length ? `${Math.round(Math.min(...values))}¢` : "—"
}
</script>

<template>
  <section class="projects-view">
    <div class="projects-hero">
      <div>
        <p class="mono-eyebrow accent-text">PROJECTS / {{ String(projects.length).padStart(2, "0") }}</p>
        <h1>Reference<br />library</h1>
        <p>A project holds one reference song and every take you sing against it.</p>
      </div>
      <button class="solid-button" @click="($refs.creator as HTMLElement)?.scrollIntoView({ behavior: 'smooth' })">
        + NEW PROJECT
      </button>
    </div>

    <div v-if="projects.length" class="project-list">
      <button
        v-for="(project, index) in projects"
        :key="project.id"
        class="project-row"
        @click="emit('open', project)"
      >
        <div class="project-copy">
          <span class="mono-muted">{{ String(index + 1).padStart(2, "0") }}</span>
          <strong>{{ project.title }}</strong>
          <small>{{ project.reference.source_url || project.reference.title }}</small>
        </div>
        <ProjectWaveform :project-id="project.id" />
        <div class="project-stat"><span>TAKES</span><strong>{{ String(project.takes.length).padStart(2, "0") }}</strong></div>
        <div class="project-stat"><span>BEST MAE</span><strong class="accent-text">{{ bestMae(project) }}</strong></div>
      </button>
    </div>
    <p v-else class="empty-copy">No projects yet. Prepare a reference to start your workspace.</p>

    <section ref="creator" class="project-creator">
      <div>
        <p class="mono-eyebrow accent-text">START A PROJECT</p>
        <h2>Prepare a reference</h2>
        <p>Choose what your audio contains. Mixes are separated; existing stems are imported directly.</p>
      </div>
      <div class="creator-form">
        <div class="segmented graphite-segmented">
          <button :class="{ active: sourceMode === 'file' }" @click="sourceMode = 'file'">LOCAL FILE</button>
          <button :class="{ active: sourceMode === 'url' }" @click="sourceMode = 'url'">YOUTUBE URL</button>
        </div>
        <input v-model="title" class="graphite-input" placeholder="Project title (optional)" />
        <label v-if="sourceMode === 'file'" class="drop-target">
          <span>{{ referenceFile?.name || "DROP A REFERENCE MIX" }}</span>
          <small>MP3 · WAV · FLAC · OPUS</small>
          <input type="file" accept="audio/*" @change="chooseFile" />
        </label>
        <input
          v-else
          v-model="referenceUrl"
          class="graphite-input"
          type="url"
          placeholder="https://www.youtube.com/watch?v=…"
        />
        <fieldset class="reference-kind">
          <legend class="range-label">AUDIO CONTENT</legend>
          <div class="reference-kind-toggle">
            <label v-for="option in [
              { value: 'mix', label: 'MIX' },
              { value: 'vocal', label: 'VOCALS ONLY' },
              { value: 'instrumental', label: 'INSTRUMENTAL' },
            ]" :key="option.value">
              <input v-model="referenceKind" type="radio" name="reference-kind" :value="option.value" />
              <span>{{ option.label }}</span>
            </label>
          </div>
        </fieldset>
        <p class="feature-note">
          {{ referenceKind === 'mix'
            ? 'Vocals and instruments together. We’ll separate them into reusable stems.'
            : referenceKind === 'vocal'
            ? 'An isolated voice. Ready to use for vocal pitch comparison.'
            : 'A backing track for recording. Pitch comparison requires a vocal reference.' }}
        </p>
        <button class="accent-button" :disabled="!canCreate || busy" @click="submit">
          {{ busy ? "PREPARING…" : "PREPARE →" }}
        </button>
      </div>
    </section>
  </section>
</template>

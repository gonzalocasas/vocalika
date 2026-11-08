<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue"

import type { Project } from "../../shared/types"
import ProjectWaveform from "./ProjectWaveform.vue"
import { searchProjects } from "./projectSearch"
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
const query = ref("")
const searchInput = ref<HTMLInputElement | null>(null)
const matches = computed(() => searchProjects(props.projects, query.value))
const searching = computed(() => query.value.trim().length > 0)
const count = (value: number) => String(value).padStart(2, "0")

function clearSearch(): void {
  query.value = ""
  searchInput.value?.focus()
}

// "/" jumps to the search field from anywhere on the screen, unless the
// singer is already typing somewhere.
function focusSearch(event: KeyboardEvent): void {
  if (event.key !== "/" || event.metaKey || event.ctrlKey || event.altKey) return
  const target = event.target as HTMLElement | null
  if (target?.closest("input, textarea, select, [contenteditable='true']")) return
  if (!searchInput.value) return
  event.preventDefault()
  searchInput.value.focus()
}

onMounted(() => window.addEventListener("keydown", focusSearch))
onBeforeUnmount(() => window.removeEventListener("keydown", focusSearch))

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
        <p class="mono-eyebrow accent-text">
          PROJECTS / {{ searching ? `${count(matches.length)} OF ${count(projects.length)}` : count(projects.length) }}
        </p>
        <h1>Your<br />songs</h1>
        <p>A project holds one reference song and every take you sing against it.</p>
      </div>
      <div class="projects-actions">
        <div v-if="projects.length" class="project-search">
          <input
            ref="searchInput"
            v-model="query"
            class="graphite-input"
            type="search"
            placeholder="Search songs and lyrics"
            aria-label="Search projects"
            @keydown.esc="query = ''"
          />
          <kbd v-if="!searching" aria-hidden="true">/</kbd>
        </div>
        <button class="solid-button" @click="($refs.creator as HTMLElement)?.scrollIntoView({ behavior: 'smooth' })">
          + NEW PROJECT
        </button>
      </div>
    </div>

    <div v-if="matches.length" class="project-list">
      <button
        v-for="{ project, index, lyricsOnly } in matches"
        :key="project.id"
        class="project-row"
        @click="emit('open', project)"
      >
        <div class="project-copy">
          <span class="mono-muted">{{ count(index + 1) }}</span>
          <strong>{{ project.title }}</strong>
          <small>
            <span v-if="lyricsOnly" class="search-hit">IN THE LYRICS · </span>{{ project.reference.source_url || project.reference.title }}
          </small>
        </div>
        <ProjectWaveform :project-id="project.id" />
        <div class="project-stat"><span>TAKES</span><strong>{{ String(project.takes.length).padStart(2, "0") }}</strong></div>
        <div class="project-stat"><span>BEST MAE</span><strong class="accent-text">{{ bestMae(project) }}</strong></div>
      </button>
    </div>
    <p v-else-if="searching" class="empty-copy">
      Nothing matches “{{ query.trim() }}”.
      <button class="text-button" @click="clearSearch">Clear the search</button>
    </p>
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

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue"

import { apiJson } from "./shared/api"
import { transposedRange, type VocalRange } from "./shared/notes"

import CompareView from "./features/compare/CompareView.vue"
import ExportView from "./features/export/ExportView.vue"
import PracticeView from "./features/practice/PracticeView.vue"
import ProjectsView from "./features/projects/ProjectsView.vue"
import type { NewProjectInput } from "./features/projects/useProjects"
import { useProjects } from "./features/projects/useProjects"
import ReferenceView from "./features/reference/ReferenceView.vue"
import { appRoutePath, parseAppRoute } from "./routes"
import type { AppRoute, ProjectTab } from "./routes"
import TakesView from "./features/takes/TakesView.vue"
import type { AnalysisArtifact, Project, Take } from "./shared/types"

const {
  projects,
  busy,
  loaded,
  error,
  createProject,
  updateProject,
  addTake,
  deleteTake,
  loadAnalysis,
} = useProjects()
const initialRoute = parseAppRoute(window.location.pathname)
const selectedProjectId = ref<string | null>(initialRoute.projectId)
const activeTab = ref<ProjectTab>(initialRoute.tab)
const selectedTakeId = ref<string | null>(initialRoute.takeId)
const artifact = ref<AnalysisArtifact | null>(null)
let artifactRequest = 0
if (window.location.pathname !== appRoutePath(initialRoute)) {
  window.history.replaceState({}, "", appRoutePath(initialRoute))
}

const selectedProject = computed(() =>
  projects.value.find((project) => project.id === selectedProjectId.value) ?? null,
)
const selectedTake = computed(() => selectedProject.value?.takes.find(
  (take) => take.id === selectedTakeId.value,
) ?? null)
const bestMae = computed(() => {
  const values = selectedProject.value?.takes.flatMap((take) =>
    take.analysis_summary ? [take.analysis_summary.mean_absolute_error_cents] : [],
  ) ?? []
  return values.length ? `${Math.min(...values).toFixed(0)}¢` : "—"
})

function currentRoute(): AppRoute {
  return {
    projectId: selectedProjectId.value,
    tab: activeTab.value,
    takeId: selectedTakeId.value,
  }
}

function writeRoute(replace = false): void {
  const path = appRoutePath(currentRoute())
  if (window.location.pathname === path) return
  window.history[replace ? "replaceState" : "pushState"]({}, "", path)
}

function applyRoute(route: AppRoute): void {
  artifactRequest += 1
  artifact.value = null
  selectedProjectId.value = route.projectId
  activeTab.value = route.tab
  selectedTakeId.value = route.takeId
}

function openProject(project: Project): void {
  selectedProjectId.value = project.id
  selectedTakeId.value = [...project.takes].reverse().find(
    (take) => take.status === "analyzed",
  )?.id ?? null
  artifact.value = null
  activeTab.value = "reference"
  writeRoute()
}

function closeProject(): void {
  applyRoute({ projectId: null, tab: "reference", takeId: null })
  writeRoute()
}

async function handleCreate(input: NewProjectInput): Promise<void> {
  try {
    openProject(await createProject(input))
  } catch {
    // useProjects exposes the user-facing error.
  }
}

const referenceRange = ref<VocalRange | null>(null)

/**
 * The reference's range, measured once in its original key.
 *
 * Transposition shifts it arithmetically, so the control can be dragged
 * without re-measuring -- which would mean rendering transposed audio and
 * running pyin again for every semitone.
 */
async function loadReferenceRange(): Promise<void> {
  referenceRange.value = null
  const project = selectedProject.value
  if (!project) return
  try {
    const payload = await apiJson<{ range: VocalRange | null }>(
      `/api/projects/${project.id}/reference/pitch`,
    )
    referenceRange.value = payload.range
  } catch {
    // The range is informational; the rest of the screen works without it.
    referenceRange.value = null
  }
}

const sungRange = computed(() =>
  transposedRange(referenceRange.value, selectedProject.value?.transpose_semitones ?? 0),
)

const renamingProject = ref(false)
const renameDraft = ref("")
const renameInput = ref<HTMLInputElement | null>(null)

function beginRename(): void {
  if (!selectedProject.value) return
  renameDraft.value = selectedProject.value.title
  renamingProject.value = true
  // The field is created by this same change, so focus has to wait for it.
  void nextTick(() => {
    renameInput.value?.focus()
    renameInput.value?.select()
  })
}

async function commitRename(): Promise<void> {
  if (!renamingProject.value) return
  renamingProject.value = false
  const next = renameDraft.value.trim()
  // An unchanged or emptied name is a no-op rather than a write; the server
  // also refuses a blank title, but there is no reason to ask it.
  if (!next || next === selectedProject.value?.title) return
  await handleUpdate({ title: next })
}

async function handleUpdate(
  settings: Partial<Pick<Project, "title" | "trim_start_seconds" | "trim_end_seconds" | "transpose_semitones" | "lyrics">>,
): Promise<void> {
  if (selectedProject.value) await updateProject(selectedProject.value.id, settings)
}

async function handleTake(file: File, isolate: boolean): Promise<void> {
  if (!selectedProject.value) return
  try {
    const result = await addTake(selectedProject.value.id, file, isolate, true)
    selectedTakeId.value = result.take.id
    artifact.value = result.artifact
    activeTab.value = "compare"
    writeRoute()
  } catch {
    // useProjects exposes the user-facing error.
  }
}

async function selectTake(take: Take): Promise<void> {
  if (!selectedProject.value || take.status !== "analyzed") return
  selectedTakeId.value = take.id
  artifact.value = null
  activeTab.value = "compare"
  writeRoute()
}

async function handleDeleteTake(take: Take): Promise<void> {
  if (!selectedProject.value) return
  try {
    const project = await deleteTake(selectedProject.value.id, take.id)
    if (selectedTakeId.value === take.id) {
      selectedTakeId.value = [...project.takes].reverse().find(
        (candidate) => candidate.status === "analyzed",
      )?.id ?? null
      artifact.value = null
    }
  } catch {
    // useProjects exposes the user-facing error.
  }
}

async function chooseTab(tab: ProjectTab): Promise<void> {
  activeTab.value = tab
  writeRoute()
}

function openExport(): void {
  activeTab.value = "export"
  writeRoute()
}

function selectExportTake(takeId: string): void {
  selectedTakeId.value = takeId
  artifact.value = null
  writeRoute(true)
}

async function reconcileRoute(): Promise<void> {
  if (!loaded.value) return
  const project = selectedProject.value
  if (!project) {
    if (selectedProjectId.value) {
      applyRoute({ projectId: null, tab: "reference", takeId: null })
      writeRoute(true)
    }
    return
  }

  let take = project.takes.find((candidate) => candidate.id === selectedTakeId.value) ?? null
  if (activeTab.value === "compare" && take?.status !== "analyzed") {
    take = [...project.takes].reverse().find(
      (candidate) => candidate.status === "analyzed",
    ) ?? null
    if (!take) {
      activeTab.value = "takes"
      selectedTakeId.value = null
      artifact.value = null
      writeRoute(true)
      return
    }
    selectedTakeId.value = take.id
    artifact.value = null
    writeRoute(true)
  } else if (activeTab.value === "export" && !take) {
    take = project.takes.at(-1) ?? null
    selectedTakeId.value = take?.id ?? null
    writeRoute(true)
  } else if (!take && (activeTab.value === "reference" || activeTab.value === "takes")) {
    take = [...project.takes].reverse().find(
      (candidate) => candidate.status === "analyzed",
    ) ?? null
    selectedTakeId.value = take?.id ?? null
  }

  if (activeTab.value !== "compare" || take?.status !== "analyzed" || artifact.value) return
  const request = ++artifactRequest
  try {
    const loadedArtifact = await loadAnalysis(project.id, take.id)
    if (request === artifactRequest
      && activeTab.value === "compare"
      && selectedProjectId.value === project.id
      && selectedTakeId.value === take.id) {
      artifact.value = loadedArtifact
    }
  } catch {
    if (request === artifactRequest) artifact.value = null
  }
}

function handlePopState(): void {
  applyRoute(parseAppRoute(window.location.pathname))
}

// Only the identity matters: a rename or a trim change must not re-measure.
watch(() => selectedProjectId.value, () => void loadReferenceRange(), { immediate: true })
watch([loaded, selectedProject, activeTab, selectedTakeId], () => void reconcileRoute(), {
  immediate: true,
})
onMounted(() => window.addEventListener("popstate", handlePopState))
onBeforeUnmount(() => window.removeEventListener("popstate", handlePopState))
</script>

<template>
  <div class="app-shell">
    <header class="top-bar">
      <div><b>V</b><strong>VOCALIKA</strong><span>v0.4 / server workspace</span></div>
      <div><i></i><span>ENGINE READY</span></div>
    </header>

    <main :class="{ 'projects-page': !selectedProject }">
      <div v-if="error" class="app-error"><span>ERROR</span>{{ error }}</div>

      <ProjectsView
        v-if="!selectedProject"
        :projects="projects"
        :busy="busy"
        @open="openProject"
        @create="handleCreate"
      />

      <template v-else>
        <section class="project-header">
          <button class="back-button" @click="closeProject">← ALL PROJECTS</button>
          <div class="project-title-row">
            <div>
              <h1 v-if="!renamingProject" class="editable-title" @click="beginRename">
                {{ selectedProject.title }}<button
                  type="button"
                  class="rename-hint"
                  title="Rename this project"
                  @click.stop="beginRename"
                >EDIT</button>
              </h1>
              <input
                v-else
                ref="renameInput"
                v-model="renameDraft"
                class="title-input"
                type="text"
                :placeholder="selectedProject.title"
                @keydown.enter="commitRename"
                @keydown.esc="renamingProject = false"
                @blur="commitRename"
              />
              <p>
                {{ selectedProject.reference.title }} <i>/</i>
                {{ Math.round(selectedProject.reference.duration_seconds / 60) }} MIN <i>/</i>
                <template v-if="sungRange">
                  <b class="range-badge">{{ sungRange.low_note }}–{{ sungRange.high_note }}</b>
                  <i>/</i>
                </template>
                {{ selectedProject.reference.separation_model ? "STEMS READY" : "VOCAL SOURCE" }}
              </p>
            </div>
            <div class="header-stats">
              <article><span>TAKES</span><strong>{{ String(selectedProject.takes.length).padStart(2, "0") }}</strong></article>
              <article><span>BEST MAE</span><strong>{{ bestMae }}</strong></article>
            </div>
          </div>
          <nav class="project-tabs">
            <button :class="{ active: activeTab === 'reference' }" @click="chooseTab('reference')"><span>01</span> REFERENCE</button>
            <button :class="{ active: activeTab === 'practice' }" @click="chooseTab('practice')"><span>02</span> PRACTICE</button>
            <button :class="{ active: activeTab === 'takes' }" @click="chooseTab('takes')"><span>03</span> TAKES</button>
            <button :disabled="selectedTake?.status !== 'analyzed'" :class="{ active: activeTab === 'compare' }" @click="chooseTab('compare')"><span>04</span> COMPARE</button>
            <button :class="{ active: activeTab === 'export' }" @click="chooseTab('export')"><span>05</span> EXPORT</button>
          </nav>
        </section>

        <ReferenceView v-if="activeTab === 'reference'" :project="selectedProject" @update="handleUpdate" />
        <PracticeView v-else-if="activeTab === 'practice'" :project="selectedProject" />
        <TakesView
          v-else-if="activeTab === 'takes'"
          :project="selectedProject"
          :busy="busy"
          :selected-take-id="selectedTakeId"
          @submit="handleTake"
          @select="selectTake"
          @delete="handleDeleteTake"
          @update-lyrics="(lyrics) => handleUpdate({ lyrics })"
        />
        <CompareView
          v-else-if="activeTab === 'compare' && artifact && selectedTake"
          :key="selectedTake.id"
          :project="selectedProject"
          :take="selectedTake"
          :artifact="artifact"
          @export="openExport"
        />
        <ExportView
          v-else-if="activeTab === 'export'"
          :project="selectedProject"
          :selected-take-id="selectedTakeId"
          @select="selectExportTake"
        />
        <section v-else class="empty-copy">Choose an analyzed take to compare.</section>
      </template>
    </main>
  </div>
</template>

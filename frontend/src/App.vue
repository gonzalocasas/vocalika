<script setup lang="ts">
import { computed, ref } from "vue"

import CompareView from "./features/compare/CompareView.vue"
import ExportView from "./features/export/ExportView.vue"
import ProjectsView from "./features/projects/ProjectsView.vue"
import type { NewProjectInput } from "./features/projects/useProjects"
import { useProjects } from "./features/projects/useProjects"
import ReferenceView from "./features/reference/ReferenceView.vue"
import TakesView from "./features/takes/TakesView.vue"
import type { AnalysisArtifact, Project, Take } from "./shared/types"

type ProjectTab = "reference" | "takes" | "compare" | "export"

const {
  projects,
  busy,
  error,
  createProject,
  updateProject,
  addTake,
  deleteTake,
  loadAnalysis,
} = useProjects()
const selectedProjectId = ref<string | null>(null)
const activeTab = ref<ProjectTab>("reference")
const selectedTakeId = ref<string | null>(null)
const artifact = ref<AnalysisArtifact | null>(null)

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

function openProject(project: Project): void {
  selectedProjectId.value = project.id
  selectedTakeId.value = [...project.takes].reverse().find(
    (take) => take.status === "analyzed",
  )?.id ?? null
  artifact.value = null
  activeTab.value = "reference"
}

async function handleCreate(input: NewProjectInput): Promise<void> {
  try {
    openProject(await createProject(input))
  } catch {
    // useProjects exposes the user-facing error.
  }
}

async function handleUpdate(
  settings: Partial<Pick<Project, "trim_start_seconds" | "trim_end_seconds" | "transpose_semitones" | "lyrics">>,
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
  } catch {
    // useProjects exposes the user-facing error.
  }
}

async function selectTake(take: Take): Promise<void> {
  if (!selectedProject.value || take.status !== "analyzed") return
  selectedTakeId.value = take.id
  artifact.value = await loadAnalysis(selectedProject.value.id, take.id)
  activeTab.value = "compare"
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
  if (tab === "compare" && selectedProject.value && selectedTake.value?.status === "analyzed" && !artifact.value) {
    artifact.value = await loadAnalysis(selectedProject.value.id, selectedTake.value.id)
  }
}

function openExport(): void {
  activeTab.value = "export"
}

function selectExportTake(takeId: string): void {
  selectedTakeId.value = takeId
  artifact.value = null
}
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
          <button class="back-button" @click="selectedProjectId = null">← ALL PROJECTS</button>
          <div class="project-title-row">
            <div>
              <h1>{{ selectedProject.title }}</h1>
              <p>
                {{ selectedProject.reference.title }} <i>/</i>
                {{ Math.round(selectedProject.reference.duration_seconds / 60) }} MIN <i>/</i>
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
            <button :class="{ active: activeTab === 'takes' }" @click="chooseTab('takes')"><span>02</span> TAKES</button>
            <button :disabled="selectedTake?.status !== 'analyzed'" :class="{ active: activeTab === 'compare' }" @click="chooseTab('compare')"><span>03</span> COMPARE</button>
            <button :class="{ active: activeTab === 'export' }" @click="chooseTab('export')"><span>04</span> EXPORT</button>
          </nav>
        </section>

        <ReferenceView v-if="activeTab === 'reference'" :project="selectedProject" @update="handleUpdate" />
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

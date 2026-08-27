import { onMounted, ref } from "vue"

import { apiJson } from "../../shared/api"
import type { AnalysisArtifact, Project, Take } from "../../shared/types"

export interface NewProjectInput {
  title: string
  referenceFile: File | null
  referenceUrl: string
  referenceIsVocal: boolean
}

export function useProjects() {
  const projects = ref<Project[]>([])
  const busy = ref(false)
  const loaded = ref(false)
  const error = ref("")

  async function refresh(): Promise<void> {
    const payload = await apiJson<{ projects: Project[] }>("/api/projects")
    projects.value = payload.projects
    loaded.value = true
  }

  async function createProject(input: NewProjectInput): Promise<Project> {
    busy.value = true
    error.value = ""
    try {
      const body = new FormData()
      if (input.title.trim()) body.append("title", input.title.trim())
      body.append("reference_is_vocal", String(input.referenceIsVocal))
      if (input.referenceFile) body.append("reference_file", input.referenceFile)
      else body.append("reference_url", input.referenceUrl.trim())
      const payload = await apiJson<{ project: Project }>("/api/projects", {
        method: "POST",
        body,
      })
      await refresh()
      return payload.project
    } catch (reason) {
      error.value = reason instanceof Error ? reason.message : String(reason)
      throw reason
    } finally {
      busy.value = false
    }
  }

  async function updateProject(
    projectId: string,
    update: Partial<Pick<Project, "trim_start_seconds" | "trim_end_seconds" | "transpose_semitones" | "lyrics">>,
  ): Promise<Project> {
    const payload = await apiJson<{ project: Project }>(`/api/projects/${projectId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(update),
    })
    projects.value = projects.value.map((project) =>
      project.id === projectId ? payload.project : project,
    )
    return payload.project
  }

  async function addTake(
    projectId: string,
    file: File,
    isolatePerformance: boolean,
    analyze = true,
  ): Promise<{ project: Project; take: Take; artifact: AnalysisArtifact | null }> {
    busy.value = true
    error.value = ""
    try {
      const body = new FormData()
      body.append("audio_file", file)
      body.append("name", file.name.replace(/\.[^.]+$/, ""))
      body.append("isolate_performance", String(isolatePerformance))
      body.append("analyze", String(analyze))
      const payload = await apiJson<{
        project: Project
        take: Take
        artifact: AnalysisArtifact | null
      }>(`/api/projects/${projectId}/takes`, { method: "POST", body })
      projects.value = projects.value.map((project) =>
        project.id === projectId ? payload.project : project,
      )
      return payload
    } catch (reason) {
      error.value = reason instanceof Error ? reason.message : String(reason)
      throw reason
    } finally {
      busy.value = false
    }
  }

  async function loadAnalysis(projectId: string, takeId: string): Promise<AnalysisArtifact> {
    const payload = await apiJson<{ artifact: AnalysisArtifact }>(
      `/api/projects/${projectId}/takes/${takeId}/analysis`,
    )
    return payload.artifact
  }

  async function deleteTake(projectId: string, takeId: string): Promise<Project> {
    busy.value = true
    error.value = ""
    try {
      const payload = await apiJson<{ project: Project }>(
        `/api/projects/${projectId}/takes/${takeId}`,
        { method: "DELETE" },
      )
      projects.value = projects.value.map((project) =>
        project.id === projectId ? payload.project : project,
      )
      return payload.project
    } catch (reason) {
      error.value = reason instanceof Error ? reason.message : String(reason)
      throw reason
    } finally {
      busy.value = false
    }
  }

  onMounted(() => void refresh().catch((reason) => {
    error.value = reason instanceof Error ? reason.message : String(reason)
  }))

  return {
    projects,
    busy,
    loaded,
    error,
    refresh,
    createProject,
    updateProject,
    addTake,
    deleteTake,
    loadAnalysis,
  }
}

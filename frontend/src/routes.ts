export type ProjectTab = "reference" | "practice" | "takes" | "compare" | "export"

export interface AppRoute {
  projectId: string | null
  tab: ProjectTab
  takeId: string | null
}

const PROJECT_TABS = new Set<ProjectTab>([
  "reference",
  "practice",
  "takes",
  "compare",
  "export",
])

function decodeSegment(value: string | undefined): string | null {
  if (!value) return null
  try {
    return decodeURIComponent(value)
  } catch {
    return null
  }
}

export function parseAppRoute(pathname: string): AppRoute {
  const segments = pathname.split("/").filter(Boolean)
  if (segments[0] !== "projects") {
    return { projectId: null, tab: "reference", takeId: null }
  }

  const projectId = decodeSegment(segments[1])
  if (!projectId) return { projectId: null, tab: "reference", takeId: null }
  const requestedTab = decodeSegment(segments[2])
  const tab = requestedTab && PROJECT_TABS.has(requestedTab as ProjectTab)
    ? requestedTab as ProjectTab
    : "reference"
  const takeId = tab === "compare" || tab === "export"
    ? decodeSegment(segments[3])
    : null
  return { projectId, tab, takeId }
}

export function appRoutePath(route: AppRoute): string {
  if (!route.projectId) return "/"
  const projectPath = `/projects/${encodeURIComponent(route.projectId)}/${route.tab}`
  if ((route.tab === "compare" || route.tab === "export") && route.takeId) {
    return `${projectPath}/${encodeURIComponent(route.takeId)}`
  }
  return projectPath
}

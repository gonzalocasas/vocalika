import type { Project } from "../../shared/types"

export interface ProjectMatch {
  project: Project
  /** Position in the unfiltered list, so a row keeps its number while searching. */
  index: number
  /** True when only the lyrics matched, which the row should say. */
  lyricsOnly: boolean
}

/** Lower case without accents, so "rasguna" finds "Rasguña". */
export function foldForSearch(text: string): string {
  return text.normalize("NFD").replace(/\p{Diacritic}/gu, "").toLowerCase()
}

function words(query: string): string[] {
  return foldForSearch(query).split(/\s+/).filter(Boolean)
}

function contains(haystack: string, terms: string[]): boolean {
  return terms.every((term) => haystack.includes(term))
}

/**
 * The projects matching every word of ``query``, in their original order.
 *
 * A project matches on its title, its reference's title or URL and its
 * takes' names; failing those, on its lyrics, where a singer often
 * remembers a line before the title.
 */
export function searchProjects(projects: Project[], query: string): ProjectMatch[] {
  const terms = words(query)
  const all = projects.map((project, index) => ({ project, index, lyricsOnly: false }))
  if (!terms.length) return all
  return all.flatMap((match) => {
    const { project } = match
    const described = foldForSearch([
      project.title,
      project.reference.title,
      project.reference.source_url ?? "",
      ...project.takes.map((take) => take.name),
    ].join("\n"))
    if (contains(described, terms)) return [match]
    if (contains(`${described}\n${foldForSearch(project.lyrics ?? "")}`, terms)) {
      return [{ ...match, lyricsOnly: true }]
    }
    return []
  })
}

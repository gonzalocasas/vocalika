/**
 * The release notes shown after an upgrade, read from the bundled CHANGELOG.md.
 *
 * release-please writes one section per version, with commit subjects grouped
 * under "Features", "Bug Fixes" and others. Only features and fixes concern
 * the singer; documentation and the like are left out, and so are the commit
 * links and the conventional-commit scopes ("**desktop:**").
 */

export interface Release {
  version: string
  date: string
  features: string[]
  fixes: string[]
}

const VERSION_HEADING = /^##\s+\[?(\d+\.\d+\.\d+)\]?(?:\([^)]*\))?\s*(?:\(([^)]+)\))?/
const SECTION_HEADING = /^###\s+(.+?)\s*$/

/** One changelog bullet as plain text: no scope, no commit link, capitalized. */
export function cleanEntry(line: string): string {
  const text = line
    .replace(/^\*\s+/, "")
    .replace(/^\*\*[^*]+:\*\*\s*/, "")
    .replace(/\s*\(\[[0-9a-f]{7,}\]\([^)]*\)\)/g, "")
    .replace(/\s*,?\s*closes\s+\[#\d+\]\([^)]*\)/gi, "")
    .trim()
  return text.charAt(0).toUpperCase() + text.slice(1)
}

export function parseChangelog(markdown: string): Release[] {
  const releases: Release[] = []
  let current: Release | null = null
  let section: "features" | "fixes" | null = null
  for (const line of markdown.split(/\r?\n/)) {
    const version = VERSION_HEADING.exec(line)
    if (version) {
      current = { version: version[1], date: version[2] ?? "", features: [], fixes: [] }
      releases.push(current)
      section = null
      continue
    }
    const heading = SECTION_HEADING.exec(line)
    if (heading) {
      const name = heading[1].toLowerCase()
      section = name === "features" ? "features" : name === "bug fixes" ? "fixes" : null
      continue
    }
    if (current && section && line.startsWith("* ")) current[section].push(cleanEntry(line))
  }
  return releases
}

export function compareVersions(first: string, second: string): number {
  const a = first.split(".").map(Number)
  const b = second.split(".").map(Number)
  for (let index = 0; index < 3; index += 1) {
    const difference = (a[index] ?? 0) - (b[index] ?? 0)
    if (difference) return difference
  }
  return 0
}

/**
 * The releases to show after upgrading from `lastSeen` to `current`, newest
 * first, leaving out any with nothing for the singer. Without a `lastSeen`
 * (an install from before the app remembered it) only `current` is shown.
 */
export function releasesSince(releases: Release[], lastSeen: string | null, current: string): Release[] {
  return releases
    .filter((release) =>
      compareVersions(release.version, current) <= 0
      && (lastSeen === null
        ? release.version === current
        : compareVersions(release.version, lastSeen) > 0))
    .filter((release) => release.features.length || release.fixes.length)
    .sort((first, second) => compareVersions(second.version, first.version))
}

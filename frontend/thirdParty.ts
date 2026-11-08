// A Vite plugin that writes third-party.json next to the built page: every
// npm package with code in the bundle, and its license texts, for the About
// page. It asks Rollup which modules it bundled, so build tools and packages
// that were only installed are not listed.
import { existsSync, readdirSync, readFileSync } from "node:fs"
import { dirname, join, sep } from "node:path"
import { fileURLToPath } from "node:url"
import type { Plugin } from "vite"

const licenseFile = /^(licen[cs]e|copying|notice)/i

interface Notice {
  name: string
  version: string
  license: string
  url: string | null
  licenses: { file: string; text: string }[]
}

/** The package folder holding ``file``: the last node_modules/<name> in its path. */
function packageFolder(file: string): string | null {
  const marker = `${sep}node_modules${sep}`
  const at = file.lastIndexOf(marker)
  if (at < 0) return null
  const rest = file.slice(at + marker.length).split(sep)
  const depth = rest[0].startsWith("@") ? 2 : 1
  return file.slice(0, at + marker.length) + rest.slice(0, depth).join(sep)
}

function describe(folder: string): Notice {
  const manifest = JSON.parse(readFileSync(join(folder, "package.json"), "utf8"))
  const repository: string | undefined =
    typeof manifest.repository === "string" ? manifest.repository : manifest.repository?.url
  return {
    name: manifest.name,
    version: manifest.version,
    license: typeof manifest.license === "string" ? manifest.license : "See the license text",
    url: manifest.homepage ?? repository?.replace(/^git\+/, "").replace(/\.git$/, "") ?? null,
    licenses: readdirSync(folder)
      .filter((file) => licenseFile.test(file))
      .sort()
      .map((file) => ({ file, text: readFileSync(join(folder, file), "utf8") })),
  }
}

export function thirdPartyNotices(): Plugin {
  return {
    name: "vocalika-third-party-notices",
    apply: "build",
    generateBundle() {
      const folders = new Set<string>()
      for (const id of this.getModuleIds()) {
        const file = id.replace(/^\0/, "").split("?")[0]
        const folder = packageFolder(file)
        if (folder && existsSync(join(folder, "package.json"))) folders.add(folder)
      }
      // Vite's own module-preload helper is bundled as a virtual module.
      folders.add(join(dirname(fileURLToPath(import.meta.url)), "node_modules", "vite"))
      const packages = [...folders].map(describe).sort((a, b) => a.name.localeCompare(b.name))
      this.emitFile({ type: "asset", fileName: "third-party.json", source: JSON.stringify({ packages }) })
    },
  }
}

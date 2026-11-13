import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import test from "node:test"
import { cleanEntry, compareVersions, parseChangelog, releasesSince } from "../src/features/whatsNew/changelog.ts"

const SAMPLE = `# Changelog

## [0.5.1](https://github.com/x/y/compare/v0.5.0...v0.5.1) (2026-11-08)


### Bug Fixes

* **desktop:** build the Windows installer again ([a807fcc](https://github.com/x/y/commit/a807fcc5f3))

## [0.5.0](https://github.com/x/y/compare/v0.4.1...v0.5.0) (2026-11-08)


### Features

* add an About tab with the version and all open source credits ([ebe744a](https://github.com/x/y/commit/ebe744ae))

## [0.4.2](https://github.com/x/y/compare/v0.4.1...v0.4.2) (2026-11-08)


### Documentation

* **site:** smaller logo ([39af5c0](https://github.com/x/y/commit/39af5c0e))

## 0.4.1 (2026-11-01)


### Features

* **projects:** search the song list ([c37c8d8](https://github.com/x/y/commit/c37c8d80))
`

test("entries lose their scope and commit link", () => {
  assert.equal(
    cleanEntry("* **desktop:** build the Windows installer again ([a807fcc](https://github.com/x/y/commit/a807fcc5f3))"),
    "Build the Windows installer again",
  )
})

test("releases keep only features and fixes", () => {
  const releases = parseChangelog(SAMPLE)
  assert.deepEqual(releases.map((release) => release.version), ["0.5.1", "0.5.0", "0.4.2", "0.4.1"])
  assert.equal(releases[0].date, "2026-11-08")
  assert.deepEqual(releases[0].fixes, ["Build the Windows installer again"])
  assert.deepEqual(releases[2].features, [])
  assert.deepEqual(releases[3].features, ["Search the song list"])
})

test("an upgrade shows every release since the last one seen, newest first", () => {
  const shown = releasesSince(parseChangelog(SAMPLE), "0.4.1", "0.5.1")
  // 0.4.2 only touched the website, so there is nothing to show for it.
  assert.deepEqual(shown.map((release) => release.version), ["0.5.1", "0.5.0"])
})

test("without a remembered version only the current release is shown", () => {
  assert.deepEqual(releasesSince(parseChangelog(SAMPLE), null, "0.5.0").map((r) => r.version), ["0.5.0"])
})

test("nothing is shown when the version has not changed", () => {
  assert.deepEqual(releasesSince(parseChangelog(SAMPLE), "0.5.1", "0.5.1"), [])
})

test("versions compare numerically", () => {
  assert.ok(compareVersions("0.10.0", "0.9.9") > 0)
  assert.equal(compareVersions("1.2.3", "1.2.3"), 0)
})

test("the real changelog parses", () => {
  const releases = parseChangelog(readFileSync(new URL("../../CHANGELOG.md", import.meta.url), "utf8"))
  assert.ok(releases.length > 0)
  assert.ok(releases.every((release) => /^\d+\.\d+\.\d+$/.test(release.version)))
  assert.ok(releases.flatMap((release) => [...release.features, ...release.fixes]).every((entry) => !entry.includes("](")))
})

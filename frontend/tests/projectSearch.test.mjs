import assert from "node:assert/strict"
import test from "node:test"

import { foldForSearch, searchProjects } from "../src/features/projects/projectSearch.ts"

function project(id, title, extra = {}) {
  return {
    id,
    title,
    lyrics: extra.lyrics ?? "",
    reference: { title: extra.reference ?? `${title}.mp3`, source_url: extra.url ?? null },
    takes: (extra.takes ?? []).map((name) => ({ name })),
  }
}

const projects = [
  project("a", "Rasguña las piedras", { lyrics: "Rasguña las piedras\nhasta sangrar" }),
  project("b", "Blackbird", { url: "https://www.youtube.com/watch?v=Man4Xw8Xypo", takes: ["warm-up"] }),
  project("c", "Alfonsina y el mar", { lyrics: "Por la blanda arena que lame el mar" }),
]

const ids = (matches) => matches.map((match) => match.project.id)

test("an empty query lists every project in order", () => {
  assert.deepEqual(ids(searchProjects(projects, "  ")), ["a", "b", "c"])
})

test("matching ignores case and accents, both ways", () => {
  assert.deepEqual(ids(searchProjects(projects, "RASGUNA")), ["a"])
  assert.deepEqual(ids(searchProjects(projects, "rasguña")), ["a"])
  assert.equal(foldForSearch("Canción Ñandú"), "cancion nandu")
})

test("every word must match, in any order and any field", () => {
  assert.deepEqual(ids(searchProjects(projects, "mar alfonsina")), ["c"])
  assert.deepEqual(ids(searchProjects(projects, "blackbird warm")), ["b"])
  assert.deepEqual(ids(searchProjects(projects, "blackbird alfonsina")), [])
})

test("a reference URL and take names are searchable", () => {
  assert.deepEqual(ids(searchProjects(projects, "youtube")), ["b"])
  assert.deepEqual(ids(searchProjects(projects, "warm-up")), ["b"])
})

test("a lyrics-only match is found and flagged; a title match is not flagged", () => {
  const [lyrics] = searchProjects(projects, "blanda arena")
  assert.equal(lyrics.project.id, "c")
  assert.equal(lyrics.lyricsOnly, true)
  const [title] = searchProjects(projects, "piedras")
  assert.equal(title.lyricsOnly, false, "the title matched, so the lyrics are beside the point")
})

test("rows keep their position in the full list", () => {
  const [match] = searchProjects(projects, "alfonsina")
  assert.equal(match.index, 2)
})

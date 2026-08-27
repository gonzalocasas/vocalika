import assert from "node:assert/strict"
import test from "node:test"

import { appRoutePath, parseAppRoute } from "../src/routes.ts"

test("project routes preserve the active tab and selected take", () => {
  assert.deepEqual(parseAppRoute("/projects/project-1/reference"), {
    projectId: "project-1",
    tab: "reference",
    takeId: null,
  })
  assert.deepEqual(parseAppRoute("/projects/project-1/compare/take-2"), {
    projectId: "project-1",
    tab: "compare",
    takeId: "take-2",
  })
  assert.equal(appRoutePath({
    projectId: "project-1",
    tab: "export",
    takeId: "take-2",
  }), "/projects/project-1/export/take-2")
})

test("unknown and malformed routes return to safe defaults", () => {
  assert.deepEqual(parseAppRoute("/somewhere"), {
    projectId: null,
    tab: "reference",
    takeId: null,
  })
  assert.deepEqual(parseAppRoute("/projects/project-1/unknown"), {
    projectId: "project-1",
    tab: "reference",
    takeId: null,
  })
  assert.deepEqual(parseAppRoute("/projects/%E0%A4%A/compare/take-2"), {
    projectId: null,
    tab: "reference",
    takeId: null,
  })
})

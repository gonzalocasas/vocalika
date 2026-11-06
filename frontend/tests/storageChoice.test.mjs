import assert from "node:assert/strict"
import test from "node:test"
import { storageAction } from "../src/features/settings/storageChoice.ts"

const status = (overrides = {}) => ({
  configured: true,
  data_directory: "/data/current",
  project_count: 3,
  suggested_directory: "/data/current",
  can_browse: false,
  ...overrides,
})
const folder = (overrides = {}) => ({ path: "/data/new", exists: false, project_count: 0, problem: null, ...overrides })

test("the folder in use cannot be chosen again", () => {
  const action = storageAction(status(), folder({ path: "/data/current", exists: true, project_count: 3 }), true)
  assert.equal(action.allowed, false)
})

test("a first start keeps an existing library where it is", () => {
  const action = storageAction(
    status({ configured: false }),
    folder({ path: "/data/current", exists: true, project_count: 3 }),
    true,
  )
  assert.deepEqual([action.allowed, action.move, action.offersMove], [true, false, false])
  assert.match(action.note, /3 projects are already here/)
})

test("a new folder offers to bring the projects along", () => {
  const moving = storageAction(status(), folder(), true)
  assert.deepEqual([moving.move, moving.label], [true, "MOVE 3 PROJECTS"])
  assert.match(moving.note, /will create/)
  const switching = storageAction(status(), folder(), false)
  assert.deepEqual([switching.move, switching.label], [false, "USE THIS FOLDER"])
})

test("with nothing to move there is no move choice", () => {
  const action = storageAction(status({ project_count: 0 }), folder({ exists: true }), true)
  assert.deepEqual([action.offersMove, action.move], [false, false])
  assert.match(action.note, /no projects yet/)
})

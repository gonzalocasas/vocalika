import assert from "node:assert/strict"
import test from "node:test"

import { displayContour, rawContour } from "../src/plotData.ts"

test("display contour removes an isolated pitch-estimator spike", () => {
  const displayed = displayContour(
    [0, 0.1, 0.2, 0.3, 0.4],
    [60, 60, 72, 60, 60],
    [true, true, true, true, true],
  )

  assert.deepEqual(displayed, [60, 60, 60, 60, 60])
})

test("display contour bridges only a short unobserved gap", () => {
  assert.deepEqual(
    displayContour([0, 0.1, 0.2], [60, 0, 62], [true, false, true]),
    [60, 61, 62],
  )
  assert.deepEqual(
    displayContour([0, 0.1, 0.2, 0.3], [60, 0, 0, 62], [true, false, false, true]),
    [60, null, null, 62],
  )
})

test("raw contour preserves every valid source frame", () => {
  assert.deepEqual(rawContour([60, 72, 61], [true, false, true]), [60, null, 61])
})

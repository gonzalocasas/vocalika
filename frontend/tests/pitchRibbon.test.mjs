import assert from "node:assert/strict"
import test from "node:test"

import {
  accuracyBand,
  midiToY,
  referenceMidiAt,
  sliceContour,
  timeToX,
  verticalRange,
} from "../src/features/recording/pitchRibbon.ts"

function contour(step = 0.1, values = [60, 62, null, 64, 65, 67]) {
  return { times: values.map((_, index) => index * step), midi: values }
}

test("slices the visible window plus one bracketing point each side", () => {
  // The bracketing points are deliberate: without them the drawn line would
  // stop short of the ribbon's edges instead of running off them.
  const points = sliceContour(contour(), 0.15, 0.35)
  assert.deepEqual(points.map((point) => point.midi), [62, null, 64, 65])
  assert.ok(points[0].time <= 0.15)
  assert.ok(points[points.length - 1].time >= 0.35)
})

test("slicing is inclusive at the edges and clamps out-of-range windows", () => {
  assert.equal(sliceContour(contour(), -5, 5).length, 6)
  assert.deepEqual(sliceContour(contour(), 10, 12), [])
  assert.deepEqual(sliceContour(contour(), 0.3, 0.2), [])
  assert.deepEqual(sliceContour({ times: [], midi: [] }, 0, 1), [])
})

test("reads the reference note at a time, and null where it is silent", () => {
  const c = contour()
  assert.equal(referenceMidiAt(c, 0.0), 60)
  assert.equal(referenceMidiAt(c, 0.31), 64)
  assert.equal(referenceMidiAt(c, 0.2), null, "unvoiced frame must not interpolate")
  assert.equal(referenceMidiAt(c, 99), null, "outside the track")
})

test("vertical range pads and enforces a minimum span", () => {
  // A held note would otherwise collapse the range and exaggerate vibrato.
  const held = verticalRange([60, 60, 60])
  assert.equal(held.high - held.low, 12)
  assert.ok(held.low < 60 && held.high > 60)

  const wide = verticalRange([50, 80])
  assert.equal(wide.low, 48)
  assert.equal(wide.high, 82)
})

test("vertical range ignores nulls and survives an empty window", () => {
  const withNulls = verticalRange([null, 60, null, 62, null])
  assert.ok(withNulls.low < 60 && withNulls.high > 62)
  const empty = verticalRange([null, null])
  assert.ok(empty.high > empty.low)
})

test("accuracy bands follow the analysis tolerances", () => {
  assert.equal(accuracyBand(0), "excellent")
  assert.equal(accuracyBand(-15), "excellent")
  assert.equal(accuracyBand(20), "good")
  assert.equal(accuracyBand(-25), "good")
  assert.equal(accuracyBand(26), "off")
  assert.equal(accuracyBand(null), "unknown")
  assert.equal(accuracyBand(Number.NaN), "unknown")
})

test("higher pitch maps to a smaller y, and time maps left to right", () => {
  assert.equal(midiToY(70, 60, 70, 100), 0)
  assert.equal(midiToY(60, 60, 70, 100), 100)
  assert.equal(midiToY(65, 60, 70, 100), 50)
  assert.equal(midiToY(65, 60, 60, 100), 50, "degenerate range centres")

  assert.equal(timeToX(1, 0, 2, 200), 100)
  assert.equal(timeToX(0, 0, 2, 200), 0)
  assert.equal(timeToX(5, 2, 2, 200), 0, "degenerate window")
})

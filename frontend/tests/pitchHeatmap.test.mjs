import assert from "node:assert/strict"
import test from "node:test"

import { bandFor, buildHeatmap, worstCells } from "../src/features/compare/pitchHeatmap.ts"

/** Build frames at 10 fps from a compact description of each phrase. */
function frames(phrases, { step = 0.1, restFrames = 6 } = {}) {
  const reference_time = []
  const reference_midi = []
  const reference_voiced = []
  const valid = []
  const absolute_error_cents = []
  const relative_error_cents = []
  let time = 0

  phrases.forEach((phrase, phraseIndex) => {
    if (phraseIndex > 0) {
      for (let index = 0; index < restFrames; index += 1) {
        reference_time.push(Number(time.toFixed(4)))
        reference_midi.push(Number.NaN)
        reference_voiced.push(false)
        valid.push(false)
        absolute_error_cents.push(Number.NaN)
        relative_error_cents.push(Number.NaN)
        time += step
      }
    }
    for (let index = 0; index < phrase.frames; index += 1) {
      reference_time.push(Number(time.toFixed(4)))
      reference_midi.push(60)
      reference_voiced.push(true)
      const sung = index < Math.round(phrase.frames * (phrase.coverage ?? 1))
      valid.push(sung)
      const error = Array.isArray(phrase.errors)
        ? phrase.errors[index % phrase.errors.length]
        : phrase.error
      absolute_error_cents.push(sung ? error : Number.NaN)
      relative_error_cents.push(sung ? error - (phrase.bias ?? 0) : Number.NaN)
      time += step
    }
  })
  return {
    reference_time,
    reference_midi,
    reference_voiced,
    valid,
    absolute_error_cents,
    relative_error_cents,
  }
}

test("splits into one cell per phrase, not per time bin", () => {
  const cells = buildHeatmap(frames([
    { frames: 20, error: 5 },
    { frames: 20, error: 60 },
    { frames: 20, error: -30 },
  ]))
  assert.equal(cells.length, 3)
  assert.deepEqual(cells.map((cell) => cell.band), ["excellent", "off", "noticeable"])
})

test("a held note stays one cell", () => {
  const cells = buildHeatmap(frames([{ frames: 120, error: 3 }]))
  assert.equal(cells.length, 1)
  assert.ok(cells[0].end - cells[0].start > 11)
})

test("centres on signed error so vibrato is not punished", () => {
  // A note centred correctly with +-30 cents of vibrato is good singing.
  // Averaging |error| would call it "noticeable"; averaging signed error
  // reports it as centred, with the swing surfaced separately as spread.
  const vibrato = buildHeatmap(frames([{ frames: 40, errors: [30, -30] }]))[0]
  assert.equal(vibrato.band, "excellent")
  assert.ok(Math.abs(vibrato.centerCents) < 1)
  assert.ok(vibrato.spreadCents > 25, `spread was ${vibrato.spreadCents}`)

  // A consistently flat note of the same magnitude is not excused.
  const flat = buildHeatmap(frames([{ frames: 40, error: -30 }]))[0]
  assert.equal(flat.band, "noticeable")
  assert.ok(flat.spreadCents < 1)
})

test("unsung phrases read as missing, not as mistuned", () => {
  const cells = buildHeatmap(frames([
    { frames: 30, error: 4 },
    { frames: 30, error: 4, coverage: 0.1 },
  ]))
  assert.equal(cells[0].band, "excellent")
  assert.equal(cells[1].band, "missing")
  assert.ok(cells[1].coverage < 0.35)
})

test("relative mode removes the singer's global offset", () => {
  const phrases = [{ frames: 30, error: 45, bias: 45 }]
  assert.equal(buildHeatmap(frames(phrases)).at(0).band, "noticeable")
  assert.equal(buildHeatmap(frames(phrases), { mode: "relative" }).at(0).band, "excellent")
})

test("no cell is left as an unreadable sliver", () => {
  // The invariant that matters is the width of what gets drawn, not a
  // particular cell count: a run of two-frame phrases must not become a run
  // of two-frame cells. A merged cell spans the rests it swallowed, so it can
  // exceed the sung time it contains.
  const cells = buildHeatmap(frames([
    { frames: 2, error: 5 },
    { frames: 2, error: 5 },
    { frames: 2, error: 5 },
    { frames: 30, error: 5 },
  ]))
  assert.ok(cells.length >= 1)
  for (const cell of cells) {
    assert.ok(cell.end - cell.start >= 0.6, `cell of ${cell.end - cell.start}s survived`)
  }
})

test("a short leading phrase is folded forward, not left dangling", () => {
  // A leading sliver has no predecessor to absorb it, so it needs folding
  // into what follows.
  const cells = buildHeatmap(frames([
    { frames: 2, error: 5 },
    { frames: 40, error: 5 },
  ]))
  assert.equal(cells.length, 1)
  assert.equal(cells[0].start, 0)
})

test("repeated reference times are counted once", () => {
  // DTW repeats a reference frame when the performance lingers; weighting by
  // those repeats would score a cell by how long the singer took.
  const base = frames([{ frames: 10, error: 0 }])
  const stretched = {
    reference_time: [...base.reference_time, ...base.reference_time.slice(0, 5)],
    reference_midi: [...base.reference_midi, ...base.reference_midi.slice(0, 5)],
    reference_voiced: [...base.reference_voiced, ...base.reference_voiced.slice(0, 5)],
    valid: [...base.valid, ...base.valid.slice(0, 5)],
    absolute_error_cents: [...base.absolute_error_cents, ...Array(5).fill(400)],
    relative_error_cents: [...base.relative_error_cents, ...Array(5).fill(400)],
  }
  const cell = buildHeatmap(stretched).at(0)
  assert.equal(cell.band, "excellent", "duplicate reference times must not re-weight the cell")
})

test("band thresholds follow the analysis tolerances", () => {
  assert.equal(bandFor(0, 1, 0.35), "excellent")
  assert.equal(bandFor(-15, 1, 0.35), "excellent")
  assert.equal(bandFor(25, 1, 0.35), "good")
  assert.equal(bandFor(-50, 1, 0.35), "noticeable")
  assert.equal(bandFor(51, 1, 0.35), "off")
  assert.equal(bandFor(5, 0.1, 0.35), "missing", "low coverage overrides a good score")
  assert.equal(bandFor(null, 1, 0.35), "missing")
})

test("worst cells are ranked by severity weighted by duration", () => {
  // All phrases are comfortably above the merge threshold so the ranking is
  // tested, not the segmentation.
  const cells = buildHeatmap(frames([
    { frames: 10, error: 300 },
    { frames: 80, error: 80 },
    { frames: 30, error: 4 },
  ]))
  const worst = worstCells(cells, 2)
  assert.equal(worst.length, 2)
  // A long 80-cent phrase is worth more practice than a brief 300-cent stumble.
  assert.ok(worst[0].end - worst[0].start > 5, "expected the long phrase first")
  assert.ok(worst[1].end - worst[1].start < 2)
})

test("empty input yields no cells", () => {
  assert.deepEqual(buildHeatmap({
    reference_time: [], reference_midi: [], valid: [],
    absolute_error_cents: [], relative_error_cents: [],
  }), [])
})

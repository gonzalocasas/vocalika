/**
 * A coarse band summarising pitch accuracy across a take.
 *
 * The pitch plot answers "what happened"; this answers "where should I
 * practise", which is a different question and the one a singer acts on.
 *
 * Cells are musical phrases, not fixed time bins. Fixed bins split held notes
 * across cells and produce unreadable striping; phrases are inherently few,
 * inherently meaningful, and can be clicked to loop.
 */

export interface HeatmapFrames {
  reference_time: number[]
  reference_midi: number[]
  reference_voiced?: boolean[]
  valid: boolean[]
  absolute_error_cents: number[]
  relative_error_cents: number[]
}

export type HeatmapBand = "excellent" | "good" | "noticeable" | "off" | "missing"

export interface HeatmapCell {
  start: number
  end: number
  /** Signed mean error: negative is flat, positive is sharp. Null if unsung. */
  centerCents: number | null
  /** Mean deviation about this cell's own centre: vibrato, scoops, wandering. */
  spreadCents: number | null
  /** Fraction of the phrase's reference-voiced frames that were actually sung. */
  coverage: number
  band: HeatmapBand
}

export interface HeatmapOptions {
  /** "absolute" keeps the singer's global offset; "relative" removes it. */
  mode?: "absolute" | "relative"
  /** A silence at least this long ends a phrase. */
  restSeconds?: number
  /** Cells shorter than this are merged into the previous one. */
  minimumCellSeconds?: number
  /** Below this fraction sung, a cell reads as missing rather than mistuned. */
  minimumCoverage?: number
}

// Matches AnalysisConfig's excellent/good/noticeable tolerances, so the band
// cannot disagree with the numbers reported beside it.
export const EXCELLENT_CENTS = 15
export const GOOD_CENTS = 25
export const NOTICEABLE_CENTS = 50

const DEFAULTS: Required<HeatmapOptions> = {
  mode: "absolute",
  restSeconds: 0.35,
  minimumCellSeconds: 0.6,
  minimumCoverage: 0.35,
}

function mean(values: number[]): number {
  return values.reduce((total, value) => total + value, 0) / values.length
}

export function bandFor(centerCents: number | null, coverage: number, minimumCoverage: number): HeatmapBand {
  // "Did not sing" and "sang the wrong note" are different problems with
  // different fixes, so they must not share a colour.
  if (centerCents === null || coverage < minimumCoverage) return "missing"
  const magnitude = Math.abs(centerCents)
  if (magnitude <= EXCELLENT_CENTS) return "excellent"
  if (magnitude <= GOOD_CENTS) return "good"
  if (magnitude <= NOTICEABLE_CENTS) return "noticeable"
  return "off"
}

interface Span {
  from: number
  to: number
}

/** Contiguous reference-voiced runs, split where a rest is long enough. */
function phraseSpans(frames: HeatmapFrames, restSeconds: number): Span[] {
  const { reference_time: times, reference_midi: midi, reference_voiced: voicedFlags } = frames
  const voiced = (index: number): boolean =>
    voicedFlags ? Boolean(voicedFlags[index]) : Number.isFinite(midi[index])

  const spans: Span[] = []
  let from = -1
  let lastVoiced = -1
  for (let index = 0; index < times.length; index += 1) {
    if (!voiced(index)) continue
    if (from === -1) {
      from = index
    } else if (times[index] - times[lastVoiced] >= restSeconds) {
      spans.push({ from, to: lastVoiced })
      from = index
    }
    lastVoiced = index
  }
  if (from !== -1) spans.push({ from, to: lastVoiced })
  return spans
}

/** Merge slivers so the band stays coarse enough to read. */
function mergeShortSpans(spans: Span[], times: number[], minimumSeconds: number): Span[] {
  const duration = (span: Span): number => times[span.to] - times[span.from]
  const merged: Span[] = []
  for (const span of spans) {
    const previous = merged[merged.length - 1]
    if (previous && duration(span) < minimumSeconds) previous.to = span.to
    else merged.push({ ...span })
  }
  // A short *leading* phrase has no predecessor to absorb it, so it would
  // survive as the sliver this pass exists to remove. Fold it forward.
  while (merged.length > 1 && duration(merged[0]) < minimumSeconds) {
    merged[1].from = merged[0].from
    merged.shift()
  }
  return merged
}

export function buildHeatmap(
  frames: HeatmapFrames,
  options: HeatmapOptions = {},
): HeatmapCell[] {
  const { mode, restSeconds, minimumCellSeconds, minimumCoverage } = { ...DEFAULTS, ...options }
  const times = frames.reference_time
  if (!times || times.length === 0) return []

  const errors = mode === "relative" ? frames.relative_error_cents : frames.absolute_error_cents
  const spans = mergeShortSpans(phraseSpans(frames, restSeconds), times, minimumCellSeconds)

  return spans.map(({ from, to }) => {
    // DTW repeats a reference frame whenever the performance lingers on it.
    // Counting those repeats would weight a cell by how long the singer took
    // rather than by how much reference it covers, so each reference time is
    // counted once -- matching how matched_seconds is computed elsewhere.
    const seen = new Set<number>()
    const sung: number[] = []
    let referenceFrames = 0
    for (let index = from; index <= to; index += 1) {
      const time = times[index]
      if (seen.has(time)) continue
      seen.add(time)
      referenceFrames += 1
      if (frames.valid[index] && Number.isFinite(errors[index])) sung.push(errors[index])
    }

    const coverage = referenceFrames === 0 ? 0 : sung.length / referenceFrames
    const centerCents = sung.length > 0 ? mean(sung) : null
    const spreadCents =
      sung.length > 1 && centerCents !== null
        ? mean(sung.map((value) => Math.abs(value - centerCents)))
        : null

    return {
      start: times[from],
      end: times[to],
      centerCents,
      spreadCents,
      coverage,
      band: bandFor(centerCents, coverage, minimumCoverage),
    }
  })
}

/** The cells a singer should practise first: worst, and long enough to matter. */
export function worstCells(cells: HeatmapCell[], count = 3): HeatmapCell[] {
  return cells
    .filter((cell) => cell.band === "off" || cell.band === "noticeable")
    .sort((left, right) => {
      const weight = (cell: HeatmapCell) =>
        Math.abs(cell.centerCents ?? 0) * Math.max(0.25, cell.end - cell.start)
      return weight(right) - weight(left)
    })
    .slice(0, count)
}

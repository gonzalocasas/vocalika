export interface MetricFrames {
  reference_time: number[]
  reference_midi: number[]
  performance_midi: number[]
  valid: boolean[]
}

export interface MetricStableRegion {
  reference_start: number
  reference_end: number
  error_cents: number
}

export interface MetricSummary {
  global_bias_cents: number
  mean_absolute_error_cents: number
  relative_mean_absolute_error_cents: number
  median_absolute_error_cents: number
  relative_median_absolute_error_cents: number
  within_15_percent: number
  within_25_percent: number
  within_50_percent: number
  relative_within_15_percent: number
  relative_within_25_percent: number
  relative_within_50_percent: number
  valid_frame_count: number
  valid_fraction: number
  matched_seconds: number
  stable_note_pitch_center_mae_cents: number | null
  relative_stable_note_pitch_center_mae_cents: number | null
  stable_note_duration_weighted_mae_cents: number | null
  relative_stable_note_duration_weighted_mae_cents: number | null
  stable_note_region_count: number
  stable_note_total_seconds: number
}

function median(values: number[]): number {
  const ordered = [...values].sort((left, right) => left - right)
  const middle = Math.floor(ordered.length / 2)
  return ordered.length % 2 === 0
    ? (ordered[middle - 1] + ordered[middle]) / 2
    : ordered[middle]
}

function mean(values: number[]): number {
  return values.reduce((total, value) => total + value, 0) / values.length
}

function within(values: number[], tolerance: number): number {
  return 100 * values.filter((value) => value <= tolerance).length / values.length
}

export function calculateRangeSummary(
  frames: MetricFrames,
  stableRegions: MetricStableRegion[],
  rangeStart: number,
  rangeEnd: number,
  framesPerSecond = 10,
): MetricSummary | null {
  const start = Math.min(rangeStart, rangeEnd)
  const end = Math.max(rangeStart, rangeEnd)
  const length = Math.min(
    frames.reference_time.length,
    frames.reference_midi.length,
    frames.performance_midi.length,
    frames.valid.length,
  )
  const selectedIndices = Array.from({ length }, (_, index) => index).filter(
    (index) => frames.reference_time[index] >= start && frames.reference_time[index] <= end,
  )
  const validIndices = selectedIndices.filter(
    (index) =>
      frames.valid[index]
      && Number.isFinite(frames.reference_midi[index])
      && Number.isFinite(frames.performance_midi[index]),
  )
  if (validIndices.length === 0) return null

  const signedErrors = validIndices.map(
    (index) => 100 * (frames.performance_midi[index] - frames.reference_midi[index]),
  )
  const bias = median(signedErrors)
  const absoluteErrors = signedErrors.map(Math.abs)
  const relativeErrors = signedErrors.map((value) => Math.abs(value - bias))
  const uniqueReferenceTimes = new Set(
    validIndices.map((index) => frames.reference_time[index].toFixed(9)),
  )

  const selectedStableRegions = stableRegions.flatMap((region) => {
    const overlapStart = Math.max(region.reference_start, start)
    const overlapEnd = Math.min(region.reference_end, end)
    const overlap = Math.max(0, overlapEnd - overlapStart)
    if (overlap <= 0) return []

    const regionIndices = validIndices.filter((index) => {
      const time = frames.reference_time[index]
      return time >= region.reference_start && time < region.reference_end
    })
    if (regionIndices.length === 0) return []

    const referenceByTime = new Map<string, number>()
    for (const index of regionIndices) {
      referenceByTime.set(
        frames.reference_time[index].toFixed(9),
        frames.reference_midi[index],
      )
    }
    const referenceCenter = median([...referenceByTime.values()])
    const performanceCenter = median(
      regionIndices.map((index) => frames.performance_midi[index]),
    )
    return [{ error: 100 * (performanceCenter - referenceCenter), overlap }]
  })
  const stableAbsoluteErrors = selectedStableRegions.map((region) => Math.abs(region.error))
  const stableRelativeErrors = selectedStableRegions.map((region) =>
    Math.abs(region.error - bias),
  )
  const stableSeconds = selectedStableRegions.reduce(
    (total, region) => total + region.overlap,
    0,
  )
  const weightedStableMean = (values: number[]): number | null => stableSeconds > 0
    ? values.reduce(
        (total, value, index) => total + value * selectedStableRegions[index].overlap,
        0,
      ) / stableSeconds
    : null

  return {
    global_bias_cents: bias,
    mean_absolute_error_cents: mean(absoluteErrors),
    relative_mean_absolute_error_cents: mean(relativeErrors),
    median_absolute_error_cents: median(absoluteErrors),
    relative_median_absolute_error_cents: median(relativeErrors),
    within_15_percent: within(absoluteErrors, 15),
    within_25_percent: within(absoluteErrors, 25),
    within_50_percent: within(absoluteErrors, 50),
    relative_within_15_percent: within(relativeErrors, 15),
    relative_within_25_percent: within(relativeErrors, 25),
    relative_within_50_percent: within(relativeErrors, 50),
    valid_frame_count: validIndices.length,
    valid_fraction: validIndices.length / Math.max(1, selectedIndices.length),
    matched_seconds: uniqueReferenceTimes.size / framesPerSecond,
    stable_note_pitch_center_mae_cents: stableAbsoluteErrors.length > 0
      ? mean(stableAbsoluteErrors)
      : null,
    relative_stable_note_pitch_center_mae_cents: stableRelativeErrors.length > 0
      ? mean(stableRelativeErrors)
      : null,
    stable_note_duration_weighted_mae_cents: weightedStableMean(stableAbsoluteErrors),
    relative_stable_note_duration_weighted_mae_cents: weightedStableMean(
      stableRelativeErrors,
    ),
    stable_note_region_count: selectedStableRegions.length,
    stable_note_total_seconds: stableSeconds,
  }
}

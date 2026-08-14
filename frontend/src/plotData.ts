export const DISPLAY_MAX_BRIDGED_GAP_SECONDS = 0.12

function median(values: number[]): number {
  const ordered = [...values].sort((left, right) => left - right)
  const middle = Math.floor(ordered.length / 2)
  return ordered.length % 2 === 0
    ? (ordered[middle - 1] + ordered[middle]) / 2
    : ordered[middle]
}

function typicalFrameStep(times: number[]): number {
  const steps = times
    .slice(1)
    .map((time, index) => time - times[index])
    .filter((step) => Number.isFinite(step) && step > 0)
  return steps.length > 0 ? median(steps) : 0.1
}

/**
 * Prepare an analysis contour for display without changing the source frames.
 *
 * A three-sample median removes isolated estimator spikes. One missing analysis
 * frame may be interpolated when the actual unobserved duration is at most the
 * requested limit; longer unvoiced passages remain explicit gaps.
 */
export function displayContour(
  times: number[],
  values: number[],
  valid: boolean[],
  maximumBridgedGapSeconds = DISPLAY_MAX_BRIDGED_GAP_SECONDS,
): Array<number | null> {
  const length = Math.min(times.length, values.length, valid.length)
  const result: Array<number | null> = Array.from({ length }, () => null)
  if (length === 0) return result

  const frameStep = typicalFrameStep(times.slice(0, length))
  const validIndices = Array.from({ length }, (_, index) => index).filter(
    (index) => valid[index] && Number.isFinite(values[index]),
  )
  if (validIndices.length === 0) return result

  const runs: number[][] = []
  let run: number[] = []
  for (const index of validIndices) {
    const previous = run.at(-1)
    const unobservedDuration =
      previous === undefined ? 0 : Math.max(0, times[index] - times[previous] - frameStep)
    if (previous !== undefined && unobservedDuration > maximumBridgedGapSeconds + 1e-6) {
      runs.push(run)
      run = []
    }
    run.push(index)
  }
  if (run.length > 0) runs.push(run)

  for (const indices of runs) {
    indices.forEach((index, position) => {
      if (position === 0 || position === indices.length - 1) {
        result[index] = values[index]
        return
      }
      result[index] = median([
        values[indices[position - 1]],
        values[index],
        values[indices[position + 1]],
      ])
    })

    for (let position = 1; position < indices.length; position += 1) {
      const left = indices[position - 1]
      const right = indices[position]
      if (right - left <= 1) continue
      const leftValue = result[left]
      const rightValue = result[right]
      if (leftValue === null || rightValue === null) continue
      for (let index = left + 1; index < right; index += 1) {
        const fraction = (times[index] - times[left]) / (times[right] - times[left])
        result[index] = leftValue + fraction * (rightValue - leftValue)
      }
    }
  }
  return result
}

export function rawContour(values: number[], valid: boolean[]): Array<number | null> {
  return values.map((value, index) => (valid[index] && Number.isFinite(value) ? value : null))
}

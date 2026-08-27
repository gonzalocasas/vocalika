interface PlaybackAlignment {
  global_offset_seconds?: number | null
  global_offset_confidence?: number | null
}

function median(values: number[]): number {
  const ordered = [...values].sort((left, right) => left - right)
  const middle = Math.floor(ordered.length / 2)
  return ordered.length % 2 === 0
    ? (ordered[middle - 1] + ordered[middle]) / 2
    : ordered[middle]
}

export function resolvePlaybackOffset(
  alignment: PlaybackAlignment | undefined,
  referenceTimes: number[],
  performanceTimes: number[],
): number {
  const globalOffset = alignment?.global_offset_seconds
  const confidence = alignment?.global_offset_confidence ?? 0
  if (globalOffset !== null && globalOffset !== undefined
    && Number.isFinite(globalOffset) && confidence >= 0.25) {
    return globalOffset
  }

  const differences = referenceTimes.flatMap((referenceTime, index) => {
    const performanceTime = performanceTimes[index]
    return Number.isFinite(referenceTime) && Number.isFinite(performanceTime)
      ? [performanceTime - referenceTime]
      : []
  })
  return differences.length ? median(differences) : 0
}

export function referenceToPerformanceTime(referenceTime: number, offset: number): number {
  return Math.max(0, referenceTime + offset)
}

export function performanceToReferenceTime(performanceTime: number, offset: number): number {
  return Math.max(0, performanceTime - offset)
}

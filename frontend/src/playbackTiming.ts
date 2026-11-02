import type { PlaybackTiming } from "./shared/types"

/** The server owns placement policy; pitch/DTW arrays never move audio. */
export function resolvePlaybackOffset(timing: PlaybackTiming | undefined): number {
  return timing && Number.isFinite(timing.offset_seconds) ? timing.offset_seconds : 0
}

export function referenceToPerformanceTime(referenceTime: number, offset: number): number {
  return Math.max(0, referenceTime + offset)
}

export function performanceToReferenceTime(performanceTime: number, offset: number): number {
  return Math.max(0, performanceTime - offset)
}

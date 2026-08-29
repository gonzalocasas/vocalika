/**
 * Elapsed recording time that survives pauses.
 *
 * A take can be paused, and the paused gap is not in the recording, so the
 * displayed time cannot simply be `now - startedAt`. This accumulates the
 * segments actually recorded. Time is passed in rather than read from
 * `performance.now()` so the behaviour across pauses can be tested.
 */
export interface ElapsedClock {
  start(now: number): void
  pause(now: number): void
  resume(now: number): void
  /** Seconds recorded so far, excluding any paused gaps. */
  read(now: number): number
  running(): boolean
}

export function createElapsedClock(): ElapsedClock {
  let accumulated = 0
  let segmentStart = 0
  let active = false

  return {
    start(now: number): void {
      accumulated = 0
      segmentStart = now
      active = true
    },
    pause(now: number): void {
      if (!active) return
      accumulated += now - segmentStart
      active = false
    },
    resume(now: number): void {
      if (active) return
      segmentStart = now
      active = true
    },
    read(now: number): number {
      return (accumulated + (active ? now - segmentStart : 0)) / 1000
    },
    running(): boolean {
      return active
    },
  }
}

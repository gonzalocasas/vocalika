import changelog from "../../../../CHANGELOG.md?raw"

import { parseChangelog, releasesSince, type Release } from "./changelog"

/** The version this build was released as; release-please bumps it with the changelog. */
export const APP_VERSION = __APP_VERSION__

const LAST_SEEN_KEY = "vocalika.lastSeenVersion"

/** Kept beside the device choices and latencies, in this webview's storage. */
export function lastSeenVersion(): string | null {
  try {
    return window.localStorage.getItem(LAST_SEEN_KEY)
  } catch {
    return null
  }
}

export function markVersionSeen(version = APP_VERSION): void {
  try {
    window.localStorage.setItem(LAST_SEEN_KEY, version)
  } catch {
    // Unavailable storage means the notes may show again next start.
  }
}

export function releasesSinceLastSeen(): Release[] {
  return releasesSince(parseChangelog(changelog), lastSeenVersion(), APP_VERSION)
}

/** The current release on its own, for opening the notes from About. */
export function currentRelease(): Release[] {
  return releasesSince(parseChangelog(changelog), null, APP_VERSION)
}

/**
 * The desktop launcher downloads new releases in the background; this is the
 * page's side of it. In a browser there is no launcher, and nothing happens.
 */

export interface UpdateNotice {
  version: string
}

interface TauriGlobal {
  core: { invoke<T>(command: string, args?: Record<string, unknown>): Promise<T> }
  event: {
    listen<T>(event: string, handler: (event: { payload: T }) => void): Promise<() => void>
  }
}

function tauri(): TauriGlobal | null {
  return (window as unknown as { __TAURI__?: TauriGlobal }).__TAURI__ ?? null
}

/**
 * Call ``onReady`` once an update is downloaded, now or later in this run.
 * Returns a function that stops listening.
 */
export async function watchForUpdate(onReady: (notice: UpdateNotice) => void): Promise<() => void> {
  const api = tauri()
  if (!api) return () => {}
  try {
    // Listen first, then ask: a download finishing in between is not missed.
    const stop = await api.event.listen<UpdateNotice>("update-ready", ({ payload }) => onReady(payload))
    const ready = await api.core.invoke<UpdateNotice | null>("update_ready")
    if (ready) onReady(ready)
    return stop
  } catch {
    // An older launcher without these commands: no updates offered.
    return () => {}
  }
}

/** Install the downloaded update; the app quits and comes back in it. */
export async function installUpdate(): Promise<void> {
  await tauri()?.core.invoke("install_update")
}

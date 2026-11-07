export class ApiError extends Error {}

export async function apiJson<T>(input: RequestInfo | URL, init?: RequestInit): Promise<T> {
  const response = await fetch(input, init)
  const payload = await response.json() as T & { detail?: string }
  if (!response.ok) throw new ApiError(payload.detail ?? `Request failed (${response.status})`)
  return payload
}

let desktopApp: Promise<boolean> | null = null

/** Whether this page runs inside the desktop app (asked once, then remembered). */
export function isDesktopApp(): Promise<boolean> {
  desktopApp ??= apiJson<{ desktop: boolean }>("/api/settings/app")
    .then((status) => status.desktop)
    .catch(() => false)
  return desktopApp
}

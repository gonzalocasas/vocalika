export class ApiError extends Error {}

export async function apiJson<T>(input: RequestInfo | URL, init?: RequestInit): Promise<T> {
  const response = await fetch(input, init)
  const payload = await response.json() as T & { detail?: string }
  if (!response.ok) throw new ApiError(payload.detail ?? `Request failed (${response.status})`)
  return payload
}

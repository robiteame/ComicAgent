export const BACKEND_SERVICE = 'comic-agent'

export function isComicAgentHealthResponse(body: string): boolean {
  let payload: unknown
  try {
    payload = JSON.parse(body)
  } catch {
    return false
  }

  if (typeof payload !== 'object' || payload === null || Array.isArray(payload)) return false

  const health = payload as Record<string, unknown>
  return health.status === 'ok' && health.service === BACKEND_SERVICE
}

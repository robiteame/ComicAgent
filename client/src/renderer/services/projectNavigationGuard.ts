export type ProjectNavigationGuard = (fromProjectId: string, toProjectId: string | null) => Promise<boolean>

const guards = new Set<ProjectNavigationGuard>()
let navigationIntentVersion = 0

/**
 * Monotonically marks an explicit project/navigation intent. Consumers that
 * create a project implicitly (for example, the first script submission) can
 * compare their captured version after an await and discard the result if the
 * user chose another destination meanwhile.
 */
export function beginProjectNavigationIntent(): number {
  navigationIntentVersion += 1
  return navigationIntentVersion
}

export function currentProjectNavigationIntent(): number {
  return navigationIntentVersion
}

export function registerProjectNavigationGuard(guard: ProjectNavigationGuard): () => void {
  guards.add(guard)
  return () => guards.delete(guard)
}

export async function requestProjectNavigation(
  fromProjectId: string | null,
  toProjectId: string | null,
): Promise<boolean> {
  if (!fromProjectId || fromProjectId === toProjectId) return true

  for (const guard of [...guards]) {
    try {
      if (!(await guard(fromProjectId, toProjectId))) return false
    } catch {
      return false
    }
  }
  return true
}

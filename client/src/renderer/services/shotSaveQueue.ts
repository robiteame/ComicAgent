export type PendingChanges = Record<string, unknown>

export interface PendingSaveEntry<T extends PendingChanges = PendingChanges> {
  pending: T
  inFlight: boolean
  failed: boolean
  promise: Promise<boolean> | null
  retired: boolean
}

export function hasPendingChanges(entry: PendingSaveEntry): boolean {
  return Object.keys(entry.pending).length > 0
}

/**
 * Drain every change that existed when this call began, including edits that
 * arrive while an earlier request is in flight. A retired entry never starts
 * another request or restores an old payload.
 */
export async function drainPendingSaves<T extends PendingChanges>(
  entry: PendingSaveEntry<T>,
  save: (changes: T) => Promise<boolean>,
): Promise<boolean> {
  while (!entry.retired) {
    if (entry.promise) {
      const saved = await entry.promise
      if (!saved) return false
      continue
    }

    if (!hasPendingChanges(entry)) return true

    const changes = entry.pending
    entry.pending = {} as T
    entry.inFlight = true
    const operation = (async () => {
      try {
        const saved = await save(changes)
        if (!saved && !entry.retired) {
          entry.pending = { ...changes, ...entry.pending }
          entry.failed = true
        } else if (saved) {
          entry.failed = false
        }
        return saved
      } catch {
        if (!entry.retired) {
          entry.pending = { ...changes, ...entry.pending }
          entry.failed = true
        }
        return false
      } finally {
        entry.inFlight = false
        entry.promise = null
      }
    })()
    entry.promise = operation

    const saved = await operation
    if (!saved) return false
  }

  return false
}

export function retirePendingSave(entry: PendingSaveEntry) {
  entry.retired = true
  entry.pending = {}
}

export async function retirePendingSaveAfterFlush(
  entry: PendingSaveEntry,
  flush: () => Promise<boolean>,
): Promise<boolean> {
  const saved = await flush()
  if (saved) retirePendingSave(entry)
  return saved
}

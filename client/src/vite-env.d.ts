/// <reference types="vite/client" />

interface Window {
  electronAPI?: {
    getLocalAuthToken?: () => string
    getBackendBaseUrl?: () => string
    retryBackend?: () => Promise<{ ok: boolean; detail?: string }>
    quitApp?: () => void
    selectFile?: () => Promise<string | null>
    selectDirectory?: () => Promise<string | null>
  }
}

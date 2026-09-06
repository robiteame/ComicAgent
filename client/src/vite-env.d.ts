/// <reference types="vite/client" />

interface Window {
  electronAPI?: {
    getLocalAuthToken?: () => string
    selectFile?: () => Promise<string | null>
    selectDirectory?: () => Promise<string | null>
  }
}

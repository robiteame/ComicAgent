import { contextBridge, ipcRenderer } from 'electron'

contextBridge.exposeInMainWorld('electronAPI', {
  getLocalAuthToken: () => ipcRenderer.sendSync('get-local-auth-token') as string,
  // The packaged backend listens on a per-launch random port; the main
  // process is the only component that knows it. Empty string in dev mode
  // (the renderer then falls back to the documented 8011 endpoint).
  getBackendBaseUrl: () => ipcRenderer.sendSync('get-backend-base-url') as string,
  retryBackend: () => ipcRenderer.invoke('backend-retry') as Promise<{ ok: boolean; detail?: string }>,
  quitApp: () => ipcRenderer.send('app-quit'),
  selectFile: () => ipcRenderer.invoke('select-file'),
  selectDirectory: () => ipcRenderer.invoke('select-directory'),
})

"use strict";
const electron = require("electron");
electron.contextBridge.exposeInMainWorld("electronAPI", {
  getLocalAuthToken: () => electron.ipcRenderer.sendSync("get-local-auth-token"),
  // The packaged backend listens on a per-launch random port; the main
  // process is the only component that knows it. Empty string in dev mode
  // (the renderer then falls back to the documented 8011 endpoint).
  getBackendBaseUrl: () => electron.ipcRenderer.sendSync("get-backend-base-url"),
  retryBackend: () => electron.ipcRenderer.invoke("backend-retry"),
  quitApp: () => electron.ipcRenderer.send("app-quit"),
  selectFile: () => electron.ipcRenderer.invoke("select-file"),
  selectDirectory: () => electron.ipcRenderer.invoke("select-directory")
});

"use strict";
const electron = require("electron");
electron.contextBridge.exposeInMainWorld("electronAPI", {
  selectFile: () => electron.ipcRenderer.invoke("select-file"),
  selectDirectory: () => electron.ipcRenderer.invoke("select-directory")
});

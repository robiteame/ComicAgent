"use strict";
const electron = require("electron");
const path = require("path");
let mainWindow = null;
electron.app.setName("ComicAgent");
electron.app.setPath("userData", path.join(electron.app.getPath("appData"), "ComicAgent"));
electron.app.commandLine.appendSwitch("disable-http-cache");
electron.app.commandLine.appendSwitch("disable-gpu-shader-disk-cache");
function createWindow() {
  const winOpts = {
    width: 1400,
    height: 900,
    minWidth: 1200,
    minHeight: 800,
    title: "漫剧智能办公台",
    transparent: true,
    backgroundColor: "#00000000",
    autoHideMenuBar: true,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false
    }
  };
  if (process.platform === "win32") {
    winOpts.backgroundMaterial = "acrylic";
  }
  mainWindow = new electron.BrowserWindow(winOpts);
  mainWindow.setMenuBarVisibility(false);
  if (process.env.NODE_ENV === "development" || !electron.app.isPackaged) {
    mainWindow.loadURL("http://127.0.0.1:5173");
  } else {
    mainWindow.loadFile(path.join(__dirname, "../dist/index.html"));
  }
}
electron.app.whenReady().then(() => {
  electron.Menu.setApplicationMenu(null);
  createWindow();
});
electron.app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    electron.app.quit();
  }
});
electron.app.on("activate", () => {
  if (electron.BrowserWindow.getAllWindows().length === 0) {
    createWindow();
  }
});
electron.ipcMain.handle("select-file", async () => {
  const result = await electron.dialog.showOpenDialog(mainWindow, {
    properties: ["openFile"],
    filters: [
      { name: "文本文件", extensions: ["txt"] },
      { name: "Word文档", extensions: ["docx"] },
      { name: "所有文件", extensions: ["*"] }
    ]
  });
  return result.canceled ? null : result.filePaths[0];
});
electron.ipcMain.handle("select-directory", async () => {
  const result = await electron.dialog.showOpenDialog(mainWindow, {
    properties: ["openDirectory"]
  });
  return result.canceled ? null : result.filePaths[0];
});

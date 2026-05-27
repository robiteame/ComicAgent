import { app, BrowserWindow, ipcMain, dialog, Menu } from 'electron'
import path from 'path'

let mainWindow: BrowserWindow | null = null

app.setName('ComicAgent')
app.setPath('userData', path.join(app.getPath('appData'), 'ComicAgent'))
app.commandLine.appendSwitch('disable-http-cache')
app.commandLine.appendSwitch('disable-gpu-shader-disk-cache')

function createWindow() {
  const winOpts: Electron.BrowserWindowConstructorOptions = {
    width: 1400,
    height: 900,
    minWidth: 1200,
    minHeight: 800,
    title: '漫剧智能办公台',
    transparent: true,
    backgroundColor: '#00000000',
    autoHideMenuBar: true,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  }

  if (process.platform === 'win32') {
    // Win11 下启用 acrylic 材质，配合透明窗口形成桌面透视毛玻璃观感。
    ;(winOpts as Electron.BrowserWindowConstructorOptions & { backgroundMaterial?: string }).backgroundMaterial = 'acrylic'
  }

  mainWindow = new BrowserWindow(winOpts)
  mainWindow.setMenuBarVisibility(false)

  if (process.env.NODE_ENV === 'development' || !app.isPackaged) {
    mainWindow.loadURL('http://127.0.0.1:5173')
  } else {
    mainWindow.loadFile(path.join(__dirname, '../dist/index.html'))
  }
}

app.whenReady().then(() => {
  Menu.setApplicationMenu(null)
  createWindow()
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit()
  }
})

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) {
    createWindow()
  }
})

ipcMain.handle('select-file', async () => {
  const result = await dialog.showOpenDialog(mainWindow!, {
    properties: ['openFile'],
    filters: [
      { name: '文本文件', extensions: ['txt'] },
      { name: 'Word文档', extensions: ['docx'] },
      { name: '所有文件', extensions: ['*'] },
    ],
  })
  return result.canceled ? null : result.filePaths[0]
})

ipcMain.handle('select-directory', async () => {
  const result = await dialog.showOpenDialog(mainWindow!, {
    properties: ['openDirectory'],
  })
  return result.canceled ? null : result.filePaths[0]
})

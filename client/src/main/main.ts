import { app, BrowserWindow, ipcMain, dialog, Menu } from 'electron'
import { spawn, type ChildProcess } from 'child_process'
import { existsSync, mkdirSync } from 'fs'
import { randomBytes } from 'crypto'
import http from 'http'
import path from 'path'
import { pathToFileURL } from 'url'
import { isComicAgentHealthResponse } from './backendHealth'

let mainWindow: BrowserWindow | null = null
let backendProcess: ChildProcess | null = null
let shuttingDown = false
const BACKEND_HOST = '127.0.0.1'
// The renderer's API client is built with the same fixed local endpoint. A
// user-provided PORT here would make a packaged app look healthy while the UI
// still talks to 8011, so keep the desktop contract explicit.
const BACKEND_PORT = 8011
const BACKEND_AUTH_TOKEN = app.isPackaged ? randomBytes(32).toString('hex') : ''
const gotSingleInstanceLock = app.requestSingleInstanceLock()
if (!gotSingleInstanceLock) app.quit()

app.setName('ComicAgent')
app.setPath('userData', path.join(app.getPath('appData'), 'ComicAgent'))

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
      sandbox: true,
    },
  }

  if (process.platform === 'win32') {
    // Win11 下启用 acrylic 材质，配合透明窗口形成桌面透视毛玻璃观感。
    ;(winOpts as Electron.BrowserWindowConstructorOptions & { backgroundMaterial?: string }).backgroundMaterial = 'acrylic'
  } else if (process.platform === 'darwin') {
    // macOS（26+）上透明窗口不渲染默认标题栏的红绿灯按钮；hiddenInset 让按钮
    // 以悬浮形式绘制在透明内容之上，玻璃观感与窗口控制两者兼得。
    winOpts.titleBarStyle = 'hiddenInset'
    // CSS backdrop-filter 无法模糊桌面，透明窗口只会直透桌面；under-window
    // vibrancy 提供系统级磨砂，配合渲染层的白色蒙版形成白色玻璃观感。
    winOpts.vibrancy = 'under-window'
    winOpts.visualEffectState = 'active'
  }

  mainWindow = new BrowserWindow(winOpts)
  mainWindow.webContents.setWindowOpenHandler(() => ({ action: 'deny' }))
  const appEntryUrl = pathToFileURL(path.join(__dirname, '../dist/index.html')).toString()
  const isAllowedRendererUrl = (url: string) =>
    url === appEntryUrl || url.startsWith('http://127.0.0.1:5173/')
  const rejectUnexpectedNavigation = (event: Electron.Event, url: string) => {
    const allowed = isAllowedRendererUrl(url)
    if (!allowed) event.preventDefault()
  }
  mainWindow.webContents.on('will-navigate', rejectUnexpectedNavigation)
  mainWindow.webContents.on('will-redirect', rejectUnexpectedNavigation)
  mainWindow.on('closed', () => {
    mainWindow = null
  })
  mainWindow.setMenuBarVisibility(false)

  if (process.env.NODE_ENV === 'development' || !app.isPackaged) {
    mainWindow.loadURL('http://127.0.0.1:5173')
  } else {
    mainWindow.loadFile(path.join(__dirname, '../dist/index.html'))
  }
}

function backendRoot() {
  return app.isPackaged ? path.join(process.resourcesPath, 'server') : path.resolve(__dirname, '../../server')
}

// The installer bundles a relocatable python-build-standalone runtime and a
// static ffmpeg under Resources/ (see client/scripts/build-python-runtime.mjs).
function bundledPythonCandidates(): string[] {
  const pythonDir = path.join(process.resourcesPath, 'python')
  return process.platform === 'win32'
    ? [path.join(pythonDir, 'python.exe')]
    : [path.join(pythonDir, 'bin', 'python3'), path.join(pythonDir, 'bin', 'python')]
}

function bundledBinDir(): string | null {
  const binDir = path.join(process.resourcesPath, 'bin')
  return existsSync(binDir) ? binDir : null
}

function wait(ms: number) {
  return new Promise<void>((resolve) => setTimeout(resolve, ms))
}

function probeEndpoint(
  pathname: string,
  headers: Record<string, string> = {},
  timeoutMs = 1200,
): Promise<{ statusCode: number; body: string } | null> {
  return new Promise((resolve) => {
    let settled = false
    const finish = (result: { statusCode: number; body: string } | null) => {
      if (settled) return
      settled = true
      resolve(result)
    }
    const request = http.get(
      { hostname: BACKEND_HOST, port: BACKEND_PORT, path: pathname, headers },
      (response) => {
        let body = ''
        response.setEncoding('utf8')
        response.on('data', (chunk: string) => {
          body += chunk
          if (body.length > 8192) {
            response.destroy()
            finish(null)
          }
        })
        response.on('end', () => finish({ statusCode: response.statusCode || 0, body }))
        response.on('error', () => finish(null))
      },
    )
    request.setTimeout(timeoutMs, () => {
      request.destroy()
      finish(null)
    })
    request.on('error', () => finish(null))
  })
}

async function probeBackend(timeoutMs = 1200): Promise<boolean> {
  const health = await probeEndpoint('/health', {}, timeoutMs)
  const healthStatusOk = Boolean(health && health.statusCode >= 200 && health.statusCode < 300)
  if (!health || !healthStatusOk || !isComicAgentHealthResponse(health.body)) return false

  // /health is intentionally public. In packaged mode, prove that an
  // existing ComicAgent process accepts this launcher's token before reusing
  // it; otherwise the renderer would start successfully and every protected
  // API/WebSocket request would fail with 401.
  if (app.isPackaged && BACKEND_AUTH_TOKEN) {
    const authenticated = await probeEndpoint(
      '/',
      { 'X-Comic-Agent-Token': BACKEND_AUTH_TOKEN },
      timeoutMs,
    )
    return Boolean(authenticated && authenticated.statusCode >= 200 && authenticated.statusCode < 300)
  }
  return true
}

function spawnBackend(python: string, serverDir: string, env: NodeJS.ProcessEnv): Promise<ChildProcess> {
  return new Promise((resolve, reject) => {
    const child = spawn(python, [path.join(serverDir, 'main.py')], {
      cwd: serverDir,
      env,
      stdio: ['ignore', 'pipe', 'pipe'],
      windowsHide: true,
    })
    const onError = (error: Error) => {
      child.removeListener('spawn', onSpawn)
      reject(error)
    }
    const onSpawn = () => {
      child.removeListener('error', onError)
      resolve(child)
    }
    child.once('error', onError)
    child.once('spawn', onSpawn)
    child.stdout?.on('data', (chunk) => console.log(`[backend] ${String(chunk).trimEnd()}`))
    child.stderr?.on('data', (chunk) => console.error(`[backend] ${String(chunk).trimEnd()}`))
  })
}

async function startBackend() {
  if (!app.isPackaged || (await probeBackend())) return

  const serverDir = backendRoot()
  const entrypoint = path.join(serverDir, 'main.py')
  if (!existsSync(entrypoint)) {
    throw new Error(`未找到后端入口: ${entrypoint}`)
  }

  const userData = app.getPath('userData')
  const dataDir = path.join(userData, 'data')
  const outputDir = path.join(userData, 'output')
  const checkpointDir = path.join(dataDir, 'checkpoints')
  const chromaDir = path.join(dataDir, 'chromadb')
  for (const directory of [dataDir, outputDir, checkpointDir, chromaDir]) {
    mkdirSync(directory, { recursive: true })
  }

  const env: NodeJS.ProcessEnv = {
    ...process.env,
    PYTHONUNBUFFERED: '1',
    // Never inherit a broad bind address from the user's shell. The desktop
    // backend is private to this application and its token is not a LAN auth
    // boundary.
    HOST: BACKEND_HOST,
    PORT: String(BACKEND_PORT),
    DATA_DIR: dataDir,
    OUTPUT_DIR: outputDir,
    DATABASE_URL: `sqlite:///${path.join(dataDir, 'comic_agent.db')}`,
    CHROMADB_PATH: chromaDir,
    CHECKPOINT_PATH: checkpointDir,
    ...(BACKEND_AUTH_TOKEN ? { COMIC_AGENT_LOCAL_TOKEN: BACKEND_AUTH_TOKEN } : {}),
  }
  const configuredPython = process.env.COMIC_AGENT_PYTHON?.trim()
  // Priority: explicit override (debug escape hatch) > bundled runtime >
  // system Python (legacy fallback when the bundle is missing).
  const systemCandidates = process.platform === 'win32'
    ? ['python.exe', 'python']
    : ['python3', 'python']
  const candidates = configuredPython
    ? [configuredPython]
    : app.isPackaged
      ? [...bundledPythonCandidates().filter((candidate) => existsSync(candidate)), ...systemCandidates]
      : systemCandidates

  // Make shutil.which("ffmpeg") inside the server resolve to the bundled
  // static binary instead of requiring a system install.
  const prependToPath = (env: NodeJS.ProcessEnv, dir: string) => {
    env.PATH = `${dir}${path.delimiter}${env.PATH ?? ''}`
  }
  if (app.isPackaged) {
    const binDir = bundledBinDir()
    if (binDir) prependToPath(env, binDir)
  }

  let lastError: Error | undefined
  try {
    for (const candidate of candidates) {
      try {
        console.log(`[backend] 使用解释器: ${candidate}`)
        backendProcess = await spawnBackend(candidate, serverDir, env)
        break
      } catch (error) {
        lastError = error instanceof Error ? error : new Error(String(error))
      }
    }
    if (!backendProcess) {
      throw new Error(`无法启动 Python 后端${lastError ? `: ${lastError.message}` : ''}`)
    }

    const readyUntil = Date.now() + 30_000
    while (Date.now() < readyUntil) {
      if (await probeBackend()) return
      if (backendProcess.exitCode !== null) {
        throw new Error(`后端进程提前退出 (code ${backendProcess.exitCode})`)
      }
      await wait(300)
    }
    throw new Error('后端健康检查超时，请确认已安装 Python 依赖和 FFmpeg')
  } catch (error) {
    // A failed readiness check must not leave a Python process running after
    // the error dialog and window have been shown.
    if (backendProcess && backendProcess.exitCode === null) backendProcess.kill()
    backendProcess = null
    throw error
  }
}

function stopBackend() {
  shuttingDown = true
  if (backendProcess && backendProcess.exitCode === null) {
    backendProcess.kill()
  }
  backendProcess = null
}

ipcMain.on('get-local-auth-token', (event) => {
  event.returnValue = BACKEND_AUTH_TOKEN
})

if (gotSingleInstanceLock) {
  app.on('second-instance', () => {
    if (!mainWindow) return
    if (mainWindow.isMinimized()) mainWindow.restore()
    mainWindow.focus()
  })
}

if (gotSingleInstanceLock) app.whenReady().then(async () => {
  Menu.setApplicationMenu(null)
  if (app.isPackaged) {
    try {
      await startBackend()
    } catch (error) {
      const detail = error instanceof Error ? error.message : String(error)
      const bundledMissing = !existsSync(path.join(process.resourcesPath, 'python'))
      const hint = bundledMissing
        ? '安装包似乎缺少自带的 Python 运行时，已尝试回退到系统 Python。\n可设置 COMIC_AGENT_PYTHON 指向 Python 3.11+ 并确认其已安装全部依赖。'
        : '可设置 COMIC_AGENT_PYTHON 指向 Python 3.11+。'
      dialog.showErrorBox('ComicAgent 后端启动失败', `${detail}\n\n${hint}`)
    }
  }
  createWindow()
})

app.on('before-quit', stopBackend)

app.on('child-process-gone', (_event, details) => {
  if (!shuttingDown && details.type === 'Utility' && details.reason !== 'clean-exit') {
    console.error(`[electron] 子进程异常退出: ${details.reason}`)
  }
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

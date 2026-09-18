"use strict";
const electron = require("electron");
const child_process = require("child_process");
const fs = require("fs");
const crypto = require("crypto");
const http = require("http");
const net = require("net");
const path = require("path");
const url = require("url");
const BACKEND_SERVICE = "comic-agent";
function isComicAgentHealthResponse(body) {
  let payload;
  try {
    payload = JSON.parse(body);
  } catch {
    return false;
  }
  if (typeof payload !== "object" || payload === null || Array.isArray(payload)) return false;
  const health = payload;
  return health.status === "ok" && health.service === BACKEND_SERVICE;
}
function escapeHtml(value) {
  return value.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}
function renderBackendFailurePage(detail, hint) {
  return `<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'">
<title>后端启动失败</title>
<style>
  :root { color-scheme: light; }
  * { box-sizing: border-box; }
  html, body { margin: 0; height: 100%; }
  body {
    display: flex; align-items: center; justify-content: center;
    background: #f5f6f8; color: #1f2329;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
    -webkit-font-smoothing: antialiased;
  }
  .card {
    width: min(560px, calc(100% - 48px));
    background: #fff; border-radius: 12px; padding: 32px 36px;
    box-shadow: 0 8px 28px rgba(15, 23, 42, 0.10);
  }
  .title { display: flex; align-items: center; gap: 10px; font-size: 17px; font-weight: 600; }
  .title .dot {
    width: 10px; height: 10px; border-radius: 50%; background: #e5484d; flex: none;
  }
  .status { margin: 6px 0 0 20px; min-height: 20px; font-size: 13px; color: #0f7b6c; }
  .status.error { color: #e5484d; }
  .detail {
    margin-top: 16px; padding: 12px 14px; border-radius: 8px;
    background: #f6f8fa; border: 1px solid #e5e7eb;
    font: 12px/1.6 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    white-space: pre-wrap; word-break: break-all; max-height: 180px; overflow: auto;
  }
  .hint { margin-top: 12px; font-size: 13px; line-height: 1.7; color: #57606a; }
  .actions { margin-top: 22px; display: flex; gap: 10px; }
  button {
    appearance: none; border: 0; border-radius: 6px; padding: 7px 18px;
    font-size: 13px; cursor: pointer;
  }
  button:disabled { opacity: 0.55; cursor: default; }
  .primary { background: #1677ff; color: #fff; }
  .primary:not(:disabled):hover { background: #3c89ff; }
  .secondary { background: #f0f1f3; color: #1f2329; }
  .secondary:not(:disabled):hover { background: #e2e4e8; }
</style>
</head>
<body>
<div class="card">
  <div class="title"><span class="dot"></span>后端服务启动失败</div>
  <p id="status" class="status">渲染引擎未连接到本地后端，工作台不可用。</p>
  <div id="detail" class="detail">${escapeHtml(detail)}</div>
  <div class="hint">${escapeHtml(hint)}</div>
  <div class="actions">
    <button id="retry" class="primary" type="button">重试启动</button>
    <button id="copy" class="secondary" type="button">复制错误信息</button>
    <button id="quit" class="secondary" type="button">退出</button>
  </div>
</div>
<script>
(function () {
  var status = document.getElementById('status')
  var retry = document.getElementById('retry')
  var copy = document.getElementById('copy')

  function setStatus(text, isError) {
    status.textContent = text
    status.className = isError ? 'status error' : 'status'
  }

  retry.addEventListener('click', function () {
    retry.disabled = true
    copy.disabled = true
    setStatus('正在重新启动后端…', false)
    var api = window.electronAPI
    if (!api || !api.retryBackend) {
      setStatus('当前环境不支持在线重试，请退出后重新打开应用。', true)
      retry.disabled = false
      copy.disabled = false
      return
    }
    api.retryBackend().then(function (result) {
      if (result && result.ok) return // main process swaps in the workbench
      setStatus('重试失败：' + ((result && result.detail) || '未知错误'), true)
      retry.disabled = false
      copy.disabled = false
    }, function (error) {
      setStatus('重试失败：' + error, true)
      retry.disabled = false
      copy.disabled = false
    })
  })

  copy.addEventListener('click', function () {
    var text = document.getElementById('detail').textContent || ''
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text)
    } else {
      var textarea = document.createElement('textarea')
      textarea.value = text
      document.body.appendChild(textarea)
      textarea.select()
      document.execCommand('copy')
      document.body.removeChild(textarea)
    }
  })

  document.getElementById('quit').addEventListener('click', function () {
    var api = window.electronAPI
    if (api && api.quitApp) api.quitApp()
  })
})()
<\/script>
</body>
</html>`;
}
function backendFailurePageUrl(detail, hint) {
  return `data:text/html;charset=utf-8,${encodeURIComponent(renderBackendFailurePage(detail, hint))}`;
}
let mainWindow = null;
let backendProcess = null;
let shuttingDown = false;
let backendStartInFlight = null;
const BACKEND_HOST = "127.0.0.1";
let backendPort = null;
const BACKEND_AUTH_TOKEN = electron.app.isPackaged ? crypto.randomBytes(32).toString("hex") : "";
const gotSingleInstanceLock = electron.app.requestSingleInstanceLock();
if (!gotSingleInstanceLock) electron.app.quit();
electron.app.setName("ComicAgent");
electron.app.setPath("userData", path.join(electron.app.getPath("appData"), "ComicAgent"));
function createWindow(failure) {
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
      nodeIntegration: false,
      sandbox: true
    }
  };
  if (process.platform === "win32") {
    winOpts.backgroundMaterial = "acrylic";
  } else if (process.platform === "darwin") {
    winOpts.titleBarStyle = "hiddenInset";
    winOpts.vibrancy = "under-window";
    winOpts.visualEffectState = "active";
  }
  mainWindow = new electron.BrowserWindow(winOpts);
  mainWindow.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
  const appEntryUrl = url.pathToFileURL(path.join(__dirname, "../dist/index.html")).toString();
  const isAllowedRendererUrl = (url2) => url2 === appEntryUrl || url2.startsWith("http://127.0.0.1:5173/");
  const rejectUnexpectedNavigation = (event, url2) => {
    const allowed = isAllowedRendererUrl(url2);
    if (!allowed) event.preventDefault();
  };
  mainWindow.webContents.on("will-navigate", rejectUnexpectedNavigation);
  mainWindow.webContents.on("will-redirect", rejectUnexpectedNavigation);
  mainWindow.on("closed", () => {
    mainWindow = null;
  });
  mainWindow.setMenuBarVisibility(false);
  if (failure) {
    mainWindow.loadURL(backendFailurePageUrl(failure.detail, failure.hint));
  } else {
    loadAppEntry();
  }
}
function loadAppEntry() {
  if (!mainWindow) return;
  if (process.env.NODE_ENV === "development" || !electron.app.isPackaged) {
    mainWindow.loadURL("http://127.0.0.1:5173");
  } else {
    mainWindow.loadFile(path.join(__dirname, "../dist/index.html"));
  }
}
function backendRoot() {
  return electron.app.isPackaged ? path.join(process.resourcesPath, "server") : path.resolve(__dirname, "../../server");
}
function bundledPythonCandidates() {
  const pythonDir = path.join(process.resourcesPath, "python");
  return process.platform === "win32" ? [path.join(pythonDir, "python.exe")] : [path.join(pythonDir, "bin", "python3"), path.join(pythonDir, "bin", "python")];
}
function bundledBinDir() {
  const binDir = path.join(process.resourcesPath, "bin");
  return fs.existsSync(binDir) ? binDir : null;
}
function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
function probeEndpoint(port, pathname, headers = {}, timeoutMs = 1200) {
  return new Promise((resolve) => {
    let settled = false;
    const finish = (result) => {
      if (settled) return;
      settled = true;
      resolve(result);
    };
    const request = http.get(
      { hostname: BACKEND_HOST, port, path: pathname, headers },
      (response) => {
        let body = "";
        response.setEncoding("utf8");
        response.on("data", (chunk) => {
          body += chunk;
          if (body.length > 8192) {
            response.destroy();
            finish(null);
          }
        });
        response.on("end", () => finish({ statusCode: response.statusCode || 0, body }));
        response.on("error", () => finish(null));
      }
    );
    request.setTimeout(timeoutMs, () => {
      request.destroy();
      finish(null);
    });
    request.on("error", () => finish(null));
  });
}
async function probeBackend(port, timeoutMs = 1200) {
  const health = await probeEndpoint(port, "/health", {}, timeoutMs);
  const healthStatusOk = Boolean(health && health.statusCode >= 200 && health.statusCode < 300);
  if (!health || !healthStatusOk || !isComicAgentHealthResponse(health.body)) return false;
  if (BACKEND_AUTH_TOKEN) {
    const authenticated = await probeEndpoint(
      port,
      "/",
      { "X-Comic-Agent-Token": BACKEND_AUTH_TOKEN },
      timeoutMs
    );
    return Boolean(authenticated && authenticated.statusCode >= 200 && authenticated.statusCode < 300);
  }
  return true;
}
function reserveBackendPort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.unref();
    server.once("error", reject);
    server.listen(0, BACKEND_HOST, () => {
      const address = server.address();
      const port = typeof address === "object" && address !== null ? address.port : null;
      server.close(() => {
        if (port) resolve(port);
        else reject(new Error("无法预留本地后端端口"));
      });
    });
  });
}
function spawnBackend(python, serverDir, env) {
  return new Promise((resolve, reject) => {
    var _a, _b;
    const child = child_process.spawn(python, [path.join(serverDir, "main.py")], {
      cwd: serverDir,
      env,
      // stdin stays open: the server runs a watchdog thread that exits when
      // stdin reaches EOF, so the backend can never outlive a hard crash of
      // the Electron shell (a normal quit already kills it explicitly).
      stdio: ["pipe", "pipe", "pipe"],
      windowsHide: true
    });
    const onError = (error) => {
      child.removeListener("spawn", onSpawn);
      reject(error);
    };
    const onSpawn = () => {
      child.removeListener("error", onError);
      resolve(child);
    };
    child.once("error", onError);
    child.once("spawn", onSpawn);
    (_a = child.stdout) == null ? void 0 : _a.on("data", (chunk) => console.log(`[backend] ${String(chunk).trimEnd()}`));
    (_b = child.stderr) == null ? void 0 : _b.on("data", (chunk) => console.error(`[backend] ${String(chunk).trimEnd()}`));
  });
}
function startBackend() {
  if (backendStartInFlight) return backendStartInFlight;
  backendStartInFlight = startBackendUnchecked().finally(() => {
    backendStartInFlight = null;
  });
  return backendStartInFlight;
}
async function startBackendUnchecked() {
  var _a;
  if (!electron.app.isPackaged) return;
  const serverDir = backendRoot();
  const entrypoint = path.join(serverDir, "main.py");
  if (!fs.existsSync(entrypoint)) {
    throw new Error(`未找到后端入口: ${entrypoint}`);
  }
  const userData = electron.app.getPath("userData");
  const dataDir = path.join(userData, "data");
  const outputDir = path.join(userData, "output");
  const checkpointDir = path.join(dataDir, "checkpoints");
  const chromaDir = path.join(dataDir, "chromadb");
  for (const directory of [dataDir, outputDir, checkpointDir, chromaDir]) {
    fs.mkdirSync(directory, { recursive: true });
  }
  const port = await reserveBackendPort();
  backendPort = port;
  const env = {
    ...process.env,
    PYTHONUNBUFFERED: "1",
    // Never inherit a broad bind address from the user's shell. The desktop
    // backend is private to this application and its token is not a LAN auth
    // boundary.
    HOST: BACKEND_HOST,
    PORT: String(port),
    DATA_DIR: dataDir,
    OUTPUT_DIR: outputDir,
    DATABASE_URL: `sqlite:///${path.join(dataDir, "comic_agent.db")}`,
    CHROMADB_PATH: chromaDir,
    CHECKPOINT_PATH: checkpointDir,
    COMIC_AGENT_PARENT_WATCH: "1",
    ...BACKEND_AUTH_TOKEN ? { COMIC_AGENT_LOCAL_TOKEN: BACKEND_AUTH_TOKEN } : {}
  };
  const configuredPython = (_a = process.env.COMIC_AGENT_PYTHON) == null ? void 0 : _a.trim();
  const systemCandidates = process.platform === "win32" ? ["python.exe", "python"] : ["python3", "python"];
  const candidates = configuredPython ? [configuredPython] : electron.app.isPackaged ? [...bundledPythonCandidates().filter((candidate) => fs.existsSync(candidate)), ...systemCandidates] : systemCandidates;
  const prependToPath = (env2, dir) => {
    env2.PATH = `${dir}${path.delimiter}${env2.PATH ?? ""}`;
  };
  if (electron.app.isPackaged) {
    const binDir = bundledBinDir();
    if (binDir) prependToPath(env, binDir);
  }
  let lastError;
  try {
    for (const candidate of candidates) {
      try {
        console.log(`[backend] 使用解释器: ${candidate}`);
        backendProcess = await spawnBackend(candidate, serverDir, env);
        break;
      } catch (error) {
        lastError = error instanceof Error ? error : new Error(String(error));
      }
    }
    if (!backendProcess) {
      throw new Error(`无法启动 Python 后端${lastError ? `: ${lastError.message}` : ""}`);
    }
    const readyUntil = Date.now() + 3e4;
    while (Date.now() < readyUntil) {
      if (await probeBackend(port)) return;
      if (backendProcess.exitCode !== null) {
        throw new Error(`后端进程提前退出 (code ${backendProcess.exitCode})`);
      }
      await wait(300);
    }
    throw new Error("后端健康检查超时，请确认已安装 Python 依赖和 FFmpeg");
  } catch (error) {
    if (backendProcess && backendProcess.exitCode === null) backendProcess.kill();
    backendProcess = null;
    backendPort = null;
    throw error;
  }
}
function stopBackend() {
  shuttingDown = true;
  if (backendProcess && backendProcess.exitCode === null) {
    backendProcess.kill();
  }
  backendProcess = null;
  backendPort = null;
}
electron.ipcMain.on("get-local-auth-token", (event) => {
  event.returnValue = BACKEND_AUTH_TOKEN;
});
electron.ipcMain.on("get-backend-base-url", (event) => {
  event.returnValue = backendPort ? `http://${BACKEND_HOST}:${backendPort}` : "";
});
electron.ipcMain.on("app-quit", () => {
  electron.app.quit();
});
electron.ipcMain.handle("backend-retry", async () => {
  if (!electron.app.isPackaged) return { ok: true };
  try {
    stopBackend();
    shuttingDown = false;
    await startBackend();
    loadAppEntry();
    return { ok: true };
  } catch (error) {
    return { ok: false, detail: error instanceof Error ? error.message : String(error) };
  }
});
if (gotSingleInstanceLock) {
  electron.app.on("second-instance", () => {
    if (!mainWindow) return;
    if (mainWindow.isMinimized()) mainWindow.restore();
    mainWindow.focus();
  });
}
if (gotSingleInstanceLock) electron.app.whenReady().then(async () => {
  electron.Menu.setApplicationMenu(null);
  let backendFailure;
  if (electron.app.isPackaged) {
    try {
      await startBackend();
    } catch (error) {
      const detail = error instanceof Error ? error.message : String(error);
      const bundledMissing = !fs.existsSync(path.join(process.resourcesPath, "python"));
      backendFailure = {
        detail,
        hint: bundledMissing ? "安装包似乎缺少自带的 Python 运行时，已尝试回退到系统 Python。\n可设置 COMIC_AGENT_PYTHON 指向 Python 3.11+ 并确认其已安装全部依赖，或在故障页点击“重试启动”。" : "可在下方点击“重试启动”，或设置 COMIC_AGENT_PYTHON 指向 Python 3.11+ 后重试。"
      };
    }
  }
  createWindow(backendFailure);
});
electron.app.on("before-quit", stopBackend);
electron.app.on("child-process-gone", (_event, details) => {
  if (!shuttingDown && details.type === "Utility" && details.reason !== "clean-exit") {
    console.error(`[electron] 子进程异常退出: ${details.reason}`);
  }
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

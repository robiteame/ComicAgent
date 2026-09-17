"use strict";const n=require("electron"),j=require("child_process"),m=require("fs"),q=require("crypto"),M=require("http"),H=require("net"),o=require("path"),U=require("url"),R="comic-agent";function $(e){let t;try{t=JSON.parse(e)}catch{return!1}if(typeof t!="object"||t===null||Array.isArray(t))return!1;const r=t;return r.status==="ok"&&r.service===R}function S(e){return e.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;").replace(/'/g,"&#39;")}function F(e,t){return`<!doctype html>
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
  <div id="detail" class="detail">${S(e)}</div>
  <div class="hint">${S(t)}</div>
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
</html>`}function L(e,t){return`data:text/html;charset=utf-8,${encodeURIComponent(F(e,t))}`}let s=null,u=null,C=!1,g=null;const k="127.0.0.1";let b=null;const w=n.app.isPackaged?q.randomBytes(32).toString("hex"):"",E=n.app.requestSingleInstanceLock();E||n.app.quit();n.app.setName("ComicAgent");n.app.setPath("userData",o.join(n.app.getPath("appData"),"ComicAgent"));function _(e){const t={width:1400,height:900,minWidth:1200,minHeight:800,title:"漫剧智能办公台",transparent:!0,backgroundColor:"#00000000",autoHideMenuBar:!0,webPreferences:{preload:o.join(__dirname,"preload.js"),contextIsolation:!0,nodeIntegration:!1,sandbox:!0}};process.platform==="win32"?t.backgroundMaterial="acrylic":process.platform==="darwin"&&(t.titleBarStyle="hiddenInset",t.vibrancy="under-window",t.visualEffectState="active"),s=new n.BrowserWindow(t),s.webContents.setWindowOpenHandler(()=>({action:"deny"}));const r=U.pathToFileURL(o.join(__dirname,"../dist/index.html")).toString(),a=i=>i===r||i.startsWith("http://127.0.0.1:5173/"),c=(i,d)=>{a(d)||i.preventDefault()};s.webContents.on("will-navigate",c),s.webContents.on("will-redirect",c),s.on("closed",()=>{s=null}),s.setMenuBarVisibility(!1),e?s.loadURL(L(e.detail,e.hint)):B()}function B(){s&&(process.env.NODE_ENV==="development"||!n.app.isPackaged?s.loadURL("http://127.0.0.1:5173"):s.loadFile(o.join(__dirname,"../dist/index.html")))}function W(){return n.app.isPackaged?o.join(process.resourcesPath,"server"):o.resolve(__dirname,"../../server")}function z(){const e=o.join(process.resourcesPath,"python");return process.platform==="win32"?[o.join(e,"python.exe")]:[o.join(e,"bin","python3"),o.join(e,"bin","python")]}function K(){const e=o.join(process.resourcesPath,"bin");return m.existsSync(e)?e:null}function G(e){return new Promise(t=>setTimeout(t,e))}function T(e,t,r={},a=1200){return new Promise(c=>{let i=!1;const d=l=>{i||(i=!0,c(l))},f=M.get({hostname:k,port:e,path:t,headers:r},l=>{let y="";l.setEncoding("utf8"),l.on("data",h=>{y+=h,y.length>8192&&(l.destroy(),d(null))}),l.on("end",()=>d({statusCode:l.statusCode||0,body:y})),l.on("error",()=>d(null))});f.setTimeout(a,()=>{f.destroy(),d(null)}),f.on("error",()=>d(null))})}async function V(e,t=1200){const r=await T(e,"/health",{},t),a=!!(r&&r.statusCode>=200&&r.statusCode<300);if(!r||!a||!$(r.body))return!1;if(w){const c=await T(e,"/",{"X-Comic-Agent-Token":w},t);return!!(c&&c.statusCode>=200&&c.statusCode<300)}return!0}function Y(){return new Promise((e,t)=>{const r=H.createServer();r.unref(),r.once("error",t),r.listen(0,k,()=>{const a=r.address(),c=typeof a=="object"&&a!==null?a.port:null;r.close(()=>{c?e(c):t(new Error("无法预留本地后端端口"))})})})}function J(e,t,r){return new Promise((a,c)=>{var l,y;const i=j.spawn(e,[o.join(t,"main.py")],{cwd:t,env:r,stdio:["pipe","pipe","pipe"],windowsHide:!0}),d=h=>{i.removeListener("spawn",f),c(h)},f=()=>{i.removeListener("error",d),a(i)};i.once("error",d),i.once("spawn",f),(l=i.stdout)==null||l.on("data",h=>console.log(`[backend] ${String(h).trimEnd()}`)),(y=i.stderr)==null||y.on("data",h=>console.error(`[backend] ${String(h).trimEnd()}`))})}function D(){return g||(g=X().finally(()=>{g=null}),g)}async function X(){var A;if(!n.app.isPackaged)return;const e=W(),t=o.join(e,"main.py");if(!m.existsSync(t))throw new Error(`未找到后端入口: ${t}`);const r=n.app.getPath("userData"),a=o.join(r,"data"),c=o.join(r,"output"),i=o.join(a,"checkpoints"),d=o.join(a,"chromadb");for(const p of[a,c,i,d])m.mkdirSync(p,{recursive:!0});const f=await Y();b=f;const l={...process.env,PYTHONUNBUFFERED:"1",HOST:k,PORT:String(f),DATA_DIR:a,OUTPUT_DIR:c,DATABASE_URL:`sqlite:///${o.join(a,"comic_agent.db")}`,CHROMADB_PATH:d,CHECKPOINT_PATH:i,COMIC_AGENT_PARENT_WATCH:"1",...w?{COMIC_AGENT_LOCAL_TOKEN:w}:{}},y=(A=process.env.COMIC_AGENT_PYTHON)==null?void 0:A.trim(),h=process.platform==="win32"?["python.exe","python"]:["python3","python"],I=y?[y]:n.app.isPackaged?[...z().filter(p=>m.existsSync(p)),...h]:h,N=(p,x)=>{p.PATH=`${x}${o.delimiter}${p.PATH??""}`};if(n.app.isPackaged){const p=K();p&&N(l,p)}let P;try{for(const x of I)try{console.log(`[backend] 使用解释器: ${x}`),u=await J(x,e,l);break}catch(v){P=v instanceof Error?v:new Error(String(v))}if(!u)throw new Error(`无法启动 Python 后端${P?`: ${P.message}`:""}`);const p=Date.now()+3e4;for(;Date.now()<p;){if(await V(f))return;if(u.exitCode!==null)throw new Error(`后端进程提前退出 (code ${u.exitCode})`);await G(300)}throw new Error("后端健康检查超时，请确认已安装 Python 依赖和 FFmpeg")}catch(p){throw u&&u.exitCode===null&&u.kill(),u=null,b=null,p}}function O(){C=!0,u&&u.exitCode===null&&u.kill(),u=null,b=null}n.ipcMain.on("get-local-auth-token",e=>{e.returnValue=w});n.ipcMain.on("get-backend-base-url",e=>{e.returnValue=b?`http://${k}:${b}`:""});n.ipcMain.on("app-quit",()=>{n.app.quit()});n.ipcMain.handle("backend-retry",async()=>{if(!n.app.isPackaged)return{ok:!0};try{return O(),C=!1,await D(),B(),{ok:!0}}catch(e){return{ok:!1,detail:e instanceof Error?e.message:String(e)}}});E&&n.app.on("second-instance",()=>{s&&(s.isMinimized()&&s.restore(),s.focus())});E&&n.app.whenReady().then(async()=>{n.Menu.setApplicationMenu(null);let e;if(n.app.isPackaged)try{await D()}catch(t){const r=t instanceof Error?t.message:String(t),a=!m.existsSync(o.join(process.resourcesPath,"python"));e={detail:r,hint:a?`安装包似乎缺少自带的 Python 运行时，已尝试回退到系统 Python。
可设置 COMIC_AGENT_PYTHON 指向 Python 3.11+ 并确认其已安装全部依赖，或在故障页点击“重试启动”。`:"可在下方点击“重试启动”，或设置 COMIC_AGENT_PYTHON 指向 Python 3.11+ 后重试。"}}_(e)});n.app.on("before-quit",O);n.app.on("child-process-gone",(e,t)=>{!C&&t.type==="Utility"&&t.reason!=="clean-exit"&&console.error(`[electron] 子进程异常退出: ${t.reason}`)});n.app.on("window-all-closed",()=>{process.platform!=="darwin"&&n.app.quit()});n.app.on("activate",()=>{n.BrowserWindow.getAllWindows().length===0&&_()});n.ipcMain.handle("select-file",async()=>{const e=await n.dialog.showOpenDialog(s,{properties:["openFile"],filters:[{name:"文本文件",extensions:["txt"]},{name:"Word文档",extensions:["docx"]},{name:"所有文件",extensions:["*"]}]});return e.canceled?null:e.filePaths[0]});n.ipcMain.handle("select-directory",async()=>{const e=await n.dialog.showOpenDialog(s,{properties:["openDirectory"]});return e.canceled?null:e.filePaths[0]});

// Renders the document shown in place of the workbench when the packaged
// Python backend fails to start. Pure string templating only — no Electron
// imports — so it stays unit-testable (failurePage.test.mts).

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

export function renderBackendFailurePage(detail: string, hint: string): string {
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
</script>
</body>
</html>`
}

export function backendFailurePageUrl(detail: string, hint: string): string {
  return `data:text/html;charset=utf-8,${encodeURIComponent(renderBackendFailurePage(detail, hint))}`
}

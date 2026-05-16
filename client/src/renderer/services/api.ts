import axios from 'axios'

const API_BASE = 'http://localhost:8000'
const WS_BASE = 'ws://localhost:8000'

const api = axios.create({
  baseURL: API_BASE,
  timeout: 30000,
})

// 项目 API
export const projectApi = {
  create: (data: { title?: string; style?: string; genre?: string }) =>
    api.post('/api/project', data).then((r) => r.data),

  get: (id: string) => api.get(`/api/project/${id}`).then((r) => r.data),

  list: () => api.get('/api/project').then((r) => r.data),

  update: (id: string, data: Record<string, any>) =>
    api.put(`/api/project/${id}`, data).then((r) => r.data),
}

// 脚本 API
export const scriptApi = {
  parse: (data: {
    project_id: string
    user_input: string
    input_type?: string
    style?: string
    output_format?: string
    resolution?: string
    platform?: string
    target_duration?: number
  }) => api.post('/api/script/parse', data).then((r) => r.data),

  upload: (formData: FormData) =>
    api
      .post('/api/script/upload', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      .then((r) => r.data),
}

// 镜头 API
export const shotApi = {
  list: (projectId: string) =>
    api.get(`/api/shot/${projectId}/shots`).then((r) => r.data),

  update: (shotId: string, data: Record<string, any>) =>
    api.put(`/api/shot/${shotId}`, data).then((r) => r.data),

  regenerate: (shotId: string, data?: { reason?: string }) =>
    api.post(`/api/shot/${shotId}/regenerate`, data || {}).then((r) => r.data),

  batchRegenerate: (shotIds: string[], reason?: string) =>
    api
      .post('/api/shot/batch-regenerate', shotIds, { params: { reason } })
      .then((r) => r.data),
}

// 渲染 API
export const renderApi = {
  start: (data: {
    project_id: string
    output_format?: string
    resolution?: string
  }) => api.post('/api/render', data).then((r) => r.data),

  status: (projectId: string) =>
    api.get(`/api/render/${projectId}/status`).then((r) => r.data),
}

// 聊天 API
export const chatApi = {
  send: (data: {
    project_id: string
    message: string
    current_shots?: any[]
  }) => api.post('/api/chat', data).then((r) => r.data),
}

// WebSocket 连接
export function createWebSocket(
  projectId: string,
  onMessage: (data: any) => void
): WebSocket {
  const ws = new WebSocket(`${WS_BASE}/ws/${projectId}`)

  ws.onmessage = (event) => {
    const data = JSON.parse(event.data)
    onMessage(data)
  }

  ws.onerror = (error) => {
    console.error('WebSocket error:', error)
  }

  // 心跳
  const heartbeat = setInterval(() => {
    if (ws.readyState === WebSocket.OPEN) {
      ws.send('ping')
    }
  }, 30000)

  ws.onclose = () => {
    clearInterval(heartbeat)
  }

  return ws
}

export default api

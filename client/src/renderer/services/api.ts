import axios from 'axios'

export const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8011'
export const WS_BASE = API_BASE.replace(/^http/, 'ws')
export const API_OUTPUT_BASE = `${API_BASE}/output/`

const api = axios.create({
  baseURL: API_BASE,
  timeout: 30000,
})

export const projectApi = {
  create: (data: {
    title?: string
    first_episode_title?: string
    parent_project_id?: string
    project_type?: 'series' | 'episode'
    episode_number?: number
    style?: string
    genre?: string
    output_format?: string
    resolution?: string
    platform?: string
  }) => api.post('/api/project', data).then((r) => r.data),

  get: (id: string) => api.get(`/api/project/${id}`).then((r) => r.data),

  list: () => api.get('/api/project').then((r) => r.data),

  episodes: (id: string) => api.get(`/api/project/${id}/episodes`).then((r) => r.data),

  update: (id: string, data: Record<string, any>) => api.put(`/api/project/${id}`, data).then((r) => r.data),

  delete: (id: string) => api.delete(`/api/project/${id}`).then((r) => r.data),

  importVideo: (id: string, formData: FormData) =>
    api
      .post(`/api/project/${id}/import-video`, formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      .then((r) => r.data),
}

export const scriptApi = {
  generate: (data: {
    project_id?: string
    prompt: string
    style?: string
    genre?: string
    target_duration?: number
    characters_hint?: string
  }) => api.post('/api/script/generate', data).then((r) => r.data),

  parse: (data: {
    project_id: string
    user_input: string
    input_type?: string
    style?: string
    output_format?: string
    resolution?: string
    platform?: string
    target_duration?: number
    mode?: 'manual' | 'auto'
  }) => api.post('/api/script/parse', data).then((r) => r.data),

  upload: (formData: FormData) =>
    api
      .post('/api/script/upload', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      .then((r) => r.data),
}

export const shotApi = {
  list: (projectId: string) => api.get(`/api/shot/${projectId}/shots`).then((r) => r.data),

  update: (shotId: string, data: Record<string, any>) => api.put(`/api/shot/${shotId}`, data).then((r) => r.data),

  regenerate: (shotId: string, data?: Record<string, any>) =>
    api.post(`/api/shot/${shotId}/regenerate`, data || {}).then((r) => r.data),

  generationPrompt: (shotId: string) => api.get(`/api/shot/${shotId}/generation-prompt`).then((r) => r.data),

  batchRegenerate: (shotIds: string[], reason?: string) =>
    api.post('/api/shot/batch-regenerate', shotIds, { params: { reason } }).then((r) => r.data),

  generateStoryboard: (projectId: string, shotIds?: string[]) =>
    api.post(`/api/shot/${projectId}/generate-storyboard`, { shot_ids: shotIds || [] }).then((r) => r.data),

  approveStoryboard: (shotId: string, approved = true) =>
    api.post(`/api/shot/${shotId}/approve-storyboard`, { approved }).then((r) => r.data),

  generateVideo: (shotId: string, force = false) =>
    api.post(`/api/shot/${shotId}/generate-video`, { force }).then((r) => r.data),

  confirmStoryboard: (projectId: string) => api.post(`/api/shot/${projectId}/confirm-storyboard`).then((r) => r.data),
}

export const assetApi = {
  board: (projectId: string) => api.get(`/api/asset/${projectId}/board`).then((r) => r.data),

  updateShotAssets: (shotId: string, data: { scene_asset_id?: string; character_asset_ids?: string[] }) =>
    api.put(`/api/asset/shot/${shotId}`, data).then((r) => r.data),

  updateCharacter: (characterId: string, data: Record<string, any>) =>
    api.put(`/api/asset/character/${characterId}`, data).then((r) => r.data),

  updateScene: (sceneId: string, data: Record<string, any>) =>
    api.put(`/api/asset/scene/${sceneId}`, data).then((r) => r.data),
}

export const characterApi = {
  list: (projectId: string) => api.get(`/api/character/${projectId}/characters`).then((r) => r.data),

  update: (characterId: string, data: Record<string, any>) =>
    api.put(`/api/character/${characterId}`, data).then((r) => r.data),
}

export const renderApi = {
  start: (data: { project_id: string; output_format?: string; resolution?: string }) =>
    api.post('/api/render', data).then((r) => r.data),

  status: (projectId: string) => api.get(`/api/render/${projectId}/status`).then((r) => r.data),
}

export const chatApi = {
  send: (data: { project_id: string; message: string; current_shots?: any[] }) =>
    api.post('/api/chat', data).then((r) => r.data),
}

export const settingsApi = {
  styleTemplates: () => api.get('/api/settings/style-templates').then((r) => r.data),

  createStyleTemplate: (data: { label: string; keywords: string; negative_prompt?: string }) =>
    api.post('/api/settings/style-templates', data).then((r) => r.data),

  skillConfigs: () => api.get('/api/settings/skill-configs').then((r) => r.data),

  saveSkillConfig: (data: Record<string, any>) => api.post('/api/settings/skill-configs', data).then((r) => r.data),

  updateSkillBindings: (data: Record<string, any>) => api.put('/api/settings/skill-configs/bindings', data).then((r) => r.data),

  modelConfigs: () => api.get('/api/settings/model-configs').then((r) => r.data),

  saveModelConfigs: (data: Record<string, any>) => api.put('/api/settings/model-configs', data).then((r) => r.data),
}

export function createWebSocket(projectId: string, onMessage: (data: any) => void): WebSocket {
  const ws = new WebSocket(`${WS_BASE}/ws/${projectId}`)

  ws.onmessage = (event) => {
    let parsed: any
    try {
      parsed = JSON.parse(event.data)
    } catch (err) {
      // 后端可能发来非 JSON 文本帧（如纯文本心跳），忽略而非中断消息处理
      console.warn('收到无法解析的 WebSocket 消息，已忽略:', event.data)
      return
    }
    onMessage(parsed)
  }

  ws.onerror = (error) => {
    console.error('WebSocket error:', error)
  }

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

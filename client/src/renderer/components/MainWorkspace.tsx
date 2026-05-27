import React, { useEffect, useMemo, useRef, useState } from 'react'
import { Button, Input, Select, message } from 'antd'
import { BulbOutlined, CheckCircleOutlined, SendOutlined, UploadOutlined } from '@ant-design/icons'
import { useShotStore } from '../stores/shotStore'
import { useProjectStore } from '../stores/projectStore'
import { API_OUTPUT_BASE, createWebSocket, projectApi, scriptApi, shotApi } from '../services/api'

const { TextArea } = Input
const PARSE_SCRIPT_EVENT = 'pipeline:parse-script'
const OPEN_CREATE_PROJECT_EVENT = 'workspace:open-create-project'

const STEP_LABELS: Record<string, string> = {
  start: '开始',
  parse_script: '剧本解析',
  generate_storyboard: '分镜生成',
  generate_reference_images: '参考画面',
  wait_storyboard_confirm: '等待分镜确认',
  phase2_start: '进入第二阶段',
  generate_images: '画面生成',
  generate_voice: '配音生成',
  compose_video: '视频合成',
  quality_check: '质量校验',
  rendering: '导出渲染',
}

function toOutputUrl(imagePath?: string) {
  if (!imagePath) return null
  const relative = imagePath.replace(/^.*output[\\/]/, '').replace(/\\/g, '/')
  return `${API_OUTPUT_BASE}${relative}`
}

function normalizeShot(shot: any) {
  return {
    id: shot.id || shot.shot_id || '',
    project_id: shot.project_id || '',
    sequence: Number(shot.sequence || 0),
    shot_type: shot.shot_type || 'medium',
    scene_description: shot.scene_description || '',
    character_action: shot.character_action || '',
    dialogue: shot.dialogue || '',
    camera_angle: shot.camera_angle || '正面',
    duration: Number(shot.duration || 3),
    emotion: shot.emotion || 'neutral',
    transition: shot.transition || 'cut',
    image_path: shot.image_path || '',
    audio_path: shot.audio_path || '',
    status: shot.status || 'pending',
    version: Number(shot.version || 1),
    confirmed: Boolean(shot.confirmed),
    characters_in_scene: Array.isArray(shot.characters_in_scene) ? shot.characters_in_scene : [],
  }
}

function getStepLabel(step?: string) {
  if (!step) return '处理中'
  return STEP_LABELS[step] || '处理中'
}

const MainWorkspace: React.FC = () => {
  const {
    shots,
    selectedShotId,
    selectShot,
    setShots,
    setGenerating,
    setProgress,
    isGenerating,
    updateShot,
    awaitingStoryboardConfirm,
    setAwaitingStoryboardConfirm,
    videoPath,
    setVideoPath,
    appendLog,
    clearLogs,
    currentStep,
  } = useShotStore()

  const { projectId, setProject, style, platform, outputFormat, resolution } = useProjectStore()

  const [script, setScript] = useState('')
  const [newProjectTitle, setNewProjectTitle] = useState('')
  const [showCreatePanel, setShowCreatePanel] = useState(false)
  const [creatingProject, setCreatingProject] = useState(false)
  const [loading, setLoading] = useState(false)
  const [autoWriting, setAutoWriting] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const [previewMode, setPreviewMode] = useState<'shot' | 'video'>('shot')
  const wsRef = useRef<WebSocket | null>(null)
  const wsProjectIdRef = useRef<string | null>(null)
  const uploadInputRef = useRef<HTMLInputElement | null>(null)
  const generateRef = useRef<() => Promise<void>>(async () => {})
  const awaitingRef = useRef(awaitingStoryboardConfirm)
  const stepRef = useRef(currentStep)

  const selectedShot = useMemo(
    () => shots.find((s) => s.id === selectedShotId) || shots[0],
    [shots, selectedShotId],
  )

  const replaceShots = (nextShots: any[]) => {
    const normalized = nextShots.map(normalizeShot).filter((s) => s.id)
    setShots(normalized)
    const stillExists = normalized.some((s) => s.id === selectedShotId)
    if (!stillExists && normalized[0]?.id) {
      selectShot(normalized[0].id)
    }
  }

  const loadProjectShots = async (pid: string) => {
    const list = await shotApi.list(pid)
    replaceShots(list || [])
  }

  const connectWebSocket = (pid: string) => {
    if (
      wsRef.current &&
      wsProjectIdRef.current === pid &&
      (wsRef.current.readyState === WebSocket.OPEN || wsRef.current.readyState === WebSocket.CONNECTING)
    ) {
      return wsRef.current
    }

    wsRef.current?.close()
    wsProjectIdRef.current = pid

    // 单一 WebSocket 入口：统一驱动流程进度、镜头更新和完成态。
    const ws = createWebSocket(pid, (data) => {
      const ts = new Date().toLocaleTimeString('zh-CN', { hour12: false })

      if (data.type === 'progress') {
        appendLog(`[${ts}] ${getStepLabel(data.step)} | ${data.progress ?? 0}%`)
        setProgress(Number(data.progress || 0), data.step || '')

        if (data.step === 'wait_storyboard_confirm') {
          setGenerating(false)
          setLoading(false)
          setAwaitingStoryboardConfirm(true)
          void loadProjectShots(pid)
          message.info('分镜已生成，请确认后继续')
          return
        }

        if (
          data.step === 'phase2_start' ||
          data.step === 'generate_images' ||
          data.step === 'generate_voice' ||
          data.step === 'compose_video' ||
          data.step === 'quality_check'
        ) {
          setAwaitingStoryboardConfirm(false)
          setGenerating(true)
        }
        return
      }

      if (data.type === 'shot_update' && data.shot_id) {
        appendLog(`[${ts}] 镜头已更新 | ${data.shot_id}`)
        updateShot(data.shot_id, {
          status: data.status || 'done',
          image_path: data.image_path || '',
        })
        return
      }

      if (data.type === 'complete') {
        appendLog(`[${ts}] 流程执行完成`)

        if (awaitingRef.current || stepRef.current === 'wait_storyboard_confirm') {
          setGenerating(false)
          setLoading(false)
          setAwaitingStoryboardConfirm(true)
          void loadProjectShots(pid)
          return
        }

        setGenerating(false)
        setLoading(false)
        setAwaitingStoryboardConfirm(false)
        setProgress(100, 'quality_check')

        if (data.video_path) {
          setVideoPath(data.video_path)
          setPreviewMode('video')
        }

        if (Array.isArray(data.shots) && data.shots.length > 0) {
          replaceShots(data.shots)
        } else {
          void loadProjectShots(pid)
        }

        message.success('生成完成')
        return
      }

      if (data.type === 'render_complete' && data.video_url) {
        appendLog(`[${ts}] 成片导出完成`)
        setVideoPath(data.video_url)
        setPreviewMode('video')
        setGenerating(false)
        setLoading(false)
        setProgress(100, 'quality_check')
        message.success('成片已生成，可直接播放')
        return
      }

      if (data.type === 'error') {
        appendLog(`[${ts}] 错误 | ${data.message || '未知错误'}`)
        message.error(data.message || '流程执行失败')
        setGenerating(false)
        setLoading(false)
        setAwaitingStoryboardConfirm(false)
      }
    })

    wsRef.current = ws
    return ws
  }

  const ensureProject = async () => {
    if (projectId) return projectId

    const project = await projectApi.create({
      title: script.trim() ? script.slice(0, 20) : '未命名项目',
      style,
      genre: '',
    })

    setProject({
      projectId: project.id,
      title: project.title,
      style,
      outputFormat,
      resolution,
      platform,
    })

    return project.id as string
  }

  const updateProjectField = async (field: 'style' | 'resolution', value: string) => {
    setProject({ [field]: value } as any)
    if (!projectId) return

    try {
      await projectApi.update(projectId, { [field]: value })
    } catch (err: any) {
      message.error('项目配置更新失败：' + (err.message || '未知错误'))
    }
  }

  const handleCreateProject = async () => {
    try {
      setCreatingProject(true)
      const title = newProjectTitle.trim() || '未命名项目'
      const project = await projectApi.create({ title, style, genre: '' })

      setProject({
        projectId: project.id,
        title: project.title,
        style,
        outputFormat,
        resolution,
        platform,
      })

      setShots([])
      selectShot(null)
      setGenerating(false)
      setAwaitingStoryboardConfirm(false)
      setVideoPath('')
      setProgress(0, '')
      clearLogs()
      setNewProjectTitle('')
      setShowCreatePanel(false)
      message.success('新建项目成功')
    } catch (err: any) {
      message.error('新建项目失败：' + (err.message || '未知错误'))
    } finally {
      setCreatingProject(false)
    }
  }

  const submitScriptForStoryboard = async (nextScript: string) => {
    if (!nextScript.trim()) {
      message.warning('请输入剧本内容')
      return
    }

    setLoading(true)
    setGenerating(true)
    setAwaitingStoryboardConfirm(false)
    setVideoPath('')
    setPreviewMode('shot')
    clearLogs()
    setProgress(0, 'parse_script')

    try {
      const pid = await ensureProject()
      connectWebSocket(pid)
      await scriptApi.parse({
        project_id: pid,
        user_input: nextScript,
        input_type: 'text',
        style,
        output_format: outputFormat,
        resolution,
        platform,
        target_duration: 30,
      })
      appendLog(`[${new Date().toLocaleTimeString('zh-CN', { hour12: false })}] 已提交解析任务`)
    } catch (err: any) {
      message.error('提交失败：' + (err.message || '未知错误'))
      setGenerating(false)
      setLoading(false)
    }
  }

  const handleGenerate = async () => {
    await submitScriptForStoryboard(script)
  }

  const handleAutoWriteScript = async () => {
    try {
      setAutoWriting(true)
      setGenerating(true)
      setAwaitingStoryboardConfirm(false)
      setVideoPath('')
      clearLogs()
      setProgress(0, 'generate_script')

      const pid = await ensureProject()
      connectWebSocket(pid)
      const prompt = script.trim() || '一个适合 45 秒竖屏漫剧的温暖成长故事'
      const result = await scriptApi.generate({
        project_id: pid,
        prompt,
        style,
        genre: '原创短剧',
        target_duration: 45,
      })
      const generatedScript = result.script || ''
      setScript(generatedScript)
      appendLog(`[${new Date().toLocaleTimeString('zh-CN', { hour12: false })}] Agent 已生成完整剧本`)
      await submitScriptForStoryboard(generatedScript)
    } catch (err: any) {
      message.error('自动生成剧本失败：' + (err.message || '未知错误'))
      setGenerating(false)
      setLoading(false)
    } finally {
      setAutoWriting(false)
    }
  }

  const handleUpload = async (file: File) => {
    try {
      setUploading(true)
      setGenerating(true)
      setAwaitingStoryboardConfirm(false)
      setVideoPath('')
      setPreviewMode('shot')
      clearLogs()
      setProgress(0, 'parse_script')

      const pid = await ensureProject()
      connectWebSocket(pid)

      const formData = new FormData()
      formData.append('project_id', pid)
      formData.append('file', file)
      formData.append('style', style)
      formData.append('output_format', outputFormat)
      formData.append('resolution', resolution)
      formData.append('platform', platform)

      await scriptApi.upload(formData)
      appendLog(`[${new Date().toLocaleTimeString('zh-CN', { hour12: false })}] 已上传剧本：${file.name}`)
      message.success('剧本上传成功')
    } catch (err: any) {
      message.error('上传失败：' + (err.message || '未知错误'))
      setGenerating(false)
    } finally {
      setUploading(false)
    }
  }

  const handleConfirmStoryboard = async () => {
    if (!projectId) return

    try {
      setConfirming(true)
      setGenerating(true)
      setPreviewMode('shot')
      connectWebSocket(projectId)
      // 第二阶段：用户确认分镜后继续画面、语音与合成流程。
      await shotApi.confirmStoryboard(projectId)
      setAwaitingStoryboardConfirm(false)
      appendLog(`[${new Date().toLocaleTimeString('zh-CN', { hour12: false })}] 已确认分镜，进入第二阶段`)
      message.success('分镜确认成功，继续生成')
    } catch (err: any) {
      message.error('确认分镜失败：' + (err.message || '未知错误'))
      setGenerating(false)
    } finally {
      setConfirming(false)
    }
  }

  useEffect(() => {
    generateRef.current = handleGenerate
  }, [script, projectId, style, outputFormat, resolution, platform])

  useEffect(() => {
    awaitingRef.current = awaitingStoryboardConfirm
    stepRef.current = currentStep
  }, [awaitingStoryboardConfirm, currentStep])

  useEffect(() => {
    const onParse = () => {
      void generateRef.current()
    }

    const onOpenCreateProject = () => {
      setShowCreatePanel(true)
    }

    window.addEventListener(PARSE_SCRIPT_EVENT, onParse)
    window.addEventListener(OPEN_CREATE_PROJECT_EVENT, onOpenCreateProject)
    return () => {
      window.removeEventListener(PARSE_SCRIPT_EVENT, onParse)
      window.removeEventListener(OPEN_CREATE_PROJECT_EVENT, onOpenCreateProject)
    }
  }, [])

  useEffect(() => {
    if (!projectId) return

    connectWebSocket(projectId)
    return () => {
      wsRef.current?.close()
      wsRef.current = null
      wsProjectIdRef.current = null
    }
  }, [projectId])

  const imageUrl = toOutputUrl(selectedShot?.image_path)
  const videoUrl = videoPath
    ? videoPath.startsWith('/output/')
      ? `${API_OUTPUT_BASE}${videoPath.replace('/output/', '')}`
      : toOutputUrl(videoPath)
    : null

  return (
    <section className="main-workspace" aria-label="主工作区">
      <div className="script-panel panel-enter">
        <div className="workspace-toolbar">
          <div className="workspace-toolbar-controls">
            <div className="toolbar-field">
              <span className="toolbar-label">画风</span>
              <Select
                value={style}
                size="small"
                style={{ width: 140 }}
                onChange={(v) => void updateProjectField('style', v)}
                options={[
                  { value: 'anime', label: '日系写实漫' },
                  { value: 'chinese', label: '国漫厚涂' },
                  { value: 'chibi', label: '简约条漫' },
                  { value: 'realistic', label: '电影写实' },
                ]}
              />
            </div>
            <div className="toolbar-field">
              <span className="toolbar-label">分辨率</span>
              <Select
                value={resolution}
                size="small"
                style={{ width: 130 }}
                onChange={(v) => void updateProjectField('resolution', v)}
                options={[
                  { value: '720p', label: '高清 720' },
                  { value: '1080p', label: '全高清 1080' },
                  { value: '2k', label: '影院级 2 千' },
                  { value: '4k', label: '超高清 4 千' },
                ]}
              />
            </div>
          </div>
        </div>

        {showCreatePanel && (
          <div className="workspace-create-panel">
            <div className="workspace-create-copy">
              <div className="workspace-create-title">新建项目</div>
              <div className="workspace-create-note">在主工作区完成项目创建，创建后会自动切换到新项目。</div>
            </div>
            <div className="workspace-create-form">
              <Input
                value={newProjectTitle}
                placeholder="请输入项目名称"
                onChange={(e) => setNewProjectTitle(e.target.value)}
                onPressEnter={() => void handleCreateProject()}
              />
              <Button type="primary" loading={creatingProject} onClick={() => void handleCreateProject()}>
                确认创建
              </Button>
              <Button onClick={() => setShowCreatePanel(false)}>取消</Button>
            </div>
          </div>
        )}

        <div className="script-editor-row">
          <TextArea
            value={script}
            onChange={(e) => setScript(e.target.value)}
            placeholder={'请输入剧本内容...\n\n场景：深夜街道，细雨\n人物：男主，情绪低沉\n镜头：中景，慢慢推近'}
            style={{
              height: '100%',
              resize: 'none',
              fontSize: 13,
              lineHeight: 1.7,
            }}
          />

          <div className="script-actions">
            <Button
              icon={<BulbOutlined />}
              onClick={() => void handleAutoWriteScript()}
              loading={autoWriting}
              size="small"
            >
              AI写剧本
            </Button>

            <Button
              type="primary"
              icon={<SendOutlined />}
              onClick={() => void handleGenerate()}
              loading={loading}
              size="small"
            >
              生成分镜
            </Button>

            <Button
              icon={<UploadOutlined />}
              size="small"
              loading={uploading}
              onClick={() => uploadInputRef.current?.click()}
            >
              上传剧本
            </Button>

            <input
              ref={uploadInputRef}
              type="file"
              accept=".txt,.docx"
              style={{ display: 'none' }}
              onChange={(e) => {
                const file = e.target.files?.[0]
                if (file) {
                  void handleUpload(file)
                }
                e.target.value = ''
              }}
            />
          </div>
        </div>
      </div>

      <div className="preview-panel panel-enter">
        <div className="preview-stage">
          {awaitingStoryboardConfirm && (
            <div className="confirm-overlay">
              <Button
                type="primary"
                size="small"
                icon={<CheckCircleOutlined />}
                loading={confirming}
                onClick={handleConfirmStoryboard}
              >
                确认分镜并继续
              </Button>
            </div>
          )}

          {videoUrl && (
            <div className="preview-mode-switch" aria-label="预览模式">
              <button
                type="button"
                className={previewMode === 'shot' ? 'active' : ''}
                onClick={() => setPreviewMode('shot')}
              >
                分镜
              </button>
              <button
                type="button"
                className={previewMode === 'video' ? 'active' : ''}
                onClick={() => setPreviewMode('video')}
              >
                成片
              </button>
            </div>
          )}

          {isGenerating ? (
            <div className="preview-loading">
              <div>{getStepLabel(currentStep)}...</div>
              <div className="preview-loading-bar" />
            </div>
          ) : videoUrl && previewMode === 'video' ? (
            <video
              src={videoUrl}
              controls
              className="final-video"
              poster={imageUrl || undefined}
            />
          ) : imageUrl ? (
            <img src={imageUrl} alt="当前镜头预览" style={{ width: '100%', height: '100%', objectFit: 'contain' }} />
          ) : (
            <span className="preview-placeholder">选择镜头即可预览画面</span>
          )}

          {selectedShot && !isGenerating && previewMode === 'shot' && (
            <div className="preview-caption">
              <div className="preview-scene">{selectedShot.scene_description}</div>
              {selectedShot.dialogue && <div className="preview-dialogue">“{selectedShot.dialogue}”</div>}
            </div>
          )}
        </div>

        {shots.length > 0 && (
          <div className="thumb-strip">
            {shots.map((shot, i) => {
              const thumbUrl = toOutputUrl(shot.image_path)
              const isSelected = (selectedShotId || shots[0]?.id) === shot.id

              return (
                <div
                  key={shot.id}
                  className={`thumb-item${isSelected ? ' active' : ''}`}
                  onClick={() => selectShot(shot.id)}
                >
                  {thumbUrl ? (
                    <img src={thumbUrl} alt={`镜头 ${i + 1}`} style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
                  ) : (
                    <div className="thumb-index">{i + 1}</div>
                  )}
                </div>
              )
            })}
          </div>
        )}
      </div>

    </section>
  )
}

export default MainWorkspace

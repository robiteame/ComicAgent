import React, { useEffect, useMemo, useRef, useState } from 'react'
import { Button, Input, Modal, Segmented, Select, Tooltip, message } from 'antd'
import {
  BulbOutlined,
  CheckCircleOutlined,
  ClockCircleOutlined,
  DragOutlined,
  EditOutlined,
  ReloadOutlined,
  SaveOutlined,
  SendOutlined,
  UploadOutlined,
  ZoomInOutlined,
  ZoomOutOutlined,
} from '@ant-design/icons'
import { useShotStore } from '../stores/shotStore'
import { useProjectStore } from '../stores/projectStore'
import { API_OUTPUT_BASE, assetApi, createWebSocket, projectApi, renderApi, scriptApi, settingsApi, shotApi } from '../services/api'
import { STYLE_DESCRIPTIONS, STYLE_OPTIONS } from '../constants/styleTemplates'
import { STYLE_TEMPLATES_UPDATED_EVENT } from './SystemSettingsPage'

const { TextArea } = Input
const PARSE_SCRIPT_EVENT = 'pipeline:parse-script'
const OPEN_CREATE_PROJECT_EVENT = 'workspace:open-create-project'
const OPEN_SHOT_CONFIG_EVENT = 'workspace:open-shot-config'
const WORKSPACE_NAVIGATE_EVENT = 'workspace:navigate'

type StyleOption = { value: string; label: string; keywords?: string; custom?: boolean }

const STEP_LABELS: Record<string, string> = {
  start: '开始',
  parse_script: '剧本解析',
  generate_storyboard: '分镜生成',
  wait_asset_confirm: '等待素材确认',
  generate_storyboard_images: '故事板生成',
  wait_storyboard_approval: '等待故事板审核',
  phase2_start: '进入第二阶段',
  generate_voice: '配音生成',
  generate_seedance_video: 'Seedance 视频',
  compose_video: '视频合成',
  quality_check: '质量校验',
  rendering: '导出渲染',
}

const WORKSPACE_TABS = [
  { id: 'script', label: '剧本编辑' },
  { id: 'assets', label: '角色场景资产' },
  { id: 'storyboard', label: '故事板预览' },
  { id: 'review', label: '分镜审核' },
  { id: 'video', label: '成片预览' },
] as const

type WorkspaceTab = typeof WORKSPACE_TABS[number]['id']

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
    camera_movement: shot.camera_movement || '静止',
    duration: Number(shot.duration || 3),
    emotion: shot.emotion || 'neutral',
    transition: shot.transition || 'cut',
    visual_notes: shot.visual_notes || '',
    image_path: shot.image_path || '',
    storyboard_path: shot.storyboard_path || '',
    video_path: shot.video_path || '',
    audio_path: shot.audio_path || '',
    status: shot.status || 'pending',
    storyboard_status: shot.storyboard_status || 'pending',
    version: Number(shot.version || 1),
    confirmed: Boolean(shot.confirmed),
    characters_in_scene: Array.isArray(shot.characters_in_scene) ? shot.characters_in_scene : [],
    scene_asset_id: shot.scene_asset_id || '',
    character_asset_ids: Array.isArray(shot.character_asset_ids) ? shot.character_asset_ids : [],
    scene_group_id: shot.scene_group_id || '',
    consistency_context: shot.consistency_context || '',
    reference_weights: shot.reference_weights || {},
    continuity_profile: shot.continuity_profile || {},
    continuity_reference_path: shot.continuity_reference_path || '',
    pose_reference_path: shot.pose_reference_path || '',
    depth_reference_path: shot.depth_reference_path || '',
    last_frame_path: shot.last_frame_path || '',
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

  const {
    projectId,
    parentProjectTitle,
    projectType,
    title,
    setProject,
    style,
    platform,
    outputFormat,
    resolution,
    runMode,
  } = useProjectStore()

  const [script, setScript] = useState('')
  const [newProjectTitle, setNewProjectTitle] = useState('')
  const [newEpisodeTitle, setNewEpisodeTitle] = useState('第 1 集')
  const [episodeTitleDraft, setEpisodeTitleDraft] = useState(title)
  const [showCreatePanel, setShowCreatePanel] = useState(false)
  const [creatingProject, setCreatingProject] = useState(false)
  const [loading, setLoading] = useState(false)
  const [autoWriting, setAutoWriting] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const [composing, setComposing] = useState(false)
  const [generatingStoryboard, setGeneratingStoryboard] = useState(false)
  const [assetBoard, setAssetBoard] = useState<{ characters: any[]; scenes: any[] } | null>(null)
  const [assetBoardReady, setAssetBoardReady] = useState(false)
  const [assetTab, setAssetTab] = useState<'characters' | 'scenes'>('characters')
  const [styleTemplates, setStyleTemplates] = useState<StyleOption[]>(STYLE_OPTIONS)
  const [editingAssetId, setEditingAssetId] = useState<string | null>(null)
  const [assetDraft, setAssetDraft] = useState<Record<string, any>>({})
  const [savingAsset, setSavingAsset] = useState(false)
  const [workspaceTab, setWorkspaceTab] = useState<WorkspaceTab>('script')
  const [previewMode, setPreviewMode] = useState<'shot' | 'video'>('shot')
  const [previewScale, setPreviewScale] = useState(1)
  const [previewOffset, setPreviewOffset] = useState({ x: 0, y: 0 })
  const [dragStart, setDragStart] = useState<{ x: number; y: number; ox: number; oy: number } | null>(null)
  const [imagePreview, setImagePreview] = useState<{ url: string; title: string } | null>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const wsProjectIdRef = useRef<string | null>(null)
  const uploadInputRef = useRef<HTMLInputElement | null>(null)
  const generateRef = useRef<() => Promise<void>>(async () => {})
  const awaitingRef = useRef(awaitingStoryboardConfirm)
  const stepRef = useRef(currentStep)
  const pollingRef = useRef(false)

  const selectedShot = useMemo(
    () => shots.find((s) => s.id === selectedShotId) || shots[0],
    [shots, selectedShotId],
  )

  const hasStoryboardShots = useMemo(
    () => shots.some((shot) => Boolean(shot.storyboard_path || shot.image_path)),
    [shots],
  )
  const storyboardReviewVisible = hasStoryboardShots && previewMode === 'shot' && !videoPath
  const approvedShotCount = useMemo(
    () => shots.filter((shot) => shot.confirmed).length,
    [shots],
  )
  const selectedShotVideoUrl = selectedShot?.video_path ? toOutputUrl(selectedShot.video_path) : null
  const allShotVideosReady = useMemo(
    () => shots.length > 0 && shots.every((shot) => Boolean(shot.video_path)),
    [shots],
  )

  useEffect(() => {
    const navigateWorkspace = (event: Event) => {
      const detail = (event as CustomEvent<{ tab?: WorkspaceTab; previewMode?: 'shot' | 'video' }>).detail || {}
      const nextTab = detail.tab
      if (nextTab && WORKSPACE_TABS.some((tab) => tab.id === nextTab)) {
        setWorkspaceTab(nextTab)
      }
      if (detail.previewMode) {
        setPreviewMode(detail.previewMode)
      } else if (nextTab === 'storyboard' || nextTab === 'review') {
        setPreviewMode('shot')
      } else if (nextTab === 'video') {
        setPreviewMode('video')
      }
    }

    window.addEventListener(WORKSPACE_NAVIGATE_EVENT, navigateWorkspace)
    return () => window.removeEventListener(WORKSPACE_NAVIGATE_EVENT, navigateWorkspace)
  }, [])

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

  const loadAssetBoard = async (pid: string) => {
    const board = await assetApi.board(pid)
    setAssetBoard({ characters: board.characters || [], scenes: board.scenes || [] })
    return board
  }

  const refreshWorkspaceData = async (pid: string, includeAssets = false) => {
    await loadProjectShots(pid)
    if (includeAssets) {
      await loadAssetBoard(pid)
    }
  }

  const loadStyleTemplates = async () => {
    const result = await settingsApi.styleTemplates()
    if (Array.isArray(result.templates)) {
      setStyleTemplates(result.templates)
    }
  }

  const applyProjectDetail = (projectDetail: any) => {
    setProject({
      projectId: projectDetail.id,
      parentProjectId: projectDetail.parent_project_id || '',
      parentProjectTitle: projectDetail.parent_project_title || '',
      projectType: projectDetail.project_type || 'series',
      episodeNumber: projectDetail.episode_number || 0,
      title: projectDetail.title,
      genre: projectDetail.genre,
      style: projectDetail.style || style,
      status: projectDetail.status,
      outputFormat: projectDetail.output_format || outputFormat,
      resolution: projectDetail.resolution || resolution,
      platform: projectDetail.platform || platform,
    })
    setEpisodeTitleDraft(projectDetail.title || '')
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
      // 实时读取最新运行模式：全自动模式下后端 LangGraph 不在人工卡点停留，
      // 前端也不应切到“等待确认”态或关闭生成中状态。
      const autoMode = useProjectStore.getState().runMode === 'auto'

      if (data.type === 'progress') {
        appendLog(`[${ts}] ${getStepLabel(data.step)} | ${data.progress ?? 0}%`)
        setProgress(Number(data.progress || 0), data.step || '')

        if (data.step === 'wait_asset_confirm') {
          if (autoMode) {
            void loadProjectShots(pid)
            void loadAssetBoard(pid)
            return
          }
          setGenerating(false)
          setLoading(false)
          setAssetBoardReady(true)
          setAwaitingStoryboardConfirm(false)
          setWorkspaceTab('assets')
          void loadProjectShots(pid)
          void loadAssetBoard(pid)
          message.info('角色板和场景板已生成，请确认素材后生成故事板')
          return
        }

        if (data.step === 'wait_storyboard_approval') {
          if (autoMode) {
            void loadProjectShots(pid)
            return
          }
          setGenerating(false)
          setLoading(false)
          setGeneratingStoryboard(false)
          setAwaitingStoryboardConfirm(true)
          setWorkspaceTab('review')
          void loadProjectShots(pid)
          message.info('故事板已生成，请逐镜头审核并生成视频')
          return
        }

        if (
          data.step === 'phase2_start' ||
          data.step === 'generate_voice' ||
          data.step === 'generate_seedance_video' ||
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
          storyboard_path: data.storyboard_path || data.image_path || '',
          video_path: data.video_path || '',
          audio_path: data.audio_path || '',
          storyboard_status: data.storyboard_status || 'done',
          scene_group_id: data.scene_group_id || '',
          reference_weights: data.reference_weights || {},
          continuity_profile: data.continuity_profile || {},
          continuity_reference_path: data.continuity_reference_path || '',
          pose_reference_path: data.pose_reference_path || '',
          depth_reference_path: data.depth_reference_path || '',
          last_frame_path: data.last_frame_path || '',
        })
        if (data.video_path) {
          if (autoMode) {
            void loadProjectShots(pid)
          } else {
            setGenerating(false)
            setPreviewMode('video')
            setWorkspaceTab('video')
            void loadProjectShots(pid)
          }
        }
        return
      }

      if (data.type === 'complete') {
        appendLog(`[${ts}] 流程执行完成`)

        if (data.asset_board_ready) {
          if (autoMode) {
            if (Array.isArray(data.shots) && data.shots.length > 0) {
              replaceShots(data.shots)
            }
            void loadAssetBoard(pid)
            return
          }
          setGenerating(false)
          setLoading(false)
          setAssetBoardReady(true)
          setAwaitingStoryboardConfirm(false)
          setWorkspaceTab('assets')
          if (Array.isArray(data.shots) && data.shots.length > 0) {
            replaceShots(data.shots)
          }
          void loadAssetBoard(pid)
          return
        }

        if (!autoMode && (!data.video_path || awaitingRef.current || stepRef.current === 'wait_storyboard_approval')) {
          setGenerating(false)
          setLoading(false)
          setAwaitingStoryboardConfirm(true)
          setPreviewMode('shot')
          setWorkspaceTab('review')
          if (Array.isArray(data.shots) && data.shots.length > 0) {
            replaceShots(data.shots)
          }
          void loadProjectShots(pid)
          return
        }

        if (autoMode && !data.video_path) {
          // 全自动模式下的中间态 complete（无成片）：仅刷新数据，保持生成中，等待后续节点。
          if (Array.isArray(data.shots) && data.shots.length > 0) {
            replaceShots(data.shots)
          } else {
            void loadProjectShots(pid)
          }
          return
        }

        setGenerating(false)
        setLoading(false)
        setAwaitingStoryboardConfirm(false)
        setProgress(100, 'quality_check')

        if (data.video_path) {
          setVideoPath(data.video_path)
          setPreviewMode('video')
          setWorkspaceTab('video')
        }

        if (Array.isArray(data.shots) && data.shots.length > 0) {
          replaceShots(data.shots)
        } else {
          void loadProjectShots(pid)
        }

        message.success('生成完成')
        return
      }

      if (data.type === 'storyboard_ready') {
        appendLog(`[${ts}] 故事板生成完成${autoMode ? '（全自动继续生成视频）' : '，等待审核'}`)
        if (autoMode) {
          void loadProjectShots(pid)
          return
        }
        setGenerating(false)
        setGeneratingStoryboard(false)
        setAwaitingStoryboardConfirm(true)
        setAssetBoardReady(false)
        setWorkspaceTab('review')
        void loadProjectShots(pid)
        return
      }

      if (data.type === 'render_complete' && data.video_url) {
        appendLog(`[${ts}] 成片导出完成`)
        setVideoPath(data.video_url)
        setPreviewMode('video')
        setWorkspaceTab('video')
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
        void loadProjectShots(pid)
      }
    })

    wsRef.current = ws
    return ws
  }

  const ensureProject = async () => {
    if (projectId) return projectId

    const project = await projectApi.create({
      title: script.trim() ? script.slice(0, 20) : '未命名项目',
      first_episode_title: '第 1 集',
      style,
      genre: '',
    })
    const activeProject = project.first_episode || project

    applyProjectDetail(activeProject)

    return activeProject.id as string
  }

  const updateProjectField = async (field: 'style' | 'resolution' | 'title', value: string) => {
    setProject({ [field]: value } as any)
    if (!projectId) return

    try {
      await projectApi.update(projectId, { [field]: value })
    } catch (err: any) {
      message.error('项目配置更新失败：' + (err.message || '未知错误'))
    }
  }

  const startEditAsset = (item: any) => {
    setEditingAssetId(item.id)
    setAssetDraft({
      ...item,
      appearanceText: item.appearance?.description || item.appearance?.default_outfit || '',
      keyFeaturesText: Array.isArray(item.key_features) ? item.key_features.join('\n') : '',
    })
  }

  const updateAssetDraft = (key: string, value: any) => {
    setAssetDraft((draft) => ({ ...draft, [key]: value }))
  }

  const handleSaveAsset = async (regenerate = false) => {
    if (!projectId || !editingAssetId) return
    try {
      setSavingAsset(true)
      const keyFeatures = String(assetDraft.keyFeaturesText || '')
        .split('\n')
        .map((item) => item.trim())
        .filter(Boolean)
      const payload =
        assetTab === 'characters'
          ? {
              name: assetDraft.name || '',
              appearance: { ...(assetDraft.appearance || {}), description: assetDraft.appearanceText || '' },
              personality: assetDraft.personality || '',
              visual_prompt: assetDraft.visual_prompt || '',
              negative_prompt: assetDraft.negative_prompt || '',
              voice_id: assetDraft.voice_id || '',
              key_features: keyFeatures,
              default_outfit: assetDraft.default_outfit || '',
              lora_profile: assetDraft.lora_profile || '',
              ip_adapter_profile: assetDraft.ip_adapter_profile || '',
              wardrobe_lock: assetDraft.wardrobe_lock || '',
              seed: String(assetDraft.seed || '42'),
              regenerate,
            }
          : {
              name: assetDraft.name || '',
              description: assetDraft.description || '',
              visual_prompt: assetDraft.visual_prompt || '',
              negative_prompt: assetDraft.negative_prompt || '',
              key_features: keyFeatures,
              scene_group_key: assetDraft.scene_group_key || '',
              time_of_day: assetDraft.time_of_day || '',
              prop_lock: assetDraft.prop_lock || '',
              seed: Number(assetDraft.seed || 1200),
              regenerate,
            }
      const updated =
        assetTab === 'characters'
          ? await assetApi.updateCharacter(editingAssetId, payload)
          : await assetApi.updateScene(editingAssetId, payload)
      setAssetBoard((board) => {
        if (!board) return board
        const key = assetTab
        return {
          ...board,
          [key]: board[key].map((item: any) => (item.id === editingAssetId ? updated : item)),
        }
      })
      setEditingAssetId(null)
      setAssetDraft({})
      message.success(regenerate ? '素材已更新并重生成' : '素材已保存')
    } catch (err: any) {
      message.error('素材保存失败：' + (err.message || '未知错误'))
    } finally {
      setSavingAsset(false)
    }
  }

  const commitEpisodeTitle = async () => {
    const nextTitle = episodeTitleDraft.trim() || title || '第 1 集'
    setEpisodeTitleDraft(nextTitle)
    if (nextTitle !== title) {
      await updateProjectField('title', nextTitle)
    }
  }

  const handleCreateProject = async () => {
    try {
      setCreatingProject(true)
      const title = newProjectTitle.trim() || '未命名项目'
      const project = await projectApi.create({
        title,
        first_episode_title: newEpisodeTitle.trim() || '第 1 集',
        style,
        genre: '',
        output_format: outputFormat,
        resolution,
        platform,
      })
      const activeProject = project.first_episode || project

      applyProjectDetail(activeProject)

      setShots([])
      selectShot(null)
      setGenerating(false)
      setAwaitingStoryboardConfirm(false)
      setAssetBoardReady(false)
      setAssetBoard(null)
      setVideoPath('')
      setProgress(0, '')
      setWorkspaceTab('script')
      clearLogs()
      setNewProjectTitle('')
      setNewEpisodeTitle('第 1 集')
      setShowCreatePanel(false)
      message.success('新建项目成功，已自动创建第一集')
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
    setAssetBoardReady(false)
    setVideoPath('')
    setPreviewMode('shot')
    setWorkspaceTab('script')
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
        mode: runMode,
      })
      appendLog(
        `[${new Date().toLocaleTimeString('zh-CN', { hour12: false })}] 已提交解析任务（${runMode === 'auto' ? '全自动生成' : '手动审核'}）`,
      )
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
      setAssetBoardReady(false)
      setVideoPath('')
      clearLogs()
      setWorkspaceTab('script')
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
      setAssetBoardReady(false)
      setVideoPath('')
      setPreviewMode('shot')
      setWorkspaceTab('script')
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
      formData.append('mode', runMode)

      const result = await scriptApi.upload(formData)
      if (typeof result.script === 'string') {
        setScript(result.script)
      }
      appendLog(`[${new Date().toLocaleTimeString('zh-CN', { hour12: false })}] 已上传剧本：${file.name}`)
      message.success('剧本上传成功')
    } catch (err: any) {
      message.error('上传失败：' + (err.message || '未知错误'))
      setGenerating(false)
    } finally {
      setUploading(false)
    }
  }

  const handleGenerateSelectedShotVideo = async () => {
    if (!projectId || !selectedShot) return

    try {
      setConfirming(true)
      if (!selectedShot.confirmed) {
        message.warning('请先审核通过当前镜头故事板')
        return
      }
      if (!(selectedShot.storyboard_path || selectedShot.image_path)) {
        message.warning('当前镜头尚未生成定稿故事板')
        return
      }
      setGenerating(true)
      setPreviewMode('shot')
      setWorkspaceTab('video')
      connectWebSocket(projectId)
      await shotApi.generateVideo(selectedShot.id, Boolean(selectedShot.video_path))
      setAwaitingStoryboardConfirm(false)
      appendLog(`[${new Date().toLocaleTimeString('zh-CN', { hour12: false })}] 已提交镜头 ${selectedShot.sequence} 视频生成`)
      message.success('当前镜头视频生成已启动')
    } catch (err: any) {
      message.error('镜头视频生成失败：' + (err.message || '未知错误'))
      setGenerating(false)
    } finally {
      setConfirming(false)
    }
  }

  const handleComposeProjectVideo = async () => {
    if (!projectId) return
    if (!allShotVideosReady) {
      message.warning('请先完成每个镜头的视频生成')
      return
    }

    try {
      setComposing(true)
      setGenerating(true)
      setPreviewMode('video')
      setWorkspaceTab('video')
      setProgress(92, 'compose_video')
      connectWebSocket(projectId)
      await renderApi.start({ project_id: projectId, output_format: outputFormat, resolution })
      appendLog(`[${new Date().toLocaleTimeString('zh-CN', { hour12: false })}] 已提交成片合成任务`)
      message.success('成片合成已启动')
    } catch (err: any) {
      message.error('成片合成失败：' + (err.message || '未知错误'))
      setGenerating(false)
    } finally {
      setComposing(false)
    }
  }

  const handleApproveShot = async (shotId: string, approved: boolean) => {
    try {
      await shotApi.approveStoryboard(shotId, approved)
      updateShot(shotId, { confirmed: approved, status: approved ? 'storyboard_approved' : 'needs_review' })
      message.success(approved ? '该镜头已通过审核' : '已标记为需调整')
    } catch (err: any) {
      message.error('审核操作失败：' + (err.message || '未知错误'))
    }
  }

  const changePreviewScale = (delta: number) => {
    setPreviewScale((value) => Math.min(3, Math.max(0.5, Number((value + delta).toFixed(2)))))
  }

  const resetPreviewTransform = () => {
    setPreviewScale(1)
    setPreviewOffset({ x: 0, y: 0 })
    setDragStart(null)
  }

  const beginPreviewDrag = (event: React.MouseEvent<HTMLDivElement>) => {
    if (!imageUrl || isGenerating || previewMode !== 'shot') return
    event.preventDefault()
    setDragStart({ x: event.clientX, y: event.clientY, ox: previewOffset.x, oy: previewOffset.y })
  }

  const movePreviewDrag = (event: React.MouseEvent<HTMLDivElement>) => {
    if (!dragStart) return
    setPreviewOffset({
      x: dragStart.ox + event.clientX - dragStart.x,
      y: dragStart.oy + event.clientY - dragStart.y,
    })
  }

  const handleGenerateStoryboard = async () => {
    if (!projectId) return

    try {
      setGeneratingStoryboard(true)
      setGenerating(true)
      setAwaitingStoryboardConfirm(false)
      setWorkspaceTab('storyboard')
      connectWebSocket(projectId)
      await shotApi.generateStoryboard(projectId)
      appendLog(`[${new Date().toLocaleTimeString('zh-CN', { hour12: false })}] 已确认素材，开始生成定稿故事板参考图`)
      message.success('故事板任务已启动')
    } catch (err: any) {
      message.error('故事板生成失败：' + (err.message || '未知错误'))
      setGenerating(false)
    } finally {
      setGeneratingStoryboard(false)
    }
  }

  useEffect(() => {
    generateRef.current = handleGenerate
  }, [script, projectId, style, outputFormat, resolution, platform, runMode])

  useEffect(() => {
    awaitingRef.current = awaitingStoryboardConfirm
    stepRef.current = currentStep
  }, [awaitingStoryboardConfirm, currentStep])

  useEffect(() => {
    setEpisodeTitleDraft(title)
  }, [title])

  useEffect(() => {
    const onParse = () => {
      void generateRef.current()
    }

    const onOpenCreateProject = () => {
      setWorkspaceTab('script')
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
    const reloadStyleTemplates = () => {
      void loadStyleTemplates().catch(() => undefined)
    }

    reloadStyleTemplates()
    window.addEventListener(STYLE_TEMPLATES_UPDATED_EVENT, reloadStyleTemplates)
    return () => window.removeEventListener(STYLE_TEMPLATES_UPDATED_EVENT, reloadStyleTemplates)
  }, [])

  useEffect(() => {
    if (!projectId) return

    connectWebSocket(projectId)
    projectApi.get(projectId)
      .then((projectDetail) => {
        applyProjectDetail(projectDetail)
        setScript(projectDetail.input_text || '')
        if (projectDetail.video_path) {
          setVideoPath(projectDetail.video_path)
        }
      })
      .catch(() => undefined)
    void loadProjectShots(projectId).catch(() => undefined)
    void loadAssetBoard(projectId).catch(() => undefined)
    return () => {
      wsRef.current?.close()
      wsRef.current = null
      wsProjectIdRef.current = null
    }
  }, [projectId])

  useEffect(() => {
    if (!projectId || !isGenerating) return

    const timer = window.setInterval(() => {
      if (pollingRef.current) return
      pollingRef.current = true
      const includeAssets = currentStep === 'wait_asset_confirm' || currentStep === 'generate_storyboard'
      refreshWorkspaceData(projectId, includeAssets)
        .catch(() => undefined)
        .finally(() => {
          pollingRef.current = false
        })
    }, 3200)

    return () => window.clearInterval(timer)
  }, [projectId, isGenerating, currentStep])

  const imageUrl = toOutputUrl(selectedShot?.storyboard_path || selectedShot?.image_path)
  const videoUrl = videoPath
    ? videoPath.startsWith('/output/')
      ? `${API_OUTPUT_BASE}${videoPath.replace('/output/', '')}`
      : toOutputUrl(videoPath)
    : null
  const currentVideoUrl = selectedShotVideoUrl || videoUrl

  useEffect(() => {
    resetPreviewTransform()
  }, [selectedShot?.id, imageUrl])

  const assetItems = assetTab === 'characters' ? assetBoard?.characters || [] : assetBoard?.scenes || []

  const renderReferencePreview = (item: any, label: string) => {
    const firstImage = Array.isArray(item.reference_images) ? item.reference_images[0] : ''
    const previewUrl = toOutputUrl(firstImage)
    return previewUrl ? (
      <button
        type="button"
        className="image-preview-trigger"
        onClick={() => setImagePreview({ url: previewUrl, title: item.name || label })}
        aria-label="查看高清原图"
      >
        <img src={previewUrl} alt={label} />
      </button>
    ) : (
      <span>{label}</span>
    )
  }

  const selectedShotReady = Boolean(selectedShot && (selectedShot.storyboard_path || selectedShot.image_path))
  const showPreviewSurface = workspaceTab === 'storyboard' || workspaceTab === 'review' || workspaceTab === 'video'
  const openShotConfig = (shotId: string) => {
    selectShot(shotId)
    setWorkspaceTab('review')
    setPreviewMode('shot')
    window.dispatchEvent(new CustomEvent(WORKSPACE_NAVIGATE_EVENT, { detail: { tab: 'review', previewMode: 'shot' } }))
    window.dispatchEvent(new CustomEvent(OPEN_SHOT_CONFIG_EVENT))
  }

  return (
    <section className="main-workspace tabbed-workspace" aria-label="主工作区">
      <div className="workspace-tabbar" role="tablist" aria-label="工作区模块">
        {WORKSPACE_TABS.map((tab) => {
          const active = workspaceTab === tab.id
          const tabMeta =
            tab.id === 'review' && shots.length > 0
              ? `${approvedShotCount}/${shots.length}`
              : tab.id === 'assets' && (assetBoardReady || assetBoard)
                ? '已就绪'
                : tab.id === 'video' && currentVideoUrl
                  ? '可预览'
                  : ''

          return (
            <button
              key={tab.id}
              type="button"
              role="tab"
              aria-selected={active}
              className={`workspace-tab${active ? ' active' : ''}`}
              onClick={() => {
                setWorkspaceTab(tab.id)
                if (tab.id === 'video' && currentVideoUrl) {
                  setPreviewMode('video')
                }
                if (tab.id === 'storyboard' || tab.id === 'review') {
                  setPreviewMode('shot')
                }
              }}
            >
              <span>{tab.label}</span>
              {tabMeta && <em>{tabMeta}</em>}
            </button>
          )
        })}
      </div>

      <div className="workspace-tab-body">
        {workspaceTab === 'script' && (
          <div className="script-panel panel-enter" role="tabpanel">
        <div className="script-scope-bar">
          <div className="script-scope-copy">
            <span>{parentProjectTitle || (projectType === 'series' ? title : '未选择大项目')}</span>
            <strong>{projectType === 'episode' ? '当前剧集' : '当前项目'}</strong>
          </div>
          <Input
            size="small"
            value={episodeTitleDraft}
            className="episode-title-input"
            placeholder="请输入剧集名称"
            onChange={(event) => setEpisodeTitleDraft(event.target.value)}
            onBlur={() => void commitEpisodeTitle()}
            onPressEnter={() => void commitEpisodeTitle()}
          />
        </div>
        <div className="workflow-rail" aria-label="创作流程">
          {['新建剧集', '上传剧本', 'AI解析', '资产板', '批量分镜', '逐镜审核', '生成视频'].map((item) => (
            <span key={item}>{item}</span>
          ))}
        </div>
        <div className="workspace-toolbar">
          <div className="workspace-toolbar-controls">
            <div className="toolbar-field">
              <span className="toolbar-label">画风</span>
              <Select
                value={style}
                size="small"
                style={{ width: 160 }}
                onChange={(v) => void updateProjectField('style', v)}
                options={styleTemplates.map((item) => ({
                  value: item.value,
                  label: item.custom ? `${item.label}（自定义）` : item.label,
                }))}
              />
              <em className="toolbar-hint">
                {STYLE_DESCRIPTIONS[style] || styleTemplates.find((item) => item.value === style)?.keywords || STYLE_DESCRIPTIONS.anime}
              </em>
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
            <div className="toolbar-field">
              <span className="toolbar-label">生成模式</span>
              <Tooltip
                title={
                  runMode === 'auto'
                    ? '全自动：解析剧本后由 LangGraph 一路跑到成片，自动通过故事板与逐镜视频，无需人工审核。'
                    : '手动审核：每一步生成后暂停，等待你确认素材、逐镜审核故事板再生成视频。'
                }
              >
                <Segmented
                  size="small"
                  value={runMode}
                  onChange={(value) => setProject({ runMode: value as 'manual' | 'auto' })}
                  options={[
                    { value: 'manual', label: '手动审核' },
                    { value: 'auto', label: '全自动生成' },
                  ]}
                />
              </Tooltip>
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
              <Input
                value={newEpisodeTitle}
                placeholder="请输入第一集名称"
                onChange={(e) => setNewEpisodeTitle(e.target.value)}
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
              AI解析剧本
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
        )}

        {workspaceTab === 'assets' && (
          <div className="asset-page panel-enter" role="tabpanel">
            <div className="asset-page-head">
              <div>
                <div className="asset-board-title">项目素材板</div>
                <div className="asset-board-note">
                  角色与场景将作为项目级素材复用到本集故事板和后续成片。
                </div>
              </div>
              <Button
                type="primary"
                size="small"
                loading={generatingStoryboard}
                disabled={!shots.length}
                onClick={() => void handleGenerateStoryboard()}
              >
                批量生成分镜
              </Button>
            </div>

            {(assetBoardReady || assetBoard) ? (
              <div className="asset-board-panel asset-page-board">
                <div className="asset-board-lists">
                  <div className="asset-tabs" aria-label="素材类型">
                    <button type="button" className={assetTab === 'characters' ? 'active' : ''} onClick={() => setAssetTab('characters')}>
                      角色板
                    </button>
                    <button type="button" className={assetTab === 'scenes' ? 'active' : ''} onClick={() => setAssetTab('scenes')}>
                      场景板
                    </button>
                  </div>
                  <div className="asset-card-strip asset-page-strip">
                    {assetItems.map((item) => (
                      <div className="asset-mini-card" key={item.id}>
                        <div className="asset-thumb">
                          {assetTab === 'characters'
                            ? renderReferencePreview(item, '三视图待生成')
                            : renderReferencePreview(item, '场景预览待生成')}
                        </div>
                        {editingAssetId === item.id ? (
                          <div className="asset-edit-form">
                            <Input size="small" value={assetDraft.name || ''} onChange={(event) => updateAssetDraft('name', event.target.value)} />
                            <TextArea
                              autoSize={{ minRows: 2, maxRows: 4 }}
                              value={assetTab === 'characters' ? assetDraft.personality || '' : assetDraft.description || ''}
                              onChange={(event) => updateAssetDraft(assetTab === 'characters' ? 'personality' : 'description', event.target.value)}
                            />
                            <TextArea
                              autoSize={{ minRows: 2, maxRows: 5 }}
                              value={assetDraft.visual_prompt || ''}
                              onChange={(event) => updateAssetDraft('visual_prompt', event.target.value)}
                              placeholder="视觉提示词"
                            />
                            <Input
                              size="small"
                              value={assetDraft.negative_prompt || ''}
                              onChange={(event) => updateAssetDraft('negative_prompt', event.target.value)}
                              placeholder="负向提示词"
                            />
                            <Input
                              size="small"
                              value={assetTab === 'characters' ? assetDraft.default_outfit || '' : assetDraft.prop_lock || ''}
                              onChange={(event) => updateAssetDraft(assetTab === 'characters' ? 'default_outfit' : 'prop_lock', event.target.value)}
                              placeholder={assetTab === 'characters' ? '服装锁定' : '道具/光源锁定'}
                            />
                            <div className="asset-edit-actions">
                              <Button size="small" icon={<SaveOutlined />} loading={savingAsset} onClick={() => void handleSaveAsset(false)}>
                                保存
                              </Button>
                              <Button size="small" type="primary" icon={<ReloadOutlined />} loading={savingAsset} onClick={() => void handleSaveAsset(true)}>
                                保存并重生成
                              </Button>
                              <Button size="small" onClick={() => setEditingAssetId(null)}>取消</Button>
                            </div>
                          </div>
                        ) : (
                          <div className="asset-mini-content">
                            <div className="asset-mini-title-row">
                              <strong>{item.name}</strong>
                              <Button size="small" icon={<EditOutlined />} onClick={() => startEditAsset(item)}>
                                编辑
                              </Button>
                            </div>
                            <span>{assetTab === 'characters' ? (item.personality || '性格待补充') : (item.description || '场景描述待补充')}</span>
                            {assetTab === 'characters' ? (
                              <>
                                <em>音色：{item.voice_id || 'Mimo 默认音色'}</em>
                                <em>人设：{item.appearance?.description || item.visual_prompt || '待补充'}</em>
                              </>
                            ) : (
                              <em>{item.visual_prompt || '视觉提示词待补充'}</em>
                            )}
                          </div>
                        )}
                      </div>
                    ))}
                    {!assetItems.length && <div className="asset-empty-card">素材生成后会在这里预览</div>}
                  </div>
                </div>
              </div>
            ) : (
              <div className="asset-empty-state">素材生成后会在这里集中管理</div>
            )}
          </div>
        )}

        {showPreviewSurface && (
          <>
            {workspaceTab === 'review' && (
              <div className="review-command-bar panel-enter" role="region" aria-label="分镜审核操作">
                <div className="review-shot-state">
                  <span>当前镜头 {selectedShot ? String(selectedShot.sequence || 1).padStart(2, '0') : '--'}</span>
                  <strong className={selectedShot?.confirmed ? 'approved' : 'pending'}>
                    {selectedShot?.confirmed ? '已过审' : '待审核'}
                  </strong>
                </div>
                <div className="review-actions">
                  <Button
                    type="primary"
                    className="review-approve-main"
                    icon={<CheckCircleOutlined />}
                    disabled={!selectedShot || !selectedShotReady || selectedShot.confirmed}
                    onClick={() => selectedShot && void handleApproveShot(selectedShot.id, true)}
                  >
                    {selectedShot?.confirmed ? '已通过审批' : '通过当前镜头'}
                  </Button>
                  <Button
                    disabled={!selectedShot || !selectedShotReady}
                    onClick={() => selectedShot && void handleApproveShot(selectedShot.id, false)}
                  >
                    退回调整
                  </Button>
                  <Button
                    type="primary"
                    className="shot-video-action"
                    loading={confirming}
                    disabled={!selectedShot || !selectedShot.confirmed}
                    onClick={handleGenerateSelectedShotVideo}
                  >
                    {selectedShot?.video_path ? '重新生成本镜头' : '生成本镜头视频'}
                  </Button>
                </div>
              </div>
            )}

            <div className="preview-panel panel-enter" role="tabpanel">
        <div
          className={`preview-stage${dragStart ? ' dragging' : ''}`}
          onMouseDown={beginPreviewDrag}
          onMouseMove={movePreviewDrag}
          onMouseUp={() => setDragStart(null)}
          onMouseLeave={() => setDragStart(null)}
        >
          {workspaceTab === 'review' && storyboardReviewVisible && (
            <div className="confirm-overlay">
              <Button
                type="primary"
                size="small"
                className="shot-video-action"
                icon={<CheckCircleOutlined />}
                loading={confirming}
                disabled={!selectedShot || !selectedShot.confirmed}
                onClick={handleGenerateSelectedShotVideo}
            >
                {selectedShot?.video_path ? '重新生成本镜头' : selectedShot?.confirmed ? '生成本镜头视频' : `审核后生成 ${approvedShotCount}/${shots.length}`}
              </Button>
              {allShotVideosReady && (
                <Button
                  type="primary"
                  size="small"
                  className="shot-video-action"
                  loading={composing}
                  onClick={handleComposeProjectVideo}
                >
                  合成成片
                </Button>
              )}
            </div>
          )}

          {imageUrl && previewMode === 'shot' && !isGenerating && (
            <div className="preview-tools" aria-label="分镜预览工具" onMouseDown={(event) => event.stopPropagation()}>
              <button type="button" onClick={(event) => { event.stopPropagation(); changePreviewScale(-0.1) }} aria-label="缩小">
                <ZoomOutOutlined />
              </button>
              <span>{Math.round(previewScale * 100)}%</span>
              <button type="button" onClick={(event) => { event.stopPropagation(); changePreviewScale(0.1) }} aria-label="放大">
                <ZoomInOutlined />
              </button>
              <button type="button" onClick={(event) => { event.stopPropagation(); resetPreviewTransform() }} aria-label="重置视图">
                <ReloadOutlined />
              </button>
              <DragOutlined />
            </div>
          )}

          {currentVideoUrl && (
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
                视频
              </button>
            </div>
          )}

          {isGenerating ? (
            <div className="preview-loading">
              <div>{getStepLabel(currentStep)}...</div>
              <div className="preview-loading-bar" />
            </div>
          ) : currentVideoUrl && previewMode === 'video' ? (
            <video
              src={currentVideoUrl}
              controls
              className="final-video"
              poster={imageUrl || undefined}
            />
          ) : imageUrl ? (
            <div className="preview-image-pan">
              <img
                src={imageUrl}
                alt="当前镜头预览"
                draggable={false}
                onClick={(event) => {
                  event.stopPropagation()
                  setImagePreview({ url: imageUrl, title: `镜头 ${selectedShot?.sequence || ''} 高清预览` })
                }}
                style={{
                  transform: `translate(${previewOffset.x}px, ${previewOffset.y}px) scale(${previewScale})`,
                }}
              />
            </div>
          ) : (
            <span className="preview-placeholder">选择镜头即可预览画面</span>
          )}

          {selectedShot && !isGenerating && previewMode === 'shot' && (
            <div className="preview-caption">
              <div className="preview-scene">{selectedShot.scene_description}</div>
              {selectedShot.dialogue && <div className="preview-dialogue">“{selectedShot.dialogue}”</div>}
              {workspaceTab === 'review' && selectedShotReady && (
                <div className="preview-approval-actions">
                  <Button
                    size="small"
                    className="approval-pass-btn"
                    type={selectedShot.confirmed ? 'primary' : 'default'}
                    onClick={() => void handleApproveShot(selectedShot.id, true)}
                    icon={<CheckCircleOutlined />}
                  >
                    通过此镜头
                  </Button>
                  <Button size="small" onClick={() => void handleApproveShot(selectedShot.id, false)}>
                    退回调整
                  </Button>
                  <span>{selectedShot.confirmed ? '已通过' : '待审核'}</span>
                </div>
              )}
            </div>
          )}
        </div>

        {shots.length > 0 && (
          <div className="thumb-strip">
            {shots.map((shot, i) => {
              const thumbUrl = toOutputUrl(shot.storyboard_path || shot.image_path)
              const isSelected = (selectedShotId || shots[0]?.id) === shot.id

              return (
                <div
                  key={shot.id}
                  className={`thumb-item${isSelected ? ' active' : ''}${shot.confirmed ? ' approved' : ''}`}
                  onClick={() => openShotConfig(shot.id)}
                >
                  {thumbUrl ? (
                    <img src={thumbUrl} alt={`镜头 ${i + 1}`} style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
                  ) : (
                    <div className="thumb-index">{i + 1}</div>
                  )}
                  <span className={`thumb-approval-badge${shot.confirmed ? ' approved' : ' pending'}`}>
                    {shot.confirmed ? <CheckCircleOutlined /> : <ClockCircleOutlined />}
                    <span>{shot.confirmed ? '已通过' : '待审核'}</span>
                  </span>
                </div>
              )
            })}
          </div>
        )}
            </div>
          </>
        )}
      </div>
      <Modal
        open={Boolean(imagePreview)}
        title={imagePreview?.title || '高清预览'}
        footer={null}
        centered
        width="min(1120px, 92vw)"
        className="image-preview-modal"
        onCancel={() => setImagePreview(null)}
      >
        {imagePreview && <img src={imagePreview.url} alt={imagePreview.title} />}
      </Modal>
    </section>
  )
}

export default MainWorkspace

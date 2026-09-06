import React, { useEffect, useMemo, useRef, useState } from 'react'
import {
  ApartmentOutlined,
  CodeOutlined,
  DownOutlined,
  FieldTimeOutlined,
  LeftOutlined,
  ReloadOutlined,
  RightOutlined,
  SafetyCertificateOutlined,
  SlidersOutlined,
  VideoCameraOutlined,
} from '@ant-design/icons'
import Button from 'antd/es/button'
import Input from 'antd/es/input'
import InputNumber from 'antd/es/input-number'
import message from 'antd/es/message'
import Select from 'antd/es/select'
import { assetApi, shotApi, toOutputUrl } from '../services/api'
import {
  drainPendingSaves,
  hasPendingChanges,
  retirePendingSaveAfterFlush,
  type PendingSaveEntry,
} from '../services/shotSaveQueue'
import { registerProjectNavigationGuard } from '../services/projectNavigationGuard'
import { useProjectStore } from '../stores/projectStore'
import { useShotStore } from '../stores/shotStore'

const { TextArea } = Input
const FlowGraph = React.lazy(() => import('./FlowGraph'))

const stepLabels: Record<string, string> = {
  generate_script: '剧本生成',
  parse_script: '剧本解析',
  generate_storyboard: '分镜列表',
  wait_asset_confirm: '素材确认',
  generate_storyboard_images: '故事板生成',
  wait_storyboard_approval: '分镜审核',
  phase2_start: '视频阶段',
  generate_voice: '配音生成',
  generate_seedance_video: '单镜视频',
  compose_video: '视频合成',
  quality_check: '质量校验',
  rendering: '导出渲染',
}

interface RightSidebarProps {
  collapsed: boolean
  onToggleCollapsed: () => void
}

type ShotSaveEntry = PendingSaveEntry<Record<string, any>> & {
  timer: number | null
  projectId: string
  shotId: string
}

const shotSaveKey = (projectId: string, shotId: string) => `${projectId}:${shotId}`

const RightSidebar: React.FC<RightSidebarProps> = ({ collapsed, onToggleCollapsed }) => {
  const { updateShot, logs, isGenerating, currentStep, shots, videoPath, setGenerating, setProgress, appendLog } = useShotStore()
  const { projectId, runMode, setProject } = useProjectStore()
  const [assetBoard, setAssetBoard] = useState<{ characters: any[]; scenes: any[] }>({ characters: [], scenes: [] })
  const [shotExpanded, setShotExpanded] = useState(true)
  const [runtimeExpanded, setRuntimeExpanded] = useState(true)
  const [consistencyExpanded, setConsistencyExpanded] = useState(true)
  const [flowExpanded, setFlowExpanded] = useState(false)
  const [logsExpanded, setLogsExpanded] = useState(true)
  const [regeneratingShot, setRegeneratingShot] = useState(false)
  const [loadingPrompt, setLoadingPrompt] = useState(false)
  const [shotDraft, setShotDraft] = useState<Record<string, any>>({})
  const [shotDirty, setShotDirty] = useState(false)
  const [shotSaveState, setShotSaveState] = useState<'idle' | 'dirty' | 'saving' | 'error'>('idle')
  const shotDraftRef = useRef<Record<string, any>>({})
  const shotSaveEntriesRef = useRef(new Map<string, ShotSaveEntry>())
  const flushShotDraftRef = useRef<(projectId: string, shotId: string) => Promise<boolean>>(async () => true)
  const assetRequestRef = useRef(0)
  const promptRequestRef = useRef(0)
  const regenerateRequestRef = useRef(0)
  const navigationFlushRef = useRef(new Map<string, Promise<boolean>>())
  const mountedRef = useRef(false)

  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
    }
  }, [])

  const selectedShot = useShotStore((state) => {
    const id = state.selectedShotId
    return state.shots.find((shot) => shot.id === id) || state.shots[0]
  })

  const selectedCharacters = useMemo(
    () =>
      selectedShot
        ? assetBoard.characters.filter((item) => (selectedShot.character_asset_ids || []).includes(item.id))
        : [],
    [assetBoard.characters, selectedShot],
  )

  const selectedScene = useMemo(
    () => (selectedShot ? assetBoard.scenes.find((item) => item.id === selectedShot.scene_asset_id) : null),
    [assetBoard.scenes, selectedShot],
  )

  const selectedSceneProfile = selectedScene?.consistency_profile || {}
  const sceneBaselineUrl = toOutputUrl(selectedScene?.baseline_image_path || selectedScene?.reference_images?.[0] || '')
  const referenceWeights = selectedShot?.reference_weights || {}
  const continuityProfile = selectedShot?.continuity_profile || {}
  const characterBlocking = continuityProfile.character_blocking || {}
  const blockingOrder = Array.isArray(characterBlocking.character_order_left_to_right)
    ? characterBlocking.character_order_left_to_right.filter(Boolean).join(' / ')
    : ''

  useEffect(() => {
    const requestId = ++assetRequestRef.current
    if (!projectId) {
      setAssetBoard({ characters: [], scenes: [] })
      return
    }
    assetApi.board(projectId)
      .then((board) => {
        if (requestId !== assetRequestRef.current || useProjectStore.getState().projectId !== projectId) return
        setAssetBoard({ characters: board.characters || [], scenes: board.scenes || [] })
      })
      .catch(() => undefined)
  }, [projectId])

  useEffect(() => {
    promptRequestRef.current += 1
    regenerateRequestRef.current += 1
    setLoadingPrompt(false)
    setRegeneratingShot(false)
  }, [projectId, selectedShot?.id])

  const getShotSaveEntry = (entryProjectId: string, shotId: string) => {
    const key = shotSaveKey(entryProjectId, shotId)
    let entry = shotSaveEntriesRef.current.get(key)
    if (!entry) {
      entry = {
        pending: {},
        timer: null,
        inFlight: false,
        failed: false,
        projectId: entryProjectId,
        shotId,
        promise: null,
        retired: false,
      }
      shotSaveEntriesRef.current.set(key, entry)
    }
    return entry
  }

  const isActiveShot = (shotId: string) => {
    const state = useShotStore.getState()
    const activeId = state.selectedShotId || state.shots[0]?.id || null
    return activeId === shotId
  }

  const canUpdateSaveState = (shotId: string, entryProjectId: string) =>
    mountedRef.current && entryProjectId === useProjectStore.getState().projectId && isActiveShot(shotId)

  const isCurrentShotContext = (entryProjectId: string, shotId: string) =>
    mountedRef.current && entryProjectId === useProjectStore.getState().projectId && isActiveShot(shotId)

  const scheduleShotFlush = (entryProjectId: string, shotId: string, delay = 650) => {
    const entry = getShotSaveEntry(entryProjectId, shotId)
    if (entry.retired) return
    if (entry.timer != null) window.clearTimeout(entry.timer)
    entry.timer = window.setTimeout(() => {
      entry.timer = null
      void flushShotDraftRef.current(entryProjectId, shotId)
    }, delay)
  }

  const flushShotDraft = async (entryProjectId: string, shotId: string) => {
    const key = shotSaveKey(entryProjectId, shotId)
    const entry = shotSaveEntriesRef.current.get(key)
    if (!entry) return true
    if (entry.timer != null) {
      window.clearTimeout(entry.timer)
      entry.timer = null
    }

    const saved = await drainPendingSaves(entry, async (changes) => {
      let shotSaved = false
      const assetChanges: Record<string, any> = {}
      const shotChanges: Record<string, any> = {}
      Object.entries(changes).forEach(([field, value]) => {
        if (field === 'scene_asset_id' || field === 'character_asset_ids') {
          assetChanges[field] = value
        } else {
          shotChanges[field] = value
        }
      })
      if (canUpdateSaveState(shotId, entry.projectId)) setShotSaveState('saving')

      try {
        if (Object.keys(shotChanges).length > 0) {
          await shotApi.update(shotId, shotChanges)
          shotSaved = true
        }
        if (Object.keys(assetChanges).length > 0) {
          if (!entry.projectId) throw new Error('缺少项目上下文，无法保存资产绑定')
          await assetApi.updateShotAssets(shotId, { ...assetChanges, project_id: entry.projectId })
        }
        return !entry.retired
      } catch (err: any) {
        // Keep failed changes queued so a later explicit save/retry cannot lose
        // edits made while the request was in flight. If ordinary fields were
        // persisted but asset validation failed, retry only the asset portion.
        // The queue restores this batch after the callback returns false.
        // Keep only the asset fields if ordinary fields were already saved.
        if (shotSaved) Object.keys(shotChanges).forEach((field) => delete changes[field])
        if (canUpdateSaveState(shotId, entry.projectId)) {
          setShotSaveState('error')
          message.error('镜头更新失败：' + (err?.message || '未知错误'))
        }
        return false
      }
    })

    if (saved && !hasPendingChanges(entry)) {
      if (canUpdateSaveState(shotId, entry.projectId)) {
        setShotDirty(false)
        setShotSaveState('idle')
      }
      if (shotSaveEntriesRef.current.get(key) === entry) shotSaveEntriesRef.current.delete(key)
    } else if (!saved && canUpdateSaveState(shotId, entry.projectId)) {
      setShotDirty(true)
    }
    return saved
  }

  // Keep the ref current so effect cleanups can flush the latest queue even
  // though the component callback itself is recreated on each render.
  flushShotDraftRef.current = flushShotDraft

  const flushAndRetireShotSave = async (entry: ShotSaveEntry) => {
    if (entry.timer != null) {
      window.clearTimeout(entry.timer)
      entry.timer = null
    }
    const saved = await retirePendingSaveAfterFlush(entry, () =>
      flushShotDraftRef.current(entry.projectId, entry.shotId),
    )
    const key = shotSaveKey(entry.projectId, entry.shotId)
    if (saved && shotSaveEntriesRef.current.get(key) === entry) {
      shotSaveEntriesRef.current.delete(key)
    }
    return saved
  }

  const flushProjectBeforeNavigation = (entryProjectId: string) => {
    const existing = navigationFlushRef.current.get(entryProjectId)
    if (existing) return existing

    const operation = (async () => {
      const entries = [...shotSaveEntriesRef.current.values()].filter(
        (entry) => entry.projectId === entryProjectId,
      )
      const results = await Promise.all(entries.map((entry) => flushAndRetireShotSave(entry)))
      const saved = results.every(Boolean)
      if (!saved && mountedRef.current && useProjectStore.getState().projectId === entryProjectId) {
        setShotDirty(true)
        setShotSaveState('error')
        message.error('镜头修改保存失败，已阻止切换。请点击“保存修改”后重试。')
      }
      return saved
    })().finally(() => {
      navigationFlushRef.current.delete(entryProjectId)
    })
    navigationFlushRef.current.set(entryProjectId, operation)
    return operation
  }

  useEffect(() => registerProjectNavigationGuard((fromProjectId) =>
    flushProjectBeforeNavigation(fromProjectId),
  ), [])

  useEffect(() => {
    const preventUnsavedUnload = (event: BeforeUnloadEvent) => {
      const hasUnsavedChanges = [...shotSaveEntriesRef.current.values()].some(
        (entry) => entry.inFlight || hasPendingChanges(entry),
      )
      if (!hasUnsavedChanges) return
      event.preventDefault()
      event.returnValue = ''
    }
    window.addEventListener('beforeunload', preventUnsavedUnload)
    return () => window.removeEventListener('beforeunload', preventUnsavedUnload)
  }, [])

  const queueShotChange = (entryProjectId: string, shotId: string, field: string, value: any) => {
    const currentProjectId = useProjectStore.getState().projectId
    const currentShot = useShotStore.getState().shots.find((shot) => shot.id === shotId)
    if (currentProjectId !== entryProjectId || !currentShot || currentShot.confirmed) {
      if (currentShot?.confirmed && isActiveShot(shotId)) message.warning('已审核锁定的镜头不可修改')
      return false
    }

    if (isActiveShot(shotId)) {
      setShotDraft((draft) => {
        const next = { ...draft, [field]: value }
        shotDraftRef.current = next
        return next
      })
      setShotDirty(true)
      setShotSaveState('dirty')
    }
    // A changed parameter invalidates all generated media immediately. This
    // prevents a stale image/video from remaining visible while the debounced
    // request is pending.
    updateShot(shotId, {
      [field]: value,
      status: 'pending',
      storyboard_status: 'pending',
      image_path: '',
      storyboard_path: '',
      audio_path: '',
      video_path: '',
      confirmed: false,
    })

    const entry = getShotSaveEntry(entryProjectId, shotId)
    entry.retired = false
    entry.failed = false
    entry.pending = { ...entry.pending, [field]: value }
    scheduleShotFlush(entryProjectId, shotId)
    return true
  }

  const draftFromShot = (shot: any) => ({
    visual_notes: shot.visual_notes || '',
    shot_type: shot.shot_type || 'medium',
    emotion: shot.emotion || 'neutral',
    camera_angle: shot.camera_angle || '正面',
    camera_movement: shot.camera_movement || '静止',
    transition: shot.transition || 'cut',
    duration: shot.duration || 3,
    character_asset_ids: shot.character_asset_ids || [],
    scene_asset_id: shot.scene_asset_id || '',
    scene_description: shot.scene_description || '',
    character_action: shot.character_action || '',
    dialogue: shot.dialogue || '',
  })

  useEffect(() => {
    return () => {
      shotSaveEntriesRef.current.forEach((entry) => {
        if (entry.projectId !== projectId) return
        void flushAndRetireShotSave(entry)
      })
    }
  }, [projectId])

  useEffect(() => {
    const nextDraft = selectedShot ? draftFromShot(selectedShot) : {}
    const entry = selectedShot && projectId
      ? shotSaveEntriesRef.current.get(shotSaveKey(projectId, selectedShot.id))
      : undefined
    const hasPendingSave = Boolean(entry && (entry.inFlight || hasPendingChanges(entry)))

    shotDraftRef.current = nextDraft
    setShotDraft(nextDraft)
    setShotDirty(hasPendingSave)
    setShotSaveState(
      entry?.inFlight
        ? 'saving'
        : entry && hasPendingChanges(entry)
          ? entry.failed
            ? 'error'
            : 'dirty'
          : 'idle',
    )

    const shotId = selectedShot?.id
    const entryProjectId = projectId
    return () => {
      if (shotId && entryProjectId) void flushShotDraftRef.current(entryProjectId, shotId)
    }
  }, [selectedShot?.id, projectId])

  useEffect(() => {
    if (!selectedShot || shotDirty) return
    const entry = projectId
      ? shotSaveEntriesRef.current.get(shotSaveKey(projectId, selectedShot.id))
      : undefined
    if (entry?.inFlight || (entry && hasPendingChanges(entry))) return
    const nextDraft = draftFromShot(selectedShot)
    shotDraftRef.current = nextDraft
    setShotDraft(nextDraft)
  }, [selectedShot, shotDirty])

  useEffect(() => {
    return () => {
      shotSaveEntriesRef.current.forEach((entry) => {
        void flushAndRetireShotSave(entry)
      })
    }
  }, [])

  const updateCurrentShot = (changes: Record<string, any>) => {
    const [field, value] = Object.entries(changes)[0] || []
    if (field && projectId && selectedShot) queueShotChange(projectId, selectedShot.id, field, value)
  }

  const buildCurrentShotPrompt = () => {
    if (!selectedShot) return ''
    const characters = selectedCharacters.map((item) => item.name).filter(Boolean).join('、')
    const sceneName = selectedScene?.name || ''
    const parts = [
      `镜头 ${selectedShot.sequence || 1}`,
      `镜头类型：${shotDraft.shot_type ?? selectedShot.shot_type ?? 'medium'}`,
      `情绪：${shotDraft.emotion ?? selectedShot.emotion ?? 'neutral'}`,
      `机位角度：${shotDraft.camera_angle ?? selectedShot.camera_angle ?? '正面'}`,
      `时长：${shotDraft.duration ?? selectedShot.duration ?? 3} 秒`,
      sceneName ? `绑定场景：${sceneName}` : '',
      selectedScene?.visual_prompt ? `场景基准：${selectedScene.visual_prompt}` : '',
      selectedScene?.prop_lock ? `道具锁定：${selectedScene.prop_lock}` : '',
      characters ? `绑定角色：${characters}` : '',
      ...selectedCharacters.flatMap((item) => [
        `角色 ${item.name}：${item.visual_prompt || ''}`,
        item.wardrobe_lock || item.default_outfit ? `服装锁定：${item.wardrobe_lock || item.default_outfit}` : '',
      ]),
      `场景描述：${(shotDraft.scene_description ?? selectedShot.scene_description) || '未填写'}`,
      (shotDraft.character_action ?? selectedShot.character_action) ? `人物动作：${shotDraft.character_action ?? selectedShot.character_action}` : '',
      (shotDraft.dialogue ?? selectedShot.dialogue) ? `对白：${shotDraft.dialogue ?? selectedShot.dialogue}` : '',
      selectedShot.consistency_context ? `一致性约束：${selectedShot.consistency_context}` : '',
      (shotDraft.visual_notes ?? selectedShot.visual_notes) ? `用户补充：${shotDraft.visual_notes ?? selectedShot.visual_notes}` : '',
    ]
    return parts.filter(Boolean).join('\n')
  }

  const fillGenerationPrompt = async () => {
    if (!selectedShot || !projectId) return ''
    const entryProjectId = projectId
    const shotId = selectedShot.id
    const requestId = ++promptRequestRef.current
    const fallback = buildCurrentShotPrompt()
    try {
      setLoadingPrompt(true)
      const result = await shotApi.generationPrompt(shotId)
      if (requestId !== promptRequestRef.current || !isCurrentShotContext(entryProjectId, shotId)) return ''
      const prompt = [
        result.prompt || fallback,
        result.negative_prompt ? `Negative prompt:\n${result.negative_prompt}` : '',
      ].filter(Boolean).join('\n\n')
      queueShotChange(entryProjectId, shotId, 'visual_notes', prompt)
      return prompt
    } catch {
      if (requestId !== promptRequestRef.current || !isCurrentShotContext(entryProjectId, shotId)) return ''
      queueShotChange(entryProjectId, shotId, 'visual_notes', fallback)
      message.warning('完整 Prompt 拉取失败，已回填本地组装版本')
      return fallback
    } finally {
      if (requestId === promptRequestRef.current && mountedRef.current) setLoadingPrompt(false)
    }
  }

  const regenerateCurrentShot = async () => {
    if (!selectedShot || !projectId) return
    if (selectedShot.confirmed) {
      message.warning('已审核锁定的镜头不可重新生成')
      return
    }

    const entryProjectId = projectId
    const shot = selectedShot
    const draft = { ...shotDraft }
    const requestId = ++regenerateRequestRef.current

    const shouldOnlyFillPrompt =
      selectedShot.status === 'needs_review' &&
      !String(shotDraft.visual_notes || '').includes('NON-NEGOTIABLE AGENT CONSISTENCY SOP') &&
      !String(shotDraft.visual_notes || '').includes('locked visual style preset')

    if (shouldOnlyFillPrompt) {
      const prompt = await fillGenerationPrompt()
      if (!prompt || requestId !== regenerateRequestRef.current || !isCurrentShotContext(entryProjectId, shot.id)) return
      message.info('已回填完整生成 Prompt，可编辑后再次点击重新生成')
      return
    }

    const fullPrompt = String(draft.visual_notes || '').trim() || await fillGenerationPrompt()
    if (!fullPrompt || requestId !== regenerateRequestRef.current || !isCurrentShotContext(entryProjectId, shot.id)) return

    try {
      setRegeneratingShot(true)
      setGenerating(true)
      setProgress(48, 'generate_storyboard_images')
      // Flush the debounced editor queue before starting regeneration so the
      // generation request observes the same values shown in the form.
      queueShotChange(entryProjectId, shot.id, 'visual_notes', fullPrompt)
      const saved = await flushShotDraftRef.current(entryProjectId, shot.id)
      if (requestId !== regenerateRequestRef.current || !isCurrentShotContext(entryProjectId, shot.id)) return
      if (!saved) {
        setGenerating(false)
        return
      }
      await shotApi.regenerate(shot.id, {
        prompt: fullPrompt,
        visual_notes: fullPrompt,
        new_scene: draft.scene_description ?? shot.scene_description,
        new_camera_angle: draft.camera_angle ?? shot.camera_angle,
        new_emotion: draft.emotion ?? shot.emotion,
        shot_type: draft.shot_type ?? shot.shot_type,
        character_action: draft.character_action ?? shot.character_action,
        dialogue: draft.dialogue ?? shot.dialogue,
        duration: draft.duration ?? shot.duration,
        reason: fullPrompt,
      })
      if (requestId !== regenerateRequestRef.current || !isCurrentShotContext(entryProjectId, shot.id)) return
      updateShot(shot.id, {
        confirmed: false,
        status: 'pending',
        storyboard_status: 'queued',
        storyboard_path: '',
        image_path: '',
        video_path: '',
        audio_path: '',
      })
      setShotDirty(false)
      setShotSaveState('idle')
      appendLog(`[${new Date().toLocaleTimeString('zh-CN', { hour12: false })}] Shot ${shot.sequence} regeneration submitted`)
      message.success('当前镜头重生成已启动')
    } catch (err: any) {
      if (requestId !== regenerateRequestRef.current || !isCurrentShotContext(entryProjectId, shot.id)) return
      message.error('镜头重生成失败：' + (err.message || '未知错误'))
      setGenerating(false)
    } finally {
      if (requestId === regenerateRequestRef.current && mountedRef.current) setRegeneratingShot(false)
    }
  }

  const logText =
    logs.length > 0
      ? logs.slice(-14).join('\n')
      : isGenerating && currentStep
        ? stepLabels[currentStep] || '处理中'
        : videoPath
          ? '成片已生成，可在主工作区播放'
          : shots.length > 0
            ? `已生成 ${shots.length} 个分镜，等待逐镜审核`
            : '让 Agent 先解析剧本，再生成分镜'

  const consistencySceneRows = [
    { label: '场景组', value: selectedScene?.scene_group_key || selectedShot?.scene_group_id || '待绑定' },
    { label: '时段', value: selectedScene?.time_of_day || '自动锁定' },
    { label: '色温', value: selectedSceneProfile.color_temperature || '生成时固定' },
    { label: '光源', value: selectedSceneProfile.light_source_direction || '生成时固定' },
    { label: '环境权重', value: typeof referenceWeights.environment === 'number' ? referenceWeights.environment.toFixed(2) : '0.40-0.50' },
    { label: '动作权重', value: typeof referenceWeights.action === 'number' ? referenceWeights.action.toFixed(2) : '0.25-0.35' },
    { label: '续帧', value: selectedShot?.continuity_reference_path ? '上一镜头末帧' : '场景基准' },
    { label: '骨骼', value: continuityProfile.openpose_lock || '复杂动作启用' },
  ]

  const blockingRows = [
    { label: '轴线', value: characterBlocking.axis_line || continuityProfile.axis_rule || '180 度轴线锁定' },
    { label: '站位', value: blockingOrder || '按场景基准固定' },
    { label: '视线', value: characterBlocking.eye_line_target || '指向核心主体' },
    { label: '动作', value: characterBlocking.match_on_action_policy || '动作方向连续' },
  ]

  return (
    <aside className={`right-sidebar${collapsed ? ' collapsed' : ''}`} aria-label="右侧运行信息">
      <div className="right-sidebar-head">
        <button type="button" className="collapse-switch" onClick={onToggleCollapsed} aria-label="展开或收起右侧栏">
          {collapsed ? <LeftOutlined /> : <RightOutlined />}
        </button>
      </div>

      {!collapsed && (
        <div className="right-sidebar-content-wrap">
          <div className="right-sidebar-content">
            <div className="right-sidebar-status">
              <span className="right-sidebar-status-label"><FieldTimeOutlined /> 当前步骤</span>
              <strong>{currentStep ? stepLabels[currentStep] || '处理中' : videoPath ? '成片完成' : '待命'}</strong>
            </div>

            <div className="side-panel">
              <button
                type="button"
                className="side-panel-head"
                aria-expanded={shotExpanded}
                aria-controls="right-panel-shot"
                onClick={() => setShotExpanded((prev) => !prev)}
              >
                <span className="side-panel-title"><VideoCameraOutlined /> 镜头属性</span>
                <DownOutlined className={`aux-arrow${shotExpanded ? ' expanded' : ''}`} />
              </button>
              <div id="right-panel-shot" className={`side-panel-body${shotExpanded ? ' expanded' : ''}`}>
                {!selectedShot && <div className="empty-hint">选择一个镜头后可在这里微调。</div>}

                {selectedShot && (
                  <>
                    {selectedShot.confirmed && <div className="locked-shot-note">该镜头已审核锁定，禁止修改参数或重生成。</div>}
                    <div className="form-block">
                      <label className="form-label" htmlFor="shot-visual-notes">镜头 Prompt</label>
                      <TextArea
                        id="shot-visual-notes"
                        aria-label="镜头 Prompt"
                        autoSize={{ minRows: 3, maxRows: 7 }}
                        value={shotDraft.visual_notes || ''}
                        disabled={selectedShot.confirmed}
                        placeholder="补充当前镜头的画面重点、构图、光线或风格细节"
                        onChange={(e) => updateCurrentShot({ visual_notes: e.target.value })}
                      />
                    </div>

                    <div className="form-block">
                      <label className="form-label" htmlFor="shot-type">镜头类型</label>
                      <Input
                        id="shot-type"
                        aria-label="镜头类型"
                        value={shotDraft.shot_type ?? selectedShot.shot_type}
                        disabled={selectedShot.confirmed}
                        size="small"
                        placeholder="wide / medium / close-up"
                        onChange={(e) => updateCurrentShot({ shot_type: e.target.value })}
                      />
                    </div>

                    <div className="form-block">
                      <label className="form-label" htmlFor="shot-emotion">情绪</label>
                      <Input
                        id="shot-emotion"
                        aria-label="情绪"
                        value={shotDraft.emotion ?? selectedShot.emotion}
                        disabled={selectedShot.confirmed}
                        size="small"
                        placeholder="neutral / happy / tense"
                        onChange={(e) => updateCurrentShot({ emotion: e.target.value })}
                      />
                    </div>

                    <div className="form-block">
                      <label className="form-label" htmlFor="shot-camera-angle">机位角度</label>
                      <Input
                        id="shot-camera-angle"
                        aria-label="机位角度"
                        value={shotDraft.camera_angle ?? selectedShot.camera_angle}
                        disabled={selectedShot.confirmed}
                        size="small"
                        placeholder="正面 / 侧面 / 低机位"
                        onChange={(e) => updateCurrentShot({ camera_angle: e.target.value })}
                      />
                    </div>

                    <div className="form-block">
                      <label className="form-label" htmlFor="shot-camera-movement">运镜方式</label>
                      <Select
                        id="shot-camera-movement"
                        aria-label="运镜方式"
                        value={shotDraft.camera_movement ?? selectedShot.camera_movement ?? '静止'}
                        disabled={selectedShot.confirmed}
                        size="small"
                        style={{ width: '100%' }}
                        onChange={(value) => updateCurrentShot({ camera_movement: value })}
                        options={[
                          { value: '静止', label: '静止固定' },
                          { value: '推', label: '推镜（推近）' },
                          { value: '拉', label: '拉镜（拉远）' },
                          { value: '摇', label: '摇镜（横摇）' },
                          { value: '移', label: '移镜（平移）' },
                          { value: '跟', label: '跟镜（跟随）' },
                          { value: '升降', label: '升降镜头' },
                          { value: '环绕', label: '环绕运镜' },
                        ]}
                      />
                    </div>

                    <div className="form-block">
                      <label className="form-label" htmlFor="shot-transition">转场方式</label>
                      <Select
                        id="shot-transition"
                        aria-label="转场方式"
                        value={shotDraft.transition ?? selectedShot.transition ?? 'cut'}
                        disabled={selectedShot.confirmed}
                        size="small"
                        style={{ width: '100%' }}
                        onChange={(value) => updateCurrentShot({ transition: value })}
                        options={[
                          { value: 'cut', label: '硬切 Cut' },
                          { value: 'fade', label: '淡入淡出 Fade' },
                          { value: 'dissolve', label: '叠化 Dissolve' },
                          { value: 'white_flash', label: '白闪 White Flash' },
                          { value: 'push', label: '推拉 Push' },
                          { value: 'wipe', label: '划像 Wipe' },
                        ]}
                      />
                    </div>

                    <div className="form-block">
                      <label className="form-label" htmlFor="shot-duration">时长（秒）</label>
                      <InputNumber
                        id="shot-duration"
                        aria-label="时长（秒）"
                        min={0.5}
                        step={0.5}
                        value={shotDraft.duration ?? selectedShot.duration}
                        style={{ width: '100%' }}
                        size="small"
                        disabled={selectedShot.confirmed}
                        onChange={(value) => {
                          if (typeof value === 'number') {
                            updateCurrentShot({ duration: value })
                          }
                        }}
                      />
                    </div>

                    <div className="form-block">
                      <label className="form-label" htmlFor="shot-character-assets">绑定角色资产</label>
                      <Select
                        id="shot-character-assets"
                        aria-label="绑定角色资产"
                        mode="multiple"
                        value={shotDraft.character_asset_ids ?? selectedShot.character_asset_ids ?? []}
                        disabled={selectedShot.confirmed}
                        size="small"
                        style={{ width: '100%' }}
                        onChange={(value) => updateCurrentShot({ character_asset_ids: value })}
                        options={assetBoard.characters.map((item) => ({ value: item.id, label: item.name }))}
                      />
                    </div>

                    {selectedCharacters.length > 0 && (
                      <div className="bound-asset-list">
                        {selectedCharacters.map((item) => {
                          const refUrl = toOutputUrl(Array.isArray(item.reference_images) ? item.reference_images[0] : '')
                          return (
                            <div className="bound-asset-card" key={item.id}>
                              <div className="bound-asset-thumb">
                                {refUrl ? <img src={refUrl} alt={`${item.name} 三视图`} loading="lazy" decoding="async" /> : <span>三视图待生成</span>}
                              </div>
                              <div className="bound-asset-copy">
                                <strong>{item.name}</strong>
                                <span>{item.personality || '性格待补充'}</span>
                                <em>音色：{item.voice_id || 'Mimo 默认音色'}</em>
                                <em>{item.appearance?.default_outfit || item.appearance?.description || item.visual_prompt || '人设待补充'}</em>
                              </div>
                            </div>
                          )
                        })}
                      </div>
                    )}

                    <div className="form-block">
                      <label className="form-label" htmlFor="shot-scene-asset">绑定场景资产</label>
                      <Select
                        id="shot-scene-asset"
                        aria-label="绑定场景资产"
                        value={(shotDraft.scene_asset_id ?? selectedShot.scene_asset_id) || undefined}
                        size="small"
                        allowClear
                        disabled={selectedShot.confirmed}
                        style={{ width: '100%' }}
                        onChange={(value) => updateCurrentShot({ scene_asset_id: value || '' })}
                        options={assetBoard.scenes.map((item) => ({ value: item.id, label: item.name }))}
                      />
                    </div>

                    {selectedScene && (
                      <div className="bound-asset-card scene-card">
                        <div className="bound-asset-copy">
                          <strong>{selectedScene.name}</strong>
                          <span>{selectedScene.description || '场景描述待补充'}</span>
                          <em>{selectedScene.visual_prompt || '场景视觉提示词待补充'}</em>
                        </div>
                      </div>
                    )}

                    <div className="form-block">
                      <label className="form-label" htmlFor="shot-scene-description">场景描述</label>
                      <TextArea
                        id="shot-scene-description"
                        aria-label="场景描述"
                        autoSize={{ minRows: 3, maxRows: 6 }}
                        value={shotDraft.scene_description ?? selectedShot.scene_description}
                        disabled={selectedShot.confirmed}
                        onChange={(e) => updateCurrentShot({ scene_description: e.target.value })}
                      />
                    </div>

                    <div className="form-block">
                      <label className="form-label" htmlFor="shot-character-action">人物动作</label>
                      <TextArea
                        id="shot-character-action"
                        aria-label="人物动作"
                        autoSize={{ minRows: 2, maxRows: 5 }}
                        value={shotDraft.character_action ?? selectedShot.character_action}
                        disabled={selectedShot.confirmed}
                        onChange={(e) => updateCurrentShot({ character_action: e.target.value })}
                      />
                    </div>

                    <div className="form-block">
                      <label className="form-label" htmlFor="shot-dialogue">对白</label>
                      <TextArea
                        id="shot-dialogue"
                        aria-label="对白"
                        autoSize={{ minRows: 2, maxRows: 5 }}
                        value={shotDraft.dialogue ?? selectedShot.dialogue}
                        disabled={selectedShot.confirmed}
                        onChange={(e) => updateCurrentShot({ dialogue: e.target.value })}
                      />
                    </div>

                    <div className="shot-save-row">
                      <span className="shot-save-state" role="status" aria-live="polite">
                        {shotSaveState === 'saving'
                          ? '保存中…'
                          : shotSaveState === 'error'
                            ? '保存失败，可重试'
                            : shotDirty
                              ? '有未保存修改'
                              : '已保存'}
                      </span>
                      <Button
                        size="small"
                        loading={shotSaveState === 'saving'}
                        disabled={!shotDirty || shotSaveState === 'saving'}
                        onClick={() => projectId && selectedShot && void flushShotDraftRef.current(projectId, selectedShot.id)}
                      >
                        保存修改
                      </Button>
                    </div>

                    <Button
                      type="primary"
                      icon={<ReloadOutlined />}
                      loading={regeneratingShot || loadingPrompt}
                      // Editing invalidates the previous image by design, but
                      // that must not make the regenerate action impossible.
                      // The backend can generate a fresh storyboard from the
                      // current draft without an existing reference file.
                      disabled={selectedShot.confirmed}
                      onClick={() => void regenerateCurrentShot()}
                    >
                      {selectedShot.status === 'needs_review' && !String(shotDraft.visual_notes || '').includes('NON-NEGOTIABLE AGENT CONSISTENCY SOP')
                        ? '回填全量 Prompt'
                        : '按 Prompt 重新生成'}
                    </Button>
                  </>
                )}
              </div>
            </div>

            <div className="side-panel">
              <button
                type="button"
                className="side-panel-head"
                aria-expanded={consistencyExpanded}
                aria-controls="right-panel-consistency"
                onClick={() => setConsistencyExpanded((prev) => !prev)}
              >
                <span className="side-panel-title"><SafetyCertificateOutlined /> 一致性规划</span>
                <DownOutlined className={`aux-arrow${consistencyExpanded ? ' expanded' : ''}`} />
              </button>
              <div id="right-panel-consistency" className={`side-panel-body${consistencyExpanded ? ' expanded' : ''}`}>
                {!selectedShot && <div className="empty-hint">选择镜头后查看 Agent 强制规则。</div>}
                {selectedShot && (
                  <div className="consistency-preview">
                    <div className="consistency-baseline">
                      <div className="consistency-baseline-thumb">
                        {sceneBaselineUrl ? <img src={sceneBaselineUrl} alt="场景基准图" loading="lazy" decoding="async" /> : <span>基准图待生成</span>}
                      </div>
                      <div className="consistency-baseline-copy">
                        <strong>{selectedScene?.name || '未绑定场景'}</strong>
                        <span>{selectedScene?.prop_lock || '道具、光源、透视会在生成时由 Agent 强制锁定。'}</span>
                      </div>
                    </div>

                    <div className="consistency-rule-grid">
                      {consistencySceneRows.map((item) => (
                        <div className="consistency-rule-item" key={item.label}>
                          <span>{item.label}</span>
                          <strong>{item.value}</strong>
                        </div>
                      ))}
                    </div>

                    <div className="consistency-lock-list">
                      {selectedCharacters.length > 0 ? (
                        selectedCharacters.map((item) => (
                          <div className="consistency-lock-row" key={item.id}>
                            <strong>{item.name}</strong>
                            <span>{item.lora_profile || 'LoRA 自动绑定'}</span>
                            <span>{item.ip_adapter_profile || 'IP-Adapter 自动绑定'}</span>
                            <em>{item.wardrobe_lock || item.default_outfit || '穿搭妆容全程锁定'}</em>
                          </div>
                        ))
                      ) : (
                        <div className="empty-hint">角色绑定后会显示身份与穿搭锁定。</div>
                      )}
                    </div>

                    <div className="consistency-blocking-list">
                      {blockingRows.map((item) => (
                        <div className="consistency-blocking-row" key={item.label}>
                          <span>{item.label}</span>
                          <strong>{item.value}</strong>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </div>

            <div className="side-panel">
              <button
                type="button"
                className="side-panel-head"
                aria-expanded={runtimeExpanded}
                aria-controls="right-panel-runtime"
                onClick={() => setRuntimeExpanded((prev) => !prev)}
              >
                <span className="side-panel-title"><SlidersOutlined /> 运行方式</span>
                <DownOutlined className={`aux-arrow${runtimeExpanded ? ' expanded' : ''}`} />
              </button>
              <div id="right-panel-runtime" className={`side-panel-body${runtimeExpanded ? ' expanded' : ''}`}>
                <div className="mode-group">
                  {[
                    { value: 'manual' as const, label: '手动审核' },
                    { value: 'auto' as const, label: '全自动生成' },
                  ].map((mode) => (
                    <button
                      type="button"
                      key={mode.value}
                      className={`mode-chip${runMode === mode.value ? ' active' : ''}`}
                      aria-pressed={runMode === mode.value}
                      onClick={() => setProject({ runMode: mode.value })}
                    >
                      {mode.label}
                    </button>
                  ))}
                </div>
                <div className="mode-hint">
                  {runMode === 'auto'
                    ? '提交解析后由 LangGraph 端到端跑完故事板、逐镜视频与成片合成，过程不暂停审核。'
                    : '每个阶段生成后暂停，等待你确认素材、逐镜审核故事板再继续。'}
                </div>
              </div>
            </div>

            <div className="side-panel">
              <button
                type="button"
                className="side-panel-head"
                aria-expanded={flowExpanded}
                aria-controls="right-panel-flow"
                onClick={() => setFlowExpanded((prev) => !prev)}
              >
                <span className="side-panel-title"><ApartmentOutlined /> 执行流程</span>
                <DownOutlined className={`aux-arrow${flowExpanded ? ' expanded' : ''}`} />
              </button>
              <div id="right-panel-flow" className={`side-panel-body${flowExpanded ? ' expanded' : ''}`}>
                <React.Suspense fallback={<span className="lazy-panel-status" role="status">正在加载流程...</span>}>
                  <FlowGraph compact />
                </React.Suspense>
              </div>
            </div>

            <div className="side-panel">
              <button
                type="button"
                className="side-panel-head"
                aria-expanded={logsExpanded}
                aria-controls="right-panel-logs"
                onClick={() => setLogsExpanded((prev) => !prev)}
              >
                <span className="side-panel-title"><CodeOutlined /> 运行日志</span>
                <DownOutlined className={`aux-arrow${logsExpanded ? ' expanded' : ''}`} />
              </button>
              <div id="right-panel-logs" className={`side-panel-body${logsExpanded ? ' expanded' : ''}`}>
                <div className="log-pane">{logText}</div>
              </div>
            </div>
          </div>
        </div>
      )}
    </aside>
  )
}

export default RightSidebar

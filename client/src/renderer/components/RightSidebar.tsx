import React, { useEffect, useMemo, useState } from 'react'
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
import { Button, Input, InputNumber, message, Select } from 'antd'
import FlowGraph from './FlowGraph'
import { API_OUTPUT_BASE, assetApi, shotApi } from '../services/api'
import { useProjectStore } from '../stores/projectStore'
import { useShotStore } from '../stores/shotStore'

const { TextArea } = Input

function toOutputUrl(imagePath?: string) {
  if (!imagePath) return null
  const relative = imagePath.replace(/^.*output[\\/]/, '').replace(/\\/g, '/')
  return `${API_OUTPUT_BASE}${relative}`
}

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
  const [promptDraft, setPromptDraft] = useState('')

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
    if (!projectId) {
      setAssetBoard({ characters: [], scenes: [] })
      return
    }
    assetApi.board(projectId)
      .then((board) => setAssetBoard({ characters: board.characters || [], scenes: board.scenes || [] }))
      .catch(() => undefined)
  }, [projectId])

  useEffect(() => {
    setPromptDraft(selectedShot?.visual_notes || '')
  }, [selectedShot?.id, selectedShot?.visual_notes])

  const updateCurrentShot = async (changes: Record<string, any>) => {
    if (!selectedShot) return
    if (selectedShot.confirmed) {
      message.warning('已审核锁定的镜头不可修改')
      return
    }

    updateShot(selectedShot.id, {
      ...changes,
      status: 'pending',
      audio_path: '',
      video_path: '',
      confirmed: false,
    })
    try {
      await shotApi.update(selectedShot.id, changes)
    } catch (err: any) {
      message.error('镜头更新失败：' + (err.message || '未知错误'))
    }
  }

  const buildCurrentShotPrompt = () => {
    if (!selectedShot) return ''
    const characters = selectedCharacters.map((item) => item.name).filter(Boolean).join('、')
    const sceneName = selectedScene?.name || ''
    const parts = [
      `镜头 ${selectedShot.sequence || 1}`,
      `镜头类型：${selectedShot.shot_type || 'medium'}`,
      `情绪：${selectedShot.emotion || 'neutral'}`,
      `机位角度：${selectedShot.camera_angle || '正面'}`,
      `时长：${selectedShot.duration || 3} 秒`,
      sceneName ? `绑定场景：${sceneName}` : '',
      selectedScene?.visual_prompt ? `场景基准：${selectedScene.visual_prompt}` : '',
      selectedScene?.prop_lock ? `道具锁定：${selectedScene.prop_lock}` : '',
      characters ? `绑定角色：${characters}` : '',
      ...selectedCharacters.flatMap((item) => [
        `角色 ${item.name}：${item.visual_prompt || ''}`,
        item.wardrobe_lock || item.default_outfit ? `服装锁定：${item.wardrobe_lock || item.default_outfit}` : '',
      ]),
      `场景描述：${selectedShot.scene_description || '未填写'}`,
      selectedShot.character_action ? `人物动作：${selectedShot.character_action}` : '',
      selectedShot.dialogue ? `对白：${selectedShot.dialogue}` : '',
      selectedShot.consistency_context ? `一致性约束：${selectedShot.consistency_context}` : '',
      selectedShot.visual_notes ? `用户补充：${selectedShot.visual_notes}` : '',
    ]
    return parts.filter(Boolean).join('\n')
  }

  const fillGenerationPrompt = async () => {
    if (!selectedShot) return ''
    try {
      setLoadingPrompt(true)
      const result = await shotApi.generationPrompt(selectedShot.id)
      const prompt = [
        result.prompt || buildCurrentShotPrompt(),
        result.negative_prompt ? `Negative prompt:\n${result.negative_prompt}` : '',
      ].filter(Boolean).join('\n\n')
      setPromptDraft(prompt)
      updateShot(selectedShot.id, { visual_notes: prompt })
      return prompt
    } catch {
      const fallback = buildCurrentShotPrompt()
      setPromptDraft(fallback)
      updateShot(selectedShot.id, { visual_notes: fallback })
      message.warning('完整 Prompt 拉取失败，已回填本地组装版本')
      return fallback
    } finally {
      setLoadingPrompt(false)
    }
  }

  const regenerateCurrentShot = async () => {
    if (!selectedShot || !projectId) return
    if (selectedShot.confirmed) {
      message.warning('已审核锁定的镜头不可重新生成')
      return
    }

    const shouldOnlyFillPrompt =
      selectedShot.status === 'needs_review' &&
      !promptDraft.includes('NON-NEGOTIABLE AGENT CONSISTENCY SOP') &&
      !promptDraft.includes('locked visual style preset')

    if (shouldOnlyFillPrompt) {
      await fillGenerationPrompt()
      message.info('已回填完整生成 Prompt，可编辑后再次点击重新生成')
      return
    }

    const fullPrompt = promptDraft.trim() || await fillGenerationPrompt()
    updateShot(selectedShot.id, { visual_notes: fullPrompt })

    try {
      setRegeneratingShot(true)
      setGenerating(true)
      setProgress(48, 'generate_storyboard_images')
      await shotApi.update(selectedShot.id, { visual_notes: fullPrompt })
      await shotApi.regenerate(selectedShot.id, {
        prompt: fullPrompt,
        visual_notes: fullPrompt,
        new_scene: selectedShot.scene_description,
        new_camera_angle: selectedShot.camera_angle,
        new_emotion: selectedShot.emotion,
        shot_type: selectedShot.shot_type,
        character_action: selectedShot.character_action,
        dialogue: selectedShot.dialogue,
        duration: selectedShot.duration,
        reason: fullPrompt,
      })
      updateShot(selectedShot.id, {
        confirmed: false,
        status: 'pending',
        storyboard_status: 'queued',
        storyboard_path: '',
        image_path: '',
        video_path: '',
        audio_path: '',
      })
      appendLog(`[${new Date().toLocaleTimeString('zh-CN', { hour12: false })}] Shot ${selectedShot.sequence} regeneration submitted`)
      message.success('当前镜头重生成已启动')
    } catch (err: any) {
      message.error('镜头重生成失败：' + (err.message || '未知错误'))
      setGenerating(false)
    } finally {
      setRegeneratingShot(false)
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
              <button type="button" className="side-panel-head" onClick={() => setShotExpanded((prev) => !prev)}>
                <span className="side-panel-title"><VideoCameraOutlined /> 镜头属性</span>
                <DownOutlined className={`aux-arrow${shotExpanded ? ' expanded' : ''}`} />
              </button>
              <div className={`side-panel-body${shotExpanded ? ' expanded' : ''}`}>
                {!selectedShot && <div className="empty-hint">选择一个镜头后可在这里微调。</div>}

                {selectedShot && (
                  <>
                    {selectedShot.confirmed && <div className="locked-shot-note">该镜头已审核锁定，禁止修改参数或重生成。</div>}
                    <div className="form-block">
                      <label className="form-label">镜头 Prompt</label>
                      <TextArea
                        autoSize={{ minRows: 3, maxRows: 7 }}
                        value={promptDraft}
                        disabled={selectedShot.confirmed}
                        placeholder="补充当前镜头的画面重点、构图、光线或风格细节"
                        onChange={(e) => setPromptDraft(e.target.value)}
                      />
                    </div>

                    <div className="form-block">
                      <label className="form-label">镜头类型</label>
                      <Input
                        value={selectedShot.shot_type}
                        disabled={selectedShot.confirmed}
                        size="small"
                        placeholder="wide / medium / close-up"
                        onChange={(e) => void updateCurrentShot({ shot_type: e.target.value })}
                      />
                    </div>

                    <div className="form-block">
                      <label className="form-label">情绪</label>
                      <Input
                        value={selectedShot.emotion}
                        disabled={selectedShot.confirmed}
                        size="small"
                        placeholder="neutral / happy / tense"
                        onChange={(e) => void updateCurrentShot({ emotion: e.target.value })}
                      />
                    </div>

                    <div className="form-block">
                      <label className="form-label">机位角度</label>
                      <Input
                        value={selectedShot.camera_angle}
                        disabled={selectedShot.confirmed}
                        size="small"
                        placeholder="正面 / 侧面 / 低机位"
                        onChange={(e) => void updateCurrentShot({ camera_angle: e.target.value })}
                      />
                    </div>

                    <div className="form-block">
                      <label className="form-label">运镜方式</label>
                      <Select
                        value={selectedShot.camera_movement || '静止'}
                        disabled={selectedShot.confirmed}
                        size="small"
                        style={{ width: '100%' }}
                        onChange={(value) => void updateCurrentShot({ camera_movement: value })}
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
                      <label className="form-label">转场方式</label>
                      <Select
                        value={selectedShot.transition || 'cut'}
                        disabled={selectedShot.confirmed}
                        size="small"
                        style={{ width: '100%' }}
                        onChange={(value) => void updateCurrentShot({ transition: value })}
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
                      <label className="form-label">时长（秒）</label>
                      <InputNumber
                        min={0.5}
                        step={0.5}
                        value={selectedShot.duration}
                        style={{ width: '100%' }}
                        size="small"
                        disabled={selectedShot.confirmed}
                        onChange={(value) => {
                          if (typeof value === 'number') {
                            void updateCurrentShot({ duration: value })
                          }
                        }}
                      />
                    </div>

                    <div className="form-block">
                      <label className="form-label">绑定角色资产</label>
                      <Select
                        mode="multiple"
                        value={selectedShot.character_asset_ids || []}
                        disabled={selectedShot.confirmed}
                        size="small"
                        style={{ width: '100%' }}
                        onChange={(value) => void updateCurrentShot({ character_asset_ids: value })}
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
                                {refUrl ? <img src={refUrl} alt={`${item.name} 三视图`} /> : <span>三视图待生成</span>}
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
                      <label className="form-label">绑定场景资产</label>
                      <Select
                        value={selectedShot.scene_asset_id || undefined}
                        size="small"
                        allowClear
                        disabled={selectedShot.confirmed}
                        style={{ width: '100%' }}
                        onChange={(value) => void updateCurrentShot({ scene_asset_id: value || '' })}
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
                      <label className="form-label">场景描述</label>
                      <TextArea
                        autoSize={{ minRows: 3, maxRows: 6 }}
                        value={selectedShot.scene_description}
                        disabled={selectedShot.confirmed}
                        onChange={(e) => void updateCurrentShot({ scene_description: e.target.value })}
                      />
                    </div>

                    <div className="form-block">
                      <label className="form-label">人物动作</label>
                      <TextArea
                        autoSize={{ minRows: 2, maxRows: 5 }}
                        value={selectedShot.character_action}
                        disabled={selectedShot.confirmed}
                        onChange={(e) => void updateCurrentShot({ character_action: e.target.value })}
                      />
                    </div>

                    <div className="form-block">
                      <label className="form-label">对白</label>
                      <TextArea
                        autoSize={{ minRows: 2, maxRows: 5 }}
                        value={selectedShot.dialogue}
                        disabled={selectedShot.confirmed}
                        onChange={(e) => void updateCurrentShot({ dialogue: e.target.value })}
                      />
                    </div>

                    <Button
                      type="primary"
                      icon={<ReloadOutlined />}
                      loading={regeneratingShot || loadingPrompt}
                      disabled={selectedShot.confirmed || !(selectedShot.storyboard_path || selectedShot.image_path)}
                      onClick={() => void regenerateCurrentShot()}
                    >
                      {selectedShot.status === 'needs_review' && !promptDraft.includes('NON-NEGOTIABLE AGENT CONSISTENCY SOP')
                        ? '回填全量 Prompt'
                        : '按 Prompt 重新生成'}
                    </Button>
                  </>
                )}
              </div>
            </div>

            <div className="side-panel">
              <button type="button" className="side-panel-head" onClick={() => setConsistencyExpanded((prev) => !prev)}>
                <span className="side-panel-title"><SafetyCertificateOutlined /> 一致性规划</span>
                <DownOutlined className={`aux-arrow${consistencyExpanded ? ' expanded' : ''}`} />
              </button>
              <div className={`side-panel-body${consistencyExpanded ? ' expanded' : ''}`}>
                {!selectedShot && <div className="empty-hint">选择镜头后查看 Agent 强制规则。</div>}
                {selectedShot && (
                  <div className="consistency-preview">
                    <div className="consistency-baseline">
                      <div className="consistency-baseline-thumb">
                        {sceneBaselineUrl ? <img src={sceneBaselineUrl} alt="场景基准图" /> : <span>基准图待生成</span>}
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
              <button type="button" className="side-panel-head" onClick={() => setRuntimeExpanded((prev) => !prev)}>
                <span className="side-panel-title"><SlidersOutlined /> 运行方式</span>
                <DownOutlined className={`aux-arrow${runtimeExpanded ? ' expanded' : ''}`} />
              </button>
              <div className={`side-panel-body${runtimeExpanded ? ' expanded' : ''}`}>
                <div className="mode-group">
                  {[
                    { value: 'manual' as const, label: '手动审核' },
                    { value: 'auto' as const, label: '全自动生成' },
                  ].map((mode) => (
                    <button
                      type="button"
                      key={mode.value}
                      className={`mode-chip${runMode === mode.value ? ' active' : ''}`}
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
              <button type="button" className="side-panel-head" onClick={() => setFlowExpanded((prev) => !prev)}>
                <span className="side-panel-title"><ApartmentOutlined /> 执行流程</span>
                <DownOutlined className={`aux-arrow${flowExpanded ? ' expanded' : ''}`} />
              </button>
              <div className={`side-panel-body${flowExpanded ? ' expanded' : ''}`}>
                <FlowGraph compact />
              </div>
            </div>

            <div className="side-panel">
              <button type="button" className="side-panel-head" onClick={() => setLogsExpanded((prev) => !prev)}>
                <span className="side-panel-title"><CodeOutlined /> 运行日志</span>
                <DownOutlined className={`aux-arrow${logsExpanded ? ' expanded' : ''}`} />
              </button>
              <div className={`side-panel-body${logsExpanded ? ' expanded' : ''}`}>
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

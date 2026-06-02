import React, { useEffect, useState } from 'react'
import { DownOutlined, LeftOutlined, RightOutlined } from '@ant-design/icons'
import { Input, InputNumber, message, Select } from 'antd'
import FlowGraph from './FlowGraph'
import { API_OUTPUT_BASE, assetApi, shotApi } from '../services/api'
import { useProjectStore } from '../stores/projectStore'
import { useShotStore } from '../stores/shotStore'

const { TextArea } = Input

const modeOptions = ['逐镜头审核', '手动微调', '全部完成后合成']

function toOutputUrl(imagePath?: string) {
  if (!imagePath) return null
  const relative = imagePath.replace(/^.*output[\\/]/, '').replace(/\\/g, '/')
  return `${API_OUTPUT_BASE}${relative}`
}

const stepLabels: Record<string, string> = {
  generate_script: '剧本生成',
  parse_script: '剧本解析',
  generate_storyboard: '分镜生成',
  wait_asset_confirm: '素材确认',
  generate_storyboard_images: '定稿故事板',
  wait_storyboard_approval: '单镜头审核',
  phase2_start: '视频阶段',
  generate_voice: 'Mimo 配音',
  generate_seedance_video: 'Seedance 单镜头视频',
  compose_video: '视频合成',
  quality_check: '质量校验',
  rendering: '导出渲染',
}

interface RightSidebarProps {
  collapsed: boolean
  onToggleCollapsed: () => void
}

const RightSidebar: React.FC<RightSidebarProps> = ({ collapsed, onToggleCollapsed }) => {
  const { updateShot, logs, isGenerating, currentStep, shots, videoPath } = useShotStore()
  const { projectId } = useProjectStore()
  const [runMode, setRunMode] = useState('逐镜头审核')
  const [assetBoard, setAssetBoard] = useState<{ characters: any[]; scenes: any[] }>({ characters: [], scenes: [] })
  const [shotExpanded, setShotExpanded] = useState(true)
  const [runtimeExpanded, setRuntimeExpanded] = useState(true)
  const [consistencyExpanded, setConsistencyExpanded] = useState(true)
  const [flowExpanded, setFlowExpanded] = useState(false)
  const [logsExpanded, setLogsExpanded] = useState(true)

  const selectedShot = useShotStore((state) => {
    const id = state.selectedShotId
    return state.shots.find((shot) => shot.id === id) || state.shots[0]
  })

  const selectedCharacters = selectedShot
    ? assetBoard.characters.filter((item) => (selectedShot.character_asset_ids || []).includes(item.id))
    : []
  const selectedScene = selectedShot
    ? assetBoard.scenes.find((item) => item.id === selectedShot.scene_asset_id)
    : null
  const selectedSceneProfile = selectedScene?.consistency_profile || {}
  const sceneBaselineUrl = toOutputUrl(selectedScene?.baseline_image_path || selectedScene?.reference_images?.[0] || '')
  const referenceWeights = selectedShot?.reference_weights || {}
  const continuityProfile = selectedShot?.continuity_profile || {}
  const characterBlocking = continuityProfile.character_blocking || {}
  const blockingOrder = Array.isArray(characterBlocking.character_order_left_to_right)
    ? characterBlocking.character_order_left_to_right.filter(Boolean).join(' / ')
    : ''
  const blockingRows = [
    { label: '轴线', value: characterBlocking.axis_line || continuityProfile.axis_rule || '180度轴线锁定' },
    { label: '站位', value: blockingOrder || '按场景基准固定' },
    { label: '视线', value: characterBlocking.eye_line_target || '指向下一镜头核心主体' },
    { label: '动接动', value: characterBlocking.match_on_action_policy || '动作方向连续' },
    { label: '机位', value: characterBlocking.camera_movement_limit || '同场景仅小幅变焦' },
    { label: '光影', value: characterBlocking.skin_light_integration || '人物肤色和阴影匹配场景光' },
  ]
  const consistencySceneRows = [
    { label: '场景组', value: selectedScene?.scene_group_key || selectedShot?.scene_group_id || '待绑定' },
    { label: '时段', value: selectedScene?.time_of_day || '自动锁定' },
    { label: '色温', value: selectedSceneProfile.color_temperature || '生成时强制固定' },
    { label: '光源', value: selectedSceneProfile.light_source_direction || '生成时强制固定' },
    { label: '转场', value: selectedSceneProfile.transition_same_scene || '硬切 / 0.2s 淡入淡出' },
    { label: '环境权重', value: typeof referenceWeights.environment === 'number' ? referenceWeights.environment.toFixed(2) : '0.40-0.50' },
    { label: '动作权重', value: typeof referenceWeights.action === 'number' ? referenceWeights.action.toFixed(2) : '0.25-0.35' },
    { label: '续帧', value: selectedShot?.continuity_reference_path ? '上一镜头末帧' : '场景基准' },
    { label: '骨骼', value: continuityProfile.openpose_lock || '复杂动作启用' },
    { label: '景深', value: continuityProfile.depth_lock || '复杂动作启用' },
  ]

  useEffect(() => {
    if (!projectId) {
      setAssetBoard({ characters: [], scenes: [] })
      return
    }
    assetApi.board(projectId)
      .then((board) => setAssetBoard({ characters: board.characters || [], scenes: board.scenes || [] }))
      .catch(() => undefined)
  }, [projectId])

  const updateCurrentShot = async (changes: Record<string, any>) => {
    if (!selectedShot) return
    if (selectedShot.confirmed) {
      message.warning('已审批锁定的镜头不可改动')
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

  const logText =
    logs.length > 0
      ? logs.slice(-14).join('\n')
      : isGenerating && currentStep
        ? stepLabels[currentStep] || '处理中'
        : videoPath
          ? '成片已生成，可在主工作区播放'
          : shots.length > 0
            ? `已生成 ${shots.length} 个分镜，等待逐镜头审核`
            : '让 Agent 先写剧本，再生成分镜'

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
              <span>当前步骤</span>
              <strong>{currentStep ? stepLabels[currentStep] || '处理中' : videoPath ? '成片完成' : '待命'}</strong>
            </div>

            <div className="side-panel">
              <button type="button" className="side-panel-head" onClick={() => setShotExpanded((prev) => !prev)}>
                <span>镜头属性</span>
                <DownOutlined className={`aux-arrow${shotExpanded ? ' expanded' : ''}`} />
              </button>
              <div className={`side-panel-body${shotExpanded ? ' expanded' : ''}`}>
                {!selectedShot && <div className="empty-hint">选择一个镜头后可在这里微调。</div>}

                {selectedShot && (
                  <>
                    {selectedShot.confirmed && (
                      <div className="locked-shot-note">该镜头已审批锁定，禁止修改参数或重生成。</div>
                    )}
                    <div className="form-block">
                      <label className="form-label">镜头类型</label>
                      <Select
                        value={selectedShot.shot_type}
                        disabled={selectedShot.confirmed}
                        size="small"
                        style={{ width: '100%' }}
                        onChange={(value) => void updateCurrentShot({ shot_type: value })}
                        options={[
                          { value: 'wide', label: '全景' },
                          { value: 'medium', label: '中景' },
                          { value: 'close-up', label: '近景' },
                          { value: 'extreme_close', label: '特写' },
                        ]}
                      />
                    </div>

                    <div className="form-block">
                      <label className="form-label">情绪</label>
                      <Select
                        value={selectedShot.emotion}
                        disabled={selectedShot.confirmed}
                        size="small"
                        style={{ width: '100%' }}
                        onChange={(value) => void updateCurrentShot({ emotion: value })}
                        options={[
                          { value: 'neutral', label: '平静' },
                          { value: 'happy', label: '开心' },
                          { value: 'shy', label: '害羞' },
                          { value: 'sad', label: '悲伤' },
                          { value: 'angry', label: '愤怒' },
                          { value: 'surprised', label: '惊讶' },
                        ]}
                      />
                    </div>

                    <div className="form-block">
                      <label className="form-label">机位角度</label>
                      <Select
                        value={selectedShot.camera_angle}
                        disabled={selectedShot.confirmed}
                        size="small"
                        style={{ width: '100%' }}
                        onChange={(value) => void updateCurrentShot({ camera_angle: value })}
                        options={[
                          { value: '正面', label: '正面' },
                          { value: '侧面', label: '侧面' },
                          { value: '俯视', label: '俯视' },
                          { value: '仰视', label: '仰视' },
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
                      <label className="form-label">对白</label>
                      <TextArea
                        autoSize={{ minRows: 2, maxRows: 5 }}
                        value={selectedShot.dialogue}
                        disabled={selectedShot.confirmed}
                        onChange={(e) => void updateCurrentShot({ dialogue: e.target.value })}
                      />
                    </div>
                  </>
                )}
              </div>
            </div>

            <div className="side-panel">
              <button type="button" className="side-panel-head" onClick={() => setConsistencyExpanded((prev) => !prev)}>
                <span>一致性规则</span>
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
                        <div className="empty-hint">角色绑定后会显示 LoRA / IP-Adapter / 穿搭锁定。</div>
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

                    <div className="consistency-rule-note">
                      单镜头自定义参数不会覆盖场景锚定、角色身份、180度轴线、续帧和统一后期规则。
                    </div>
                  </div>
                )}
              </div>
            </div>

            <div className="side-panel">
              <button type="button" className="side-panel-head" onClick={() => setRuntimeExpanded((prev) => !prev)}>
                <span>运行方式</span>
                <DownOutlined className={`aux-arrow${runtimeExpanded ? ' expanded' : ''}`} />
              </button>
              <div className={`side-panel-body${runtimeExpanded ? ' expanded' : ''}`}>
                <div className="mode-group">
                  {modeOptions.map((mode) => (
                    <button
                      type="button"
                      key={mode}
                      className={`mode-chip${runMode === mode ? ' active' : ''}`}
                      onClick={() => setRunMode(mode)}
                    >
                      {mode}
                    </button>
                  ))}
                </div>
              </div>
            </div>

            <div className="side-panel">
              <button type="button" className="side-panel-head" onClick={() => setFlowExpanded((prev) => !prev)}>
                <span>执行流程</span>
                <DownOutlined className={`aux-arrow${flowExpanded ? ' expanded' : ''}`} />
              </button>
              <div className={`side-panel-body${flowExpanded ? ' expanded' : ''}`}>
                <FlowGraph compact />
              </div>
            </div>

            <div className="side-panel">
              <button type="button" className="side-panel-head" onClick={() => setLogsExpanded((prev) => !prev)}>
                <span>运行日志</span>
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

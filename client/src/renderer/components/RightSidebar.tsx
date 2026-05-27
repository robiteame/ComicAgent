import React, { useState } from 'react'
import { DownOutlined, MenuFoldOutlined, MenuUnfoldOutlined } from '@ant-design/icons'
import { Input, InputNumber, message, Select } from 'antd'
import FlowGraph from './FlowGraph'
import { shotApi } from '../services/api'
import { useShotStore } from '../stores/shotStore'

const { TextArea } = Input

const modeOptions = ['全自动', '确认分镜后继续', '手动微调']

const stepLabels: Record<string, string> = {
  generate_script: '剧本生成',
  parse_script: '剧本解析',
  generate_storyboard: '分镜生成',
  generate_reference_images: '参考画面',
  wait_storyboard_confirm: '等待确认',
  phase2_start: '开始成片',
  generate_images: '镜头渲染',
  generate_voice: '音频合成',
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
  const [runMode, setRunMode] = useState('确认分镜后继续')
  const [shotExpanded, setShotExpanded] = useState(true)
  const [runtimeExpanded, setRuntimeExpanded] = useState(true)
  const [flowExpanded, setFlowExpanded] = useState(false)
  const [logsExpanded, setLogsExpanded] = useState(true)

  const selectedShot = useShotStore((state) => {
    const id = state.selectedShotId
    return state.shots.find((shot) => shot.id === id) || state.shots[0]
  })

  const updateCurrentShot = async (changes: Record<string, any>) => {
    if (!selectedShot) return

    updateShot(selectedShot.id, { ...changes, status: 'pending', audio_path: '', confirmed: false })
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
            ? `已生成 ${shots.length} 个分镜，等待确认`
            : '让 Agent 先写剧本，再生成分镜'

  return (
    <aside className={`right-sidebar${collapsed ? ' collapsed' : ''}`} aria-label="右侧运行信息">
      <div className="right-sidebar-head">
        <button type="button" className="collapse-switch" onClick={onToggleCollapsed} aria-label="展开或收起右侧栏">
          {collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
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
                    <div className="form-block">
                      <label className="form-label">镜头类型</label>
                      <Select
                        value={selectedShot.shot_type}
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
                        onChange={(value) => {
                          if (typeof value === 'number') {
                            void updateCurrentShot({ duration: value })
                          }
                        }}
                      />
                    </div>

                    <div className="form-block">
                      <label className="form-label">场景描述</label>
                      <TextArea
                        autoSize={{ minRows: 3, maxRows: 6 }}
                        value={selectedShot.scene_description}
                        onChange={(e) => void updateCurrentShot({ scene_description: e.target.value })}
                      />
                    </div>

                    <div className="form-block">
                      <label className="form-label">对白</label>
                      <TextArea
                        autoSize={{ minRows: 2, maxRows: 5 }}
                        value={selectedShot.dialogue}
                        onChange={(e) => void updateCurrentShot({ dialogue: e.target.value })}
                      />
                    </div>
                  </>
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

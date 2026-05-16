import React, { useState } from 'react'
import { Select, Button, message } from 'antd'
import { useProjectStore } from '../stores/projectStore'
import { useShotStore } from '../stores/shotStore'

const modeOptions = ['全自动', '半自动干预', '手动']

const RightSidebar: React.FC = () => {
  const { style, setProject, resolution, setProject: updateProject } = useProjectStore()
  const { isGenerating, currentStep, shots } = useShotStore()
  const [runMode, setRunMode] = useState('半自动干预')

  const selectedShot = useShotStore((s) => {
    const id = s.selectedShotId
    return s.shots.find((sh) => sh.id === id) || s.shots[0]
  })

  const labelStyle: React.CSSProperties = {
    display: 'block',
    fontSize: 12,
    color: 'var(--text)',
    marginBottom: 6,
  }

  const stepLabels: Record<string, string> = {
    script_parse: '剧本解析完成',
    storyboard: '正在生成分镜脚本',
    character: '正在生成角色',
    render: '正在渲染画面',
    audio: '正在生成配音',
  }

  return (
    <div style={{
      width: 300,
      background: 'var(--bg)',
      borderLeft: '1px solid var(--border)',
      padding: 16,
      overflowY: 'auto',
      flexShrink: 0,
    }}>
      {/* 风格设置 */}
      <div className="section-title">风格设置</div>
      <div style={{ marginBottom: 18 }}>
        <label style={labelStyle}>画风</label>
        <Select
          value={style}
          onChange={(v) => setProject({ style: v })}
          style={{ width: '100%' }}
          size="small"
          options={[
            { value: 'anime', label: '日系写实漫' },
            { value: 'chinese', label: '国漫厚涂' },
            { value: 'chibi', label: '简约条漫' },
            { value: 'realistic', label: '写实风格' },
          ]}
        />
      </div>
      <div style={{ marginBottom: 18 }}>
        <label style={labelStyle}>分辨率</label>
        <Select
          value={resolution}
          onChange={(v) => setProject({ resolution: v })}
          style={{ width: '100%' }}
          size="small"
          options={[
            { value: '720p', label: '720P' },
            { value: '1080p', label: '1080P' },
            { value: '2k', label: '2K' },
            { value: '4k', label: '4K' },
          ]}
        />
      </div>

      {/* Agent 运行模式 */}
      <div className="section-title" style={{ marginTop: 22 }}>Agent 运行模式</div>
      <div style={{ display: 'flex', gap: 6, marginTop: 6, marginBottom: 18 }}>
        {modeOptions.map((mode) => (
          <div
            key={mode}
            onClick={() => setRunMode(mode)}
            style={{
              padding: '5px 10px',
              background: runMode === mode ? 'var(--accent)' : '#f0f0f0',
              borderRadius: 'var(--radius-sm)',
              fontSize: 12,
              color: runMode === mode ? '#fff' : 'var(--text)',
              cursor: 'pointer',
              transition: 'all 120ms var(--ease)',
              whiteSpace: 'nowrap',
            }}
          >
            {mode}
          </div>
        ))}
      </div>

      {/* 镜头控制 */}
      <div className="section-title" style={{ marginTop: 22 }}>镜头控制</div>
      <div style={{ marginBottom: 18 }}>
        <label style={labelStyle}>运镜方式</label>
        <Select
          defaultValue="fixed"
          style={{ width: '100%' }}
          size="small"
          options={[
            { value: 'fixed', label: '固定镜头' },
            { value: 'pan', label: '缓慢推拉' },
            { value: 'zoom', label: '缩放' },
          ]}
        />
      </div>

      {/* 当前镜头信息 */}
      {selectedShot && (
        <>
          <div className="section-title" style={{ marginTop: 22 }}>当前镜头</div>
          <div style={{
            padding: '8px 10px',
            background: 'var(--bg-white)',
            borderRadius: 'var(--radius)',
            fontSize: 12,
            color: 'var(--text)',
            boxShadow: 'var(--shadow-sm)',
            marginBottom: 12,
            lineHeight: 1.6,
          }}>
            <div style={{ marginBottom: 4 }}>
              <span style={{ color: 'var(--text-secondary)' }}>类型：</span>
              {selectedShot.shot_type === 'wide' ? '全景' :
               selectedShot.shot_type === 'medium' ? '中景' :
               selectedShot.shot_type === 'close-up' ? '近景' : '特写'}
              <span style={{ marginLeft: 10, color: 'var(--text-secondary)' }}>角度：</span>
              {selectedShot.camera_angle}
            </div>
            <div>
              <span style={{ color: 'var(--text-secondary)' }}>情绪：</span>
              {selectedShot.emotion}
              <span style={{ marginLeft: 10, color: 'var(--text-secondary)' }}>时长：</span>
              {selectedShot.duration}s
            </div>
          </div>
        </>
      )}

      {/* 运行日志 */}
      <div className="section-title" style={{ marginTop: 22 }}>运行日志</div>
      <div style={{
        padding: 8,
        background: 'var(--bg-canvas)',
        borderRadius: 'var(--radius)',
        fontSize: 12,
        color: 'var(--text-secondary)',
        border: '1px solid var(--border)',
        lineHeight: 1.6,
        minHeight: 48,
      }}>
        {isGenerating && currentStep
          ? stepLabels[currentStep] || `当前步骤: ${currentStep}`
          : shots.length > 0
            ? `已完成 · ${shots.length} 个镜头`
            : '等待输入剧本...'
        }
      </div>
    </div>
  )
}

export default RightSidebar

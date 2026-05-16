import React, { useEffect, useState } from 'react'
import { useProjectStore } from '../stores/projectStore'
import { useShotStore } from '../stores/shotStore'
import { projectApi } from '../services/api'

interface ProjectItem {
  id: string
  title: string
  status: string
}

const agentSteps = [
  { label: '剧本解析', key: 'script_parse' },
  { label: '分镜拆解', key: 'storyboard' },
  { label: '角色生成', key: 'character' },
  { label: '画面渲染', key: 'render' },
  { label: '配音字幕', key: 'audio' },
]

const LeftSidebar: React.FC = () => {
  const { projectId, title, setProject } = useProjectStore()
  const { isGenerating, currentStep, shots } = useShotStore()
  const [projects, setProjects] = useState<ProjectItem[]>([])

  useEffect(() => {
    projectApi.list().then(setProjects).catch(() => {})
  }, [projectId])

  const getStepStatus = (key: string) => {
    if (!isGenerating && shots.length > 0) return 'done'
    if (!isGenerating) return 'wait'

    const stepOrder = ['script_parse', 'storyboard', 'character', 'render', 'audio']
    const currentIdx = stepOrder.indexOf(currentStep)
    const stepIdx = stepOrder.indexOf(key)

    if (stepIdx < currentIdx) return 'done'
    if (stepIdx === currentIdx) return 'run'
    return 'wait'
  }

  const statusColors: Record<string, string> = {
    done: 'var(--green)',
    run: 'var(--amber)',
    wait: 'var(--text-quaternary)',
  }

  return (
    <div style={{
      width: 240,
      background: 'var(--bg)',
      borderRight: '1px solid var(--border)',
      padding: 16,
      overflowY: 'auto',
      flexShrink: 0,
    }}>
      <div className="section-title">我的项目</div>
      {projectId && (
        <div style={{
          padding: '8px 10px',
          background: 'var(--bg-white)',
          borderRadius: 'var(--radius)',
          marginBottom: 6,
          color: 'var(--text)',
          boxShadow: 'var(--shadow-sm)',
          fontSize: 12,
        }}>
          {title || '未命名项目'}
        </div>
      )}
      {projects.filter(p => p.id !== projectId).map((p) => (
        <div
          key={p.id}
          style={{
            padding: '8px 10px',
            background: 'var(--bg-white)',
            borderRadius: 'var(--radius)',
            marginBottom: 6,
            color: 'var(--text)',
            boxShadow: 'var(--shadow-sm)',
            cursor: 'pointer',
            fontSize: 12,
          }}
          onClick={() => setProject({ projectId: p.id, title: p.title })}
        >
          {p.title}
        </div>
      ))}
      {!projectId && !projects.length && (
        <div style={{ padding: '8px 10px', color: 'var(--text-tertiary)', fontSize: 12 }}>暂无项目</div>
      )}

      <div className="section-title" style={{ marginTop: 24 }}>Agent 执行流程</div>
      {agentSteps.map((step) => {
        const status = getStepStatus(step.key)
        return (
          <div
            key={step.key}
            style={{
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              padding: '9px 10px',
              background: 'var(--bg-white)',
              borderRadius: 'var(--radius)',
              marginBottom: 6,
              boxShadow: 'var(--shadow-sm)',
              fontSize: 12,
            }}
          >
            <span style={{ color: 'var(--text)' }}>{step.label}</span>
            <div style={{
              width: 8,
              height: 8,
              borderRadius: '50%',
              background: statusColors[status],
            }} />
          </div>
        )
      })}
    </div>
  )
}

export default LeftSidebar

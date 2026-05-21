import React, { useEffect, useState } from 'react'
import { useProjectStore } from '../stores/projectStore'
import { projectApi } from '../services/api'
import FlowGraph from './FlowGraph'

interface ProjectItem {
  id: string
  title: string
  status: string
}

const LeftSidebar: React.FC = () => {
  const { projectId, title, setProject } = useProjectStore()
  const [projects, setProjects] = useState<ProjectItem[]>([])

  useEffect(() => {
    projectApi.list().then(setProjects).catch(() => {})
  }, [projectId])

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

      <div style={{ marginTop: 24 }}>
        <FlowGraph compact />
      </div>
    </div>
  )
}

export default LeftSidebar

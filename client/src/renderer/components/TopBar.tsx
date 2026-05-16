import React from 'react'
import { Button, message } from 'antd'
import {
  PlusOutlined,
  ImportOutlined,
  ThunderboltOutlined,
  ExportOutlined,
  SettingOutlined,
  QuestionCircleOutlined,
} from '@ant-design/icons'
import { useProjectStore } from '../stores/projectStore'
import { useShotStore } from '../stores/shotStore'
import { projectApi, scriptApi, renderApi, createWebSocket } from '../services/api'

const TopBar: React.FC = () => {
  const { projectId, title, style, platform, outputFormat, resolution, setProject, reset } = useProjectStore()
  const { shots, setShots, setGenerating, setProgress } = useShotStore()

  const handleNewProject = () => {
    reset()
    setShots([])
    message.success('已重置项目')
  }

  const handleExport = async () => {
    if (!projectId) { message.warning('请先生成分镜'); return }
    try {
      await renderApi.start({ project_id: projectId, output_format: outputFormat, resolution })
      message.success('已提交渲染任务')
    } catch { message.error('渲染提交失败') }
  }

  return (
    <div style={{
      height: 44,
      background: 'var(--bg)',
      borderBottom: '1px solid var(--border)',
      display: 'flex',
      alignItems: 'center',
      padding: '0 20px',
      justifyContent: 'space-between',
      flexShrink: 0,
    }}>
      <div style={{ fontWeight: 500, fontSize: 14, color: 'var(--text)', display: 'flex', alignItems: 'center', gap: 8 }}>
        AI漫剧生成 Agent
      </div>
      <div style={{ display: 'flex', gap: 8 }}>
        <Button icon={<PlusOutlined />} size="small" onClick={handleNewProject}>新建项目</Button>
        <Button icon={<ImportOutlined />} size="small">导入剧本</Button>
        <Button type="primary" icon={<ThunderboltOutlined />} size="small">一键生成</Button>
        <Button icon={<ExportOutlined />} size="small" onClick={handleExport}>导出成片</Button>
      </div>
      <div style={{ display: 'flex', gap: 14, color: 'var(--text-secondary)', fontSize: 12, alignItems: 'center' }}>
        <span style={{ cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 4 }}>
          <SettingOutlined /> 设置
        </span>
        <span style={{ cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 4 }}>
          <QuestionCircleOutlined /> 帮助
        </span>
      </div>
    </div>
  )
}

export default TopBar

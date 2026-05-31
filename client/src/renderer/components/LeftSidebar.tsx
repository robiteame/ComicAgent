import React, { useEffect, useMemo, useRef, useState } from 'react'
import { ExportOutlined, ImportOutlined, MenuFoldOutlined, MenuUnfoldOutlined, PlusOutlined, ThunderboltOutlined } from '@ant-design/icons'
import { message, Tooltip } from 'antd'
import { characterApi, projectApi, renderApi, scriptApi, shotApi } from '../services/api'
import { useProjectStore } from '../stores/projectStore'
import { useShotStore } from '../stores/shotStore'

const PARSE_SCRIPT_EVENT = 'pipeline:parse-script'
const OPEN_CREATE_PROJECT_EVENT = 'workspace:open-create-project'

interface ProjectItem {
  id: string
  parent_project_id?: string
  project_type?: 'series' | 'episode'
  episode_number?: number
  title: string
  status: string
  style?: string
  genre?: string
  updated_at?: string
}

interface LeftSidebarProps {
  collapsed: boolean
  onToggleCollapsed: () => void
}

function formatUpdatedAt(value?: string) {
  if (!value) return '刚刚创建'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '刚刚创建'
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date)
}

function cleanTitle(value?: string) {
  const title = (value || '').trim()
  if (!title || /^[?？]+$/.test(title)) return '未命名项目'
  return title
}

const LeftSidebar: React.FC<LeftSidebarProps> = ({ collapsed, onToggleCollapsed }) => {
  const { projectId, parentProjectId, projectType, style, outputFormat, resolution, platform, setProject } = useProjectStore()
  const {
    setShots,
    selectShot,
    setGenerating,
    setProgress,
    setAwaitingStoryboardConfirm,
    setVideoPath,
    clearLogs,
    appendLog,
  } = useShotStore()

  const [projects, setProjects] = useState<ProjectItem[]>([])
  const [loadingProjectId, setLoadingProjectId] = useState<string | null>(null)
  const fileInputRef = useRef<HTMLInputElement | null>(null)

  const refreshProjects = () => {
    projectApi.list().then(setProjects).catch(() => undefined)
  }

  useEffect(() => {
    refreshProjects()
  }, [projectId])

  const visibleProjects = useMemo(() => {
    return [...projects].sort((a, b) => {
      const ta = a.updated_at ? new Date(a.updated_at).getTime() : 0
      const tb = b.updated_at ? new Date(b.updated_at).getTime() : 0
      return tb - ta
    })
  }, [projects])

  const projectTree = useMemo(() => {
    const series = visibleProjects.filter((item) => (item.project_type || 'series') !== 'episode')
    const episodesByParent = new Map<string, ProjectItem[]>()
    visibleProjects
      .filter((item) => item.project_type === 'episode')
      .forEach((episode) => {
        const key = episode.parent_project_id || ''
        episodesByParent.set(key, [...(episodesByParent.get(key) || []), episode])
      })
    episodesByParent.forEach((items) => items.sort((a, b) => (a.episode_number || 0) - (b.episode_number || 0)))
    return { series, episodesByParent }
  }, [visibleProjects])

  const sidebarProjects = useMemo(() => {
    const nested = projectTree.series.flatMap((series) => [series, ...(projectTree.episodesByParent.get(series.id) || [])])
    const orphanEpisodes = visibleProjects.filter((item) => item.project_type === 'episode' && !item.parent_project_id)
    return [...nested, ...orphanEpisodes]
  }, [projectTree, visibleProjects])

  const handleSelectProject = async (id: string) => {
    try {
      setLoadingProjectId(id)
      const [projectDetail, shotList, characters] = await Promise.all([
        projectApi.get(id),
        shotApi.list(id),
        characterApi.list(id),
      ])

      setProject({
        projectId: projectDetail.id,
        parentProjectId: projectDetail.parent_project_id || '',
        projectType: projectDetail.project_type || 'series',
        episodeNumber: projectDetail.episode_number || 0,
        title: projectDetail.title,
        genre: projectDetail.genre,
        style: projectDetail.style,
        status: projectDetail.status,
        outputFormat: projectDetail.output_format,
        resolution: projectDetail.resolution,
        platform: projectDetail.platform,
        characters,
      })

      setShots(shotList || [])
      selectShot(shotList?.[0]?.id || null)
      setAwaitingStoryboardConfirm(projectDetail.status === 'storyboard_ready')
      setVideoPath(projectDetail.status === 'completed' ? `/output/projects/${projectDetail.id}/output/final.mp4` : '')
    } catch (err: any) {
      message.error('加载项目失败：' + (err.message || '未知错误'))
    } finally {
      setLoadingProjectId(null)
    }
  }

  const ensureProject = async () => {
    if (projectId) return projectId

    const project = await projectApi.create({
      title: '未命名项目',
      style,
      genre: '',
      output_format: outputFormat,
      resolution,
      platform,
    })

    setProject({
      projectId: project.id,
      parentProjectId: project.parent_project_id || '',
      projectType: project.project_type || 'series',
      episodeNumber: project.episode_number || 0,
      title: project.title,
      style,
      outputFormat,
      resolution,
      platform,
    })
    refreshProjects()
    return project.id as string
  }

  const handleImportScript = async (file: File) => {
    try {
      const pid = await ensureProject()
      setGenerating(true)
      setAwaitingStoryboardConfirm(false)
      setVideoPath('')
      setProgress(0, 'parse_script')
      clearLogs()

      const formData = new FormData()
      formData.append('project_id', pid)
      formData.append('file', file)
      formData.append('style', style)
      formData.append('output_format', outputFormat)
      formData.append('resolution', resolution)
      formData.append('platform', platform)

      await scriptApi.upload(formData)
      appendLog(`[${new Date().toLocaleTimeString('zh-CN', { hour12: false })}] 已导入剧本：${file.name}`)
      message.success('剧本上传成功，已进入解析流程')
    } catch (err: any) {
      setGenerating(false)
      message.error('导入失败：' + (err.message || '未知错误'))
    }
  }

  const handleExport = async () => {
    if (!projectId) {
      message.warning('请先选择或创建一个项目')
      return
    }

    try {
      await renderApi.start({
        project_id: projectId,
        output_format: outputFormat,
        resolution,
      })
      message.success('导出任务已提交')
    } catch {
      message.error('导出任务提交失败')
    }
  }

  const handleCreateEpisode = async () => {
    if (!projectId) {
      message.warning('请先选择一个大项目')
      return
    }
    const rootId = projectType === 'episode' ? parentProjectId : projectId
    if (!rootId) {
      message.warning('请先选择一个大项目')
      return
    }

    try {
      const nextNumber = visibleProjects.filter((item) => item.parent_project_id === rootId).length + 1
      const episode = await projectApi.create({
        title: `第 ${nextNumber} 集`,
        parent_project_id: rootId,
        project_type: 'episode',
        style,
        genre: '',
        output_format: outputFormat,
        resolution,
        platform,
      })
      refreshProjects()
      await handleSelectProject(episode.id)
      message.success('单集已创建')
    } catch (err: any) {
      message.error('创建单集失败：' + (err.message || '未知错误'))
    }
  }

  const actionItems = [
    { id: 'import', label: '导入剧本', icon: <ImportOutlined />, onClick: () => fileInputRef.current?.click() },
    { id: 'parse', label: '生成分镜', icon: <ThunderboltOutlined />, onClick: () => window.dispatchEvent(new CustomEvent(PARSE_SCRIPT_EVENT)) },
    { id: 'create', label: '新建项目', icon: <PlusOutlined />, onClick: () => window.dispatchEvent(new CustomEvent(OPEN_CREATE_PROJECT_EVENT)) },
    { id: 'export', label: '导出成片', icon: <ExportOutlined />, onClick: () => void handleExport() },
  ]

  return (
    <aside className={`left-sidebar${collapsed ? ' collapsed' : ''}`} aria-label="左侧导航">
      <div className="sidebar-head">
        <button type="button" className="collapse-switch" onClick={onToggleCollapsed} aria-label="展开或收起左侧栏">
          {collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
        </button>
        {!collapsed && <div className="sidebar-brand">漫剧工坊</div>}
      </div>

      <div className="sidebar-content">
        <div className={collapsed ? 'collapsed-shortcuts' : 'sidebar-quick-actions linear-actions'}>
          {actionItems.map((item) =>
            collapsed ? (
              <Tooltip title={item.label} key={item.id} placement="right">
                <button type="button" className="collapsed-project-btn" onClick={item.onClick} aria-label={item.label}>
                  {item.icon}
                </button>
              </Tooltip>
            ) : (
              <div key={item.id} className="linear-row">
                <button
                  type="button"
                  className={`linear-action${item.id === 'parse' ? ' primary' : ''}`}
                  onClick={item.onClick}
                >
                  <span className="linear-action-icon">{item.icon}</span>
                  <span>{item.label}</span>
                </button>
              </div>
            ),
          )}

          {!collapsed && (
            <div className="linear-row">
              <button type="button" className="linear-action" onClick={() => void handleCreateEpisode()}>
                <span className="linear-action-icon"><PlusOutlined /></span>
                <span>新建单集</span>
              </button>
            </div>
          )}

          <div className="project-list linear-project-list">
            {sidebarProjects.length > 0 ? (
              sidebarProjects.map((project) => {
                const isActive = project.id === projectId
                const isLoading = loadingProjectId === project.id
                const isEpisode = project.project_type === 'episode'

                return collapsed ? (
                  <Tooltip title={cleanTitle(project.title)} key={project.id} placement="right">
                    <button
                      type="button"
                      className={`collapsed-project-btn${isActive ? ' active' : ''}`}
                      onClick={() => void handleSelectProject(project.id)}
                      aria-label={cleanTitle(project.title)}
                    >
                      {cleanTitle(project.title).slice(0, 1)}
                    </button>
                  </Tooltip>
                ) : (
                  <div
                    key={project.id}
                    className={`project-item linear-project-item${isActive ? ' active' : ''}${isLoading ? ' loading' : ''}${isEpisode ? ' episode-item' : ''}`}
                  >
                    <button type="button" className="project-main" onClick={() => void handleSelectProject(project.id)}>
                      <div className="project-item-title">{isEpisode ? `第 ${project.episode_number || 1} 集 · ` : ''}{cleanTitle(project.title)}</div>
                      <div className="project-item-meta">最近编辑：{formatUpdatedAt(project.updated_at)}</div>
                    </button>
                  </div>
                )
              })
            ) : (
              <div className="empty-hint">暂无项目</div>
            )}
          </div>
        </div>
      </div>

      <input
        ref={fileInputRef}
        type="file"
        accept=".txt,.docx"
        style={{ display: 'none' }}
        onChange={(e) => {
          const file = e.target.files?.[0]
          if (file) {
            void handleImportScript(file)
          }
          e.target.value = ''
        }}
      />
    </aside>
  )
}

export default LeftSidebar

import React, { useEffect, useMemo, useRef, useState } from 'react'
import {
  CaretDownOutlined,
  CaretRightOutlined,
  DeleteOutlined,
  FileOutlined,
  FolderOutlined,
  ImportOutlined,
  LeftOutlined,
  PlusOutlined,
  RightOutlined,
} from '@ant-design/icons'
import { message, Modal, Tooltip } from 'antd'
import { characterApi, projectApi, shotApi } from '../services/api'
import { useProjectStore } from '../stores/projectStore'
import { useShotStore } from '../stores/shotStore'

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
  video_path?: string
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
  return title || '未命名项目'
}

const LeftSidebar: React.FC<LeftSidebarProps> = ({ collapsed, onToggleCollapsed }) => {
  const { projectId, parentProjectId, projectType, style, outputFormat, resolution, platform, setProject, reset } = useProjectStore()
  const {
    setShots,
    selectShot,
    setGenerating,
    setProgress,
    setAwaitingStoryboardConfirm,
    setVideoPath,
    appendLog,
    clearLogs,
  } = useShotStore()

  const [projects, setProjects] = useState<ProjectItem[]>([])
  const [expandedSeriesIds, setExpandedSeriesIds] = useState<Set<string>>(new Set())
  const [loadingProjectId, setLoadingProjectId] = useState<string | null>(null)
  const finalVideoInputRef = useRef<HTMLInputElement | null>(null)

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

    episodesByParent.forEach((items) => {
      items.sort((a, b) => (a.episode_number || 0) - (b.episode_number || 0))
    })

    return { series, episodesByParent }
  }, [visibleProjects])

  useEffect(() => {
    const activeRootId = projectType === 'episode' ? parentProjectId : projectId
    if (!activeRootId) return
    setExpandedSeriesIds((prev) => new Set(prev).add(activeRootId))
  }, [parentProjectId, projectId, projectType])

  const handleSelectProject = async (id: string) => {
    try {
      const localProject = projects.find((item) => item.id === id)
      if (localProject && (localProject.project_type || 'series') !== 'episode') {
        const firstEpisode = (projectTree.episodesByParent.get(id) || [])[0]
        if (firstEpisode) {
          setExpandedSeriesIds((prev) => new Set(prev).add(id))
          await handleSelectProject(firstEpisode.id)
          return
        }
      }
      setLoadingProjectId(id)
      const [projectDetail, shotList, characters] = await Promise.all([
        projectApi.get(id),
        shotApi.list(id),
        characterApi.list(id),
      ])

      setProject({
        projectId: projectDetail.id,
        parentProjectId: projectDetail.parent_project_id || '',
        parentProjectTitle: projectDetail.parent_project_title || '',
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
      setVideoPath(projectDetail.video_path || (projectDetail.status === 'completed' ? `/output/projects/${projectDetail.id}/output/final.mp4` : ''))
    } catch (err: any) {
      message.error('加载项目失败：' + (err.message || '未知错误'))
    } finally {
      setLoadingProjectId(null)
    }
  }

  const handleImportFinalVideo = async (file: File) => {
    if (!projectId) {
      message.warning('请先选择或创建一个剧集')
      return
    }
    if (projectType !== 'episode') {
      message.warning('请先选择具体剧集，再导入成片')
      return
    }

    try {
      setGenerating(true)
      setProgress(95, 'quality_check')
      const formData = new FormData()
      formData.append('file', file)
      const result = await projectApi.importVideo(projectId, formData)
      setVideoPath(result.video_path || `/output/projects/${projectId}/output/final.mp4`)
      appendLog(`[${new Date().toLocaleTimeString('zh-CN', { hour12: false })}] 已导入成片：${file.name}`)
      refreshProjects()
      message.success('成片已导入当前剧集')
    } catch (err: any) {
      message.error('成片导入失败：' + (err.message || '未知错误'))
    } finally {
      setGenerating(false)
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
        episode_number: nextNumber,
        style,
        genre: '',
        output_format: outputFormat,
        resolution,
        platform,
      })
      setExpandedSeriesIds((prev) => new Set(prev).add(rootId))
      refreshProjects()
      await handleSelectProject(episode.id)
      message.success('单集已创建')
    } catch (err: any) {
      message.error('创建单集失败：' + (err.message || '未知错误'))
    }
  }

  const handleDeleteProject = (project: ProjectItem, event: React.MouseEvent) => {
    event.stopPropagation()
    const isEpisode = project.project_type === 'episode'
    const title = cleanTitle(project.title)
    Modal.confirm({
      title: `删除${isEpisode ? '单集' : '项目'}：${title}`,
      content: isEpisode
        ? '删除后会同步清理该单集下的分镜、故事板、成片和输出资产文件。'
        : '删除后会同步删除大项目、所有单集，以及绑定的角色板、场景板、分镜、成片和输出资产文件。',
      okText: '确认删除',
      cancelText: '取消',
      okButtonProps: { danger: true },
      onOk: async () => {
        await projectApi.delete(project.id)
        const deletedCurrent =
          project.id === projectId ||
          (project.project_type !== 'episode' && (parentProjectId === project.id || projectId === project.id))
        if (deletedCurrent) {
          reset()
          setShots([])
          selectShot(null)
          setAwaitingStoryboardConfirm(false)
          setVideoPath('')
          setProgress(0, '')
          clearLogs()
        }
        refreshProjects()
        message.success('项目已删除，关联资产已清理')
      },
    })
  }

  const toggleSeries = (id: string) => {
    setExpandedSeriesIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const renderProjectRow = (project: ProjectItem, isEpisode = false) => {
    const isActive = project.id === projectId
    const isLoading = loadingProjectId === project.id
    const title = cleanTitle(project.title)

    return (
      <div
        key={project.id}
        className={`project-item linear-project-item${isActive ? ' active' : ''}${isLoading ? ' loading' : ''}${isEpisode ? ' episode-item' : ''}`}
      >
        <button type="button" className="project-main" onClick={() => void handleSelectProject(project.id)}>
          <div className="project-item-title">
            <span className={`project-item-icon${isEpisode ? '' : ' folder'}`}>
              {isEpisode ? <FileOutlined /> : <FolderOutlined />}
            </span>
            <span>{isEpisode ? `第 ${project.episode_number || 1} 集 · ` : ''}{title}</span>
          </div>
          <div className="project-item-meta">最近编辑：{formatUpdatedAt(project.updated_at)}</div>
        </button>
        <Tooltip title={isEpisode ? '删除单集' : '删除项目'}>
          <button
            type="button"
            className="project-delete-btn"
            aria-label={isEpisode ? '删除单集' : '删除项目'}
            onClick={(event) => handleDeleteProject(project, event)}
          >
            <DeleteOutlined />
          </button>
        </Tooltip>
      </div>
    )
  }

  const actionItems = [
    { id: 'create', label: '新建项目', icon: <PlusOutlined />, onClick: () => window.dispatchEvent(new CustomEvent(OPEN_CREATE_PROJECT_EVENT)) },
    { id: 'episode', label: '新建剧集', icon: <FileOutlined />, onClick: () => void handleCreateEpisode() },
    { id: 'import-video', label: '导入成片', icon: <ImportOutlined />, onClick: () => finalVideoInputRef.current?.click() },
  ]

  return (
    <aside className={`left-sidebar${collapsed ? ' collapsed' : ''}`} aria-label="左侧导航">
      <div className="sidebar-head">
        <button type="button" className="collapse-switch" onClick={onToggleCollapsed} aria-label="展开或收起左侧栏">
          {collapsed ? <RightOutlined /> : <LeftOutlined />}
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
                  className={`linear-action${item.id === 'create' ? ' primary' : ''}`}
                  onClick={item.onClick}
                >
                  <span className="linear-action-icon">{item.icon}</span>
                  <span>{item.label}</span>
                </button>
              </div>
            ),
          )}

          <div className="project-list linear-project-list">
            {projectTree.series.length > 0 ? (
              projectTree.series.map((series) => {
                const title = cleanTitle(series.title)
                const episodes = projectTree.episodesByParent.get(series.id) || []
                const expanded = expandedSeriesIds.has(series.id)
                const isActive = series.id === projectId

                if (collapsed) {
                  return (
                    <Tooltip title={title} key={series.id} placement="right">
                      <button
                        type="button"
                        className={`collapsed-project-btn${isActive ? ' active' : ''}`}
                        onClick={() => void handleSelectProject(series.id)}
                        aria-label={title}
                      >
                        <FolderOutlined />
                      </button>
                    </Tooltip>
                  )
                }

                return (
                  <div className="project-tree-node" key={series.id}>
                    <div className="project-series-row">
                      <button
                        type="button"
                        className="project-expand-btn"
                        onClick={() => toggleSeries(series.id)}
                        aria-label={expanded ? '收起剧集' : '展开剧集'}
                      >
                        {expanded ? <CaretDownOutlined /> : <CaretRightOutlined />}
                      </button>
                      {renderProjectRow(series)}
                    </div>
                    {expanded && episodes.map((episode) => renderProjectRow(episode, true))}
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
        ref={finalVideoInputRef}
        type="file"
        accept="video/mp4,.mp4,.m4v"
        style={{ display: 'none' }}
        onChange={(e) => {
          const file = e.target.files?.[0]
          if (file) {
            void handleImportFinalVideo(file)
          }
          e.target.value = ''
        }}
      />
    </aside>
  )
}

export default LeftSidebar

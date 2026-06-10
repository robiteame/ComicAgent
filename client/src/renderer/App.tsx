import React, { useEffect, useRef, useState } from 'react'
import BottomBar from './components/BottomBar'
import GlobalPlayfulMotion from './components/GlobalPlayfulMotion'
import LeftSidebar from './components/LeftSidebar'
import MainWorkspace from './components/MainWorkspace'
import RightSidebar from './components/RightSidebar'
import SystemSettingsPage from './components/SystemSettingsPage'
import TopBar from './components/TopBar'
import { OPEN_SETTINGS_EVENT } from './components/TopBar'

const OPEN_CREATE_PROJECT_EVENT = 'workspace:open-create-project'
const WORKSPACE_NAVIGATE_EVENT = 'workspace:navigate'

type WorkspaceNavigateDetail = {
  tab?: string
  previewMode?: 'shot' | 'video'
}

const App: React.FC = () => {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  const [rightSidebarCollapsed, setRightSidebarCollapsed] = useState(true)
  const [settingsPageOpen, setSettingsPageOpen] = useState(false)
  const settingsPageOpenRef = useRef(settingsPageOpen)
  const pendingWorkspaceNavigationRef = useRef<WorkspaceNavigateDetail | null>(null)

  useEffect(() => {
    settingsPageOpenRef.current = settingsPageOpen
  }, [settingsPageOpen])

  useEffect(() => {
    const openShotConfig = () => setRightSidebarCollapsed(false)
    window.addEventListener('workspace:open-shot-config', openShotConfig)
    return () => window.removeEventListener('workspace:open-shot-config', openShotConfig)
  }, [])

  useEffect(() => {
    const openSettings = () => setSettingsPageOpen(true)
    window.addEventListener(OPEN_SETTINGS_EVENT, openSettings)
    return () => window.removeEventListener(OPEN_SETTINGS_EVENT, openSettings)
  }, [])

  useEffect(() => {
    const openCreateProject = () => {
      if (!settingsPageOpenRef.current) return
      settingsPageOpenRef.current = false
      setSettingsPageOpen(false)
      window.setTimeout(() => {
        window.dispatchEvent(new CustomEvent(OPEN_CREATE_PROJECT_EVENT))
      }, 50)
    }
    window.addEventListener(OPEN_CREATE_PROJECT_EVENT, openCreateProject)
    return () => window.removeEventListener(OPEN_CREATE_PROJECT_EVENT, openCreateProject)
  }, [])

  useEffect(() => {
    const navigateToWorkspace = (event: Event) => {
      const detail = (event as CustomEvent<WorkspaceNavigateDetail>).detail || {}
      if (!settingsPageOpenRef.current) return

      pendingWorkspaceNavigationRef.current = detail
      settingsPageOpenRef.current = false
      setSettingsPageOpen(false)
      window.setTimeout(() => {
        const pending = pendingWorkspaceNavigationRef.current
        pendingWorkspaceNavigationRef.current = null
        if (pending) {
          window.dispatchEvent(new CustomEvent(WORKSPACE_NAVIGATE_EVENT, { detail: pending }))
        }
      }, 50)
    }

    window.addEventListener(WORKSPACE_NAVIGATE_EVENT, navigateToWorkspace)
    return () => window.removeEventListener(WORKSPACE_NAVIGATE_EVENT, navigateToWorkspace)
  }, [])

  return (
    <div className="app-shell">
      <GlobalPlayfulMotion />
      <TopBar />
      <div
        className={`app-main${sidebarCollapsed ? ' sidebar-collapsed' : ''}${rightSidebarCollapsed ? ' right-sidebar-collapsed' : ''}${settingsPageOpen ? ' settings-mode' : ''}`}
        role="main"
        aria-label="主工作台"
      >
        <LeftSidebar
          collapsed={sidebarCollapsed}
          onToggleCollapsed={() => setSidebarCollapsed((prev) => !prev)}
        />
        {settingsPageOpen ? (
          <SystemSettingsPage onBack={() => setSettingsPageOpen(false)} />
        ) : (
          <MainWorkspace />
        )}
        {!settingsPageOpen && (
          <RightSidebar
            collapsed={rightSidebarCollapsed}
            onToggleCollapsed={() => setRightSidebarCollapsed((prev) => !prev)}
          />
        )}
      </div>
      <BottomBar />
    </div>
  )
}

export default App

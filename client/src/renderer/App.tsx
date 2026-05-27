import React, { useState } from 'react'
import BottomBar from './components/BottomBar'
import LeftSidebar from './components/LeftSidebar'
import MainWorkspace from './components/MainWorkspace'
import RightSidebar from './components/RightSidebar'
import TopBar from './components/TopBar'

const App: React.FC = () => {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  const [rightSidebarCollapsed, setRightSidebarCollapsed] = useState(true)

  return (
    <div className="app-shell">
      <TopBar />
      <div
        className={`app-main${sidebarCollapsed ? ' sidebar-collapsed' : ''}${rightSidebarCollapsed ? ' right-sidebar-collapsed' : ''}`}
        role="main"
        aria-label="主工作台"
      >
        <LeftSidebar
          collapsed={sidebarCollapsed}
          onToggleCollapsed={() => setSidebarCollapsed((prev) => !prev)}
        />
        <MainWorkspace />
        <RightSidebar
          collapsed={rightSidebarCollapsed}
          onToggleCollapsed={() => setRightSidebarCollapsed((prev) => !prev)}
        />
      </div>
      <BottomBar />
    </div>
  )
}

export default App

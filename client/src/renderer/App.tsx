import React from 'react'
import TopBar from './components/TopBar'
import LeftSidebar from './components/LeftSidebar'
import MainWorkspace from './components/MainWorkspace'
import RightSidebar from './components/RightSidebar'
import BottomBar from './components/BottomBar'

const App: React.FC = () => {
  return (
    <div style={{ height: '100vh', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      <TopBar />
      <div style={{ display: 'flex', flex: 1, overflow: 'hidden' }}>
        <LeftSidebar />
        <MainWorkspace />
        <RightSidebar />
      </div>
      <BottomBar />
    </div>
  )
}

export default App

import React from 'react'
import { SettingOutlined } from '@ant-design/icons'
import { Button } from 'antd'

export const OPEN_SETTINGS_EVENT = 'workspace:open-settings'

const TopBar: React.FC = () => {
  return (
    <header className="topbar">
      <Button
        size="small"
        icon={<SettingOutlined />}
        onClick={() => window.dispatchEvent(new CustomEvent(OPEN_SETTINGS_EVENT))}
      >
        系统设置
      </Button>
    </header>
  )
}

export default TopBar

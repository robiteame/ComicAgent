import React from 'react'
import ReactDOM from 'react-dom/client'
import { ConfigProvider, theme } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import App from './App'
import './styles/global.css'

const antTheme = {
  algorithm: theme.defaultAlgorithm,
  token: {
    colorPrimary: '#0071e3',
    colorSuccess: '#34c759',
    colorWarning: '#ff9500',
    colorError: '#ff3b30',
    colorInfo: '#0071e3',
    colorBgContainer: '#ffffff',
    colorBgLayout: '#f5f5f7',
    colorBgElevated: '#ffffff',
    colorBorder: '#e0e0e0',
    colorBorderSecondary: '#e5e5ea',
    colorText: '#1d1d1f',
    colorTextSecondary: '#6e6e73',
    colorTextTertiary: '#aeaeb2',
    colorTextQuaternary: '#c7c7cc',
    borderRadius: 6,
    fontFamily: '-apple-system, BlinkMacSystemFont, "SF Pro Text", "Helvetica Neue", "Noto Sans SC", sans-serif',
    fontSize: 13,
    controlHeight: 30,
    controlHeightLG: 36,
    controlHeightSM: 24,
    colorLink: '#0071e3',
    colorLinkHover: '#0077ed',
  },
  components: {
    Button: {
      controlHeight: 30,
      controlHeightLG: 36,
      controlHeightSM: 24,
      borderRadius: 6,
    },
    Input: {
      controlHeight: 30,
      paddingInline: 10,
    },
    Select: {
      controlHeight: 30,
    },
  },
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ConfigProvider locale={zhCN} theme={antTheme}>
      <App />
    </ConfigProvider>
  </React.StrictMode>
)

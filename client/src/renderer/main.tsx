import React from 'react'
import ReactDOM from 'react-dom/client'
import { App as AntdApp, ConfigProvider, theme } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import App from './App'
import './styles/global.css'

const antTheme = {
  algorithm: theme.defaultAlgorithm,
  token: {
    colorPrimary: '#4f7fd8',
    colorSuccess: '#5fa783',
    colorWarning: '#b89266',
    colorError: '#b26969',
    colorInfo: '#4f7fd8',
    colorBgContainer: '#ffffff',
    colorBgLayout: 'transparent',
    colorBgElevated: '#fafdff',
    colorBorder: '#d7e1ec',
    colorBorderSecondary: '#e5edf5',
    colorText: '#27313a',
    colorTextSecondary: '#647385',
    colorTextTertiary: '#8a98a9',
    colorTextQuaternary: '#a0acbb',
    borderRadius: 8,
    fontFamily:
      '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif',
    fontSize: 13,
    controlHeight: 34,
    controlHeightLG: 38,
    controlHeightSM: 30,
    colorLink: '#4f7fd8',
    colorLinkHover: '#345fba',
  },
  components: {
    Button: {
      controlHeight: 34,
      controlHeightLG: 38,
      controlHeightSM: 30,
      borderRadius: 8,
    },
    Input: {
      controlHeight: 34,
      paddingInline: 11,
    },
    Select: {
      controlHeight: 34,
    },
  },
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ConfigProvider locale={zhCN} theme={antTheme}>
      <AntdApp>
        <App />
      </AntdApp>
    </ConfigProvider>
  </React.StrictMode>,
)

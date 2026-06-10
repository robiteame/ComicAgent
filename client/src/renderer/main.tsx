import React, { useEffect, useMemo, useState } from 'react'
import ReactDOM from 'react-dom/client'
import { App as AntdApp, ConfigProvider, theme } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import App from './App'
import { applyThemeToDocument, getInitialTheme, THEME_CHANGED_EVENT, type AppTheme } from './theme'
import './styles/global.css'

const fontFamily = '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif'

function buildAntTheme(appTheme: AppTheme) {
  const isBlack = appTheme === 'black'

  return {
    algorithm: isBlack ? theme.darkAlgorithm : theme.defaultAlgorithm,
    token: {
      colorPrimary: isBlack ? '#78a2f2' : '#4f7fd8',
      colorSuccess: isBlack ? '#72c69b' : '#5fa783',
      colorWarning: isBlack ? '#d9aa70' : '#b89266',
      colorError: isBlack ? '#e08383' : '#b26969',
      colorInfo: isBlack ? '#78a2f2' : '#4f7fd8',
      colorBgContainer: isBlack ? '#131820' : '#ffffff',
      colorBgLayout: 'transparent',
      colorBgElevated: isBlack ? '#171d27' : '#fafdff',
      colorBorder: isBlack ? '#313b49' : '#d7e1ec',
      colorBorderSecondary: isBlack ? '#252d38' : '#e5edf5',
      colorText: isBlack ? '#edf3fb' : '#27313a',
      colorTextSecondary: isBlack ? '#b4c0cf' : '#647385',
      colorTextTertiary: isBlack ? '#8996a8' : '#8a98a9',
      colorTextQuaternary: isBlack ? '#687586' : '#a0acbb',
      borderRadius: 8,
      fontFamily,
      fontSize: 13,
      controlHeight: 34,
      controlHeightLG: 38,
      controlHeightSM: 30,
      colorLink: isBlack ? '#8db3ff' : '#4f7fd8',
      colorLinkHover: isBlack ? '#a9c4ff' : '#345fba',
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
}

const Root: React.FC = () => {
  const [appTheme, setAppTheme] = useState<AppTheme>(() => getInitialTheme())
  const antTheme = useMemo(() => buildAntTheme(appTheme), [appTheme])

  useEffect(() => {
    applyThemeToDocument(appTheme)
  }, [appTheme])

  useEffect(() => {
    const handleThemeChanged = (event: Event) => {
      setAppTheme((event as CustomEvent<AppTheme>).detail)
    }
    window.addEventListener(THEME_CHANGED_EVENT, handleThemeChanged)
    return () => window.removeEventListener(THEME_CHANGED_EVENT, handleThemeChanged)
  }, [])

  return (
    <ConfigProvider locale={zhCN} theme={antTheme}>
      <AntdApp>
        <App />
      </AntdApp>
    </ConfigProvider>
  )
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <Root />
  </React.StrictMode>,
)

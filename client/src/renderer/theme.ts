export type AppTheme = 'light' | 'black'

export const THEME_STORAGE_KEY = 'comic-agent-theme'
export const DEFAULT_THEME: AppTheme = 'light'

export const THEME_OPTIONS: { value: AppTheme; label: string; description: string }[] = [
  { value: 'light', label: '默认主题', description: '延续当前蓝白创作工作台' },
  { value: 'black', label: '黑色主题', description: '适合低光环境的深色工作台' },
]

export const THEME_CHANGED_EVENT = 'app-theme:changed'
const THEME_RUNTIME_STYLE_ID = 'comic-agent-runtime-theme'

const BLACK_RUNTIME_CSS = `
body,
.app-shell,
.app-main,
.left-sidebar,
.right-sidebar,
.main-workspace,
.settings-workspace {
  color: #edf3fb !important;
}

.workspace-tabbar,
.settings-page,
.settings-nav,
.settings-content,
.asset-page,
.script-panel,
.preview-panel,
.workspace-tab-body,
.right-sidebar {
  background: #131820 !important;
  color: #edf3fb !important;
}

.sidebar-footer .linear-action.sidebar-settings-btn,
.sidebar-footer .collapsed-project-btn.sidebar-settings-btn,
.workflow-rail span,
.asset-tabs,
.asset-chip,
.preview-tools,
.preview-mode-switch,
.preview-caption,
.bound-asset-card,
.consistency-baseline,
.consistency-rule-item,
.consistency-lock-row,
.consistency-rule-note,
.consistency-blocking-row,
.mode-chip,
.ds-chip,
.model-config-card,
.settings-section,
.settings-nav-item,
.settings-template-chip,
.skill-agent-panel,
.skill-toggle-row,
.right-sidebar-status {
  background: rgba(19, 24, 32, 0.78) !important;
  color: #edf3fb !important;
}

.workspace-create-panel,
.asset-board-panel,
.asset-empty-state,
.bound-asset-thumb,
.consistency-baseline-thumb,
.final-video,
.thumb-item {
  background: #0f141b !important;
  color: #b4c0cf !important;
}

.ant-btn-default,
.ant-input,
.ant-input-number,
.ant-input-affix-wrapper,
.ant-select-selector,
.ant-picker,
.ant-segmented {
  border-color: #313b49 !important;
  background: rgba(15, 20, 27, 0.94) !important;
  color: #edf3fb !important;
}

.ant-modal-content,
.ant-modal-header,
.ant-popover-inner,
.ant-select-dropdown,
.ant-dropdown-menu,
.ant-message-notice-content,
.ant-tooltip-inner {
  border-color: #252d38 !important;
  background: #171d27 !important;
  color: #edf3fb !important;
}
`

export function resolveTheme(value: unknown): AppTheme {
  return value === 'black' || value === 'light' ? value : DEFAULT_THEME
}

export function getInitialTheme(storage: Pick<Storage, 'getItem'> = window.localStorage): AppTheme {
  try {
    return resolveTheme(storage.getItem(THEME_STORAGE_KEY))
  } catch {
    return DEFAULT_THEME
  }
}

export function applyThemeToDocument(
  theme: AppTheme,
  targetDocument: Pick<Document, 'documentElement'> = document,
  storage: Pick<Storage, 'setItem'> = window.localStorage,
) {
  targetDocument.documentElement.setAttribute('data-theme', theme)
  syncRuntimeThemeStyle(theme, targetDocument)
  try {
    storage.setItem(THEME_STORAGE_KEY, theme)
  } catch {
    // Theme changes should still apply when storage is unavailable.
  }
}

function syncRuntimeThemeStyle(theme: AppTheme, targetDocument: Pick<Document, 'documentElement'>) {
  const runtimeDocument = targetDocument as Document
  if (!runtimeDocument.getElementById || !runtimeDocument.createElement || !runtimeDocument.head) return

  const existing = runtimeDocument.getElementById(THEME_RUNTIME_STYLE_ID)
  if (theme === 'light') {
    existing?.remove()
    return
  }

  const style = existing || runtimeDocument.createElement('style')
  style.id = THEME_RUNTIME_STYLE_ID
  style.textContent = BLACK_RUNTIME_CSS
  if (!existing) runtimeDocument.head.appendChild(style)
}

export function notifyThemeChanged(theme: AppTheme) {
  window.dispatchEvent(new CustomEvent<AppTheme>(THEME_CHANGED_EVENT, { detail: theme }))
}

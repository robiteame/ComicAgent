import React, { useEffect, useMemo, useRef, useState } from 'react'
import {
  ApiOutlined,
  ArrowLeftOutlined,
  BgColorsOutlined,
  CopyOutlined,
  ExperimentOutlined,
  ReloadOutlined,
  SaveOutlined,
  UploadOutlined,
} from '@ant-design/icons'
import { Button, Input, InputNumber, Segmented, Select, Slider, Switch, message } from 'antd'
import { projectApi, settingsApi } from '../services/api'
import { STYLE_DESCRIPTIONS, STYLE_OPTIONS } from '../constants/styleTemplates'
import { useProjectStore } from '../stores/projectStore'
import {
  applyThemeToDocument,
  getInitialTheme,
  notifyThemeChanged,
  THEME_OPTIONS,
  type AppTheme,
} from '../theme'

const { TextArea } = Input
const { Password } = Input
const STYLE_TEMPLATES_UPDATED_EVENT = 'settings:style-templates-updated'

type StyleOption = { value: string; label: string; keywords?: string; custom?: boolean }

type AgentSkillConfig = {
  style_template_id: string
  custom_style_keywords: string
  filter_tts_instruction_text: boolean
  camera_composition: string
  force_character_scene_references: boolean
  prompt_auto_assembly: boolean
  openpose_lock_enabled: boolean
  style_reference_weight: number
  action_reference_weight: number
  continuity_enabled: boolean
}

type SkillTemplate = {
  id: string
  name: string
  script_agent: AgentSkillConfig
  storyboard_agent: AgentSkillConfig
}

type ModelCategory = 'script' | 'image' | 'video' | 'voice'
type ModelConfig = Record<string, any>
type ModelConfigState = Record<ModelCategory, ModelConfig>

interface SystemSettingsPageProps {
  onBack: () => void
}

type SettingsTab = 'appearance' | 'models' | 'skill'

const DEFAULT_AGENT_CONFIG: AgentSkillConfig = {
  style_template_id: 'anime',
  custom_style_keywords: '',
  filter_tts_instruction_text: true,
  camera_composition: 'medium shot, vertical 9:16, clear subject staging',
  force_character_scene_references: true,
  prompt_auto_assembly: true,
  openpose_lock_enabled: true,
  style_reference_weight: 0.45,
  action_reference_weight: 0.3,
  continuity_enabled: true,
}

const DEFAULT_TEMPLATE: SkillTemplate = {
  id: 'default',
  name: '默认 Skill 方案',
  script_agent: DEFAULT_AGENT_CONFIG,
  storyboard_agent: DEFAULT_AGENT_CONFIG,
}

const EMPTY_MODEL_CONFIG: ModelConfigState = {
  script: {},
  image: {},
  video: {},
  voice: {},
}

const TAB_ITEMS: { key: SettingsTab; label: string; desc: string; icon: React.ReactNode }[] = [
  { key: 'appearance', label: '外观与画风', desc: '画风模板与全局生成规格', icon: <BgColorsOutlined /> },
  { key: 'models', label: '模型与 API 配置', desc: '剧本 / 图像 / 视频 / 配音接口', icon: <ApiOutlined /> },
  { key: 'skill', label: 'Skill 配置', desc: '子 Agent 生成策略与绑定', icon: <ExperimentOutlined /> },
]

const SystemSettingsPage: React.FC<SystemSettingsPageProps> = ({ onBack }) => {
  const { projectId, parentProjectId, projectType, style, platform, outputFormat, resolution, setProject } = useProjectStore()
  const [activeTab, setActiveTab] = useState<SettingsTab>('appearance')
  const [appTheme, setAppTheme] = useState<AppTheme>(() => getInitialTheme())
  const [styleTemplates, setStyleTemplates] = useState<StyleOption[]>(STYLE_OPTIONS)
  const [customStyleName, setCustomStyleName] = useState('')
  const [customStyleKeywords, setCustomStyleKeywords] = useState('')
  const [customStyleNegative, setCustomStyleNegative] = useState('')
  const [savingStyleTemplate, setSavingStyleTemplate] = useState(false)
  const [skillTemplates, setSkillTemplates] = useState<SkillTemplate[]>([DEFAULT_TEMPLATE])
  const [activeSkillId, setActiveSkillId] = useState('default')
  const [draftSkill, setDraftSkill] = useState<SkillTemplate>(DEFAULT_TEMPLATE)
  const [globalDefaultSkillId, setGlobalDefaultSkillId] = useState('default')
  const [projectBindings, setProjectBindings] = useState<Record<string, string>>({})
  const [episodeBindings, setEpisodeBindings] = useState<Record<string, string>>({})
  const [savingSkill, setSavingSkill] = useState(false)
  const [modelConfig, setModelConfig] = useState<ModelConfigState>(EMPTY_MODEL_CONFIG)
  const [savingModel, setSavingModel] = useState(false)
  const skillImportRef = useRef<HTMLInputElement>(null)

  const skillOptions = useMemo(
    () => skillTemplates.map((item) => ({ value: item.id, label: item.name || item.id })),
    [skillTemplates],
  )

  const projectBindingKey = projectType === 'episode' ? parentProjectId : projectId || ''
  const projectBindingValue = projectBindingKey ? projectBindings[projectBindingKey] || '' : ''
  const episodeBindingValue = projectId ? episodeBindings[projectId] || '' : ''

  const loadStyleTemplates = async () => {
    const result = await settingsApi.styleTemplates()
    if (Array.isArray(result.templates)) {
      setStyleTemplates(result.templates)
    }
  }

  const loadSkillConfigs = async () => {
    const result = await settingsApi.skillConfigs()
    const templates = Array.isArray(result.templates) && result.templates.length ? result.templates : [DEFAULT_TEMPLATE]
    setSkillTemplates(templates)
    setGlobalDefaultSkillId(result.global_default_template_id || templates[0].id)
    setProjectBindings(result.project_bindings || {})
    setEpisodeBindings(result.episode_bindings || {})
    const initial = templates.find((item: SkillTemplate) => item.id === (result.global_default_template_id || 'default')) || templates[0]
    setActiveSkillId(initial.id)
    setDraftSkill(cloneTemplate(initial))
  }

  const loadModelConfigs = async () => {
    const result = await settingsApi.modelConfigs()
    const categories = result.categories || {}
    setModelConfig({
      script: categories.script || {},
      image: categories.image || {},
      video: categories.video || {},
      voice: categories.voice || {},
    })
  }

  const updateProjectField = async (field: 'style' | 'resolution' | 'outputFormat', value: string) => {
    setProject({ [field]: value } as any)
    if (!projectId) return

    // store 用 camelCase，后端项目接口用 snake_case，这里做字段名映射。
    const apiFieldMap: Record<string, string> = {
      style: 'style',
      resolution: 'resolution',
      outputFormat: 'output_format',
    }
    try {
      await projectApi.update(projectId, { [apiFieldMap[field]]: value })
    } catch (err: any) {
      message.error('项目配置更新失败：' + (err.message || '未知错误'))
    }
  }

  const handleThemeChange = (value: AppTheme) => {
    setAppTheme(value)
    applyThemeToDocument(value)
    notifyThemeChanged(value)
  }

  const handleSaveCustomStyle = async () => {
    const label = customStyleName.trim()
    const keywords = customStyleKeywords.trim()
    if (!label || !keywords) {
      message.warning('请输入模板名称和画风关键词')
      return
    }

    try {
      setSavingStyleTemplate(true)
      const template = await settingsApi.createStyleTemplate({
        label,
        keywords,
        negative_prompt: customStyleNegative.trim(),
      })
      setStyleTemplates((items) => [...items.filter((item) => item.value !== template.value), template])
      setDraftSkill((current) => ({
        ...current,
        script_agent: { ...current.script_agent, style_template_id: template.value },
        storyboard_agent: { ...current.storyboard_agent, style_template_id: template.value },
      }))
      await updateProjectField('style', template.value)
      window.dispatchEvent(new CustomEvent(STYLE_TEMPLATES_UPDATED_EVENT))
      setCustomStyleName('')
      setCustomStyleKeywords('')
      setCustomStyleNegative('')
      message.success('自定义画风模板已保存')
    } catch (err: any) {
      message.error('保存画风模板失败：' + (err.response?.data?.detail || err.message || '未知错误'))
    } finally {
      setSavingStyleTemplate(false)
    }
  }

  const handleSelectSkillTemplate = (templateId: string) => {
    const template = skillTemplates.find((item) => item.id === templateId)
    if (!template) return
    setActiveSkillId(template.id)
    setDraftSkill(cloneTemplate(template))
  }

  const handleSaveSkillTemplate = async (saveAs = false) => {
    const name = draftSkill.name.trim()
    if (!name) {
      message.warning('请输入 Skill 方案名称')
      return
    }
    const payload = {
      ...draftSkill,
      id: saveAs ? `${draftSkill.id}_${Date.now()}` : draftSkill.id,
      name: saveAs ? `${name} 副本` : name,
    }
    try {
      setSavingSkill(true)
      const saved = await settingsApi.saveSkillConfig(payload)
      setSkillTemplates((items) => [...items.filter((item) => item.id !== saved.id), saved])
      setActiveSkillId(saved.id)
      setDraftSkill(cloneTemplate(saved))
      message.success(saveAs ? 'Skill 方案已另存为模板' : 'Skill 方案已保存')
    } catch (err: any) {
      message.error('保存 Skill 方案失败：' + (err.response?.data?.detail || err.message || '未知错误'))
    } finally {
      setSavingSkill(false)
    }
  }

  const handleResetSkillTemplate = () => {
    const template = skillTemplates.find((item) => item.id === activeSkillId) || DEFAULT_TEMPLATE
    setDraftSkill(cloneTemplate(template))
    message.success('已恢复为上次保存的 Skill 方案')
  }

  const handleImportSkillFile = async (file: File) => {
    try {
      const text = await file.text()
      const parsed = JSON.parse(text)
      const candidate = parsed?.script_agent || parsed?.storyboard_agent ? parsed : parsed?.template || parsed
      if (!candidate || (!candidate.script_agent && !candidate.storyboard_agent)) {
        message.error('配置文件格式不正确：缺少 script_agent / storyboard_agent')
        return
      }
      const imported: SkillTemplate = cloneTemplate({
        id: draftSkill.id,
        name: candidate.name ? `${candidate.name}` : `${draftSkill.name}（导入）`,
        script_agent: { ...DEFAULT_AGENT_CONFIG, ...(candidate.script_agent || candidate.storyboard_agent || {}) },
        storyboard_agent: { ...DEFAULT_AGENT_CONFIG, ...(candidate.storyboard_agent || candidate.script_agent || {}) },
      })
      setDraftSkill(imported)
      message.success('已导入 Skill 配置方案，请确认后点击保存生效')
    } catch (err: any) {
      message.error('导入失败：' + (err.message || '文件解析错误'))
    }
  }

  const handleSaveBindings = async (next?: {
    global_default_template_id?: string
    project_bindings?: Record<string, string>
    episode_bindings?: Record<string, string>
  }) => {
    const payload = {
      global_default_template_id: next?.global_default_template_id ?? globalDefaultSkillId,
      project_bindings: next?.project_bindings ?? projectBindings,
      episode_bindings: next?.episode_bindings ?? episodeBindings,
    }
    const result = await settingsApi.updateSkillBindings(payload)
    setGlobalDefaultSkillId(result.global_default_template_id)
    setProjectBindings(result.project_bindings || {})
    setEpisodeBindings(result.episode_bindings || {})
    message.success('Skill 绑定方案已保存')
  }

  const updateModelField = (category: ModelCategory, field: string, value: any) => {
    setModelConfig((current) => ({
      ...current,
      [category]: { ...current[category], [field]: value },
    }))
  }

  const handleSaveModelConfig = async () => {
    try {
      setSavingModel(true)
      const result = await settingsApi.saveModelConfigs({ categories: modelConfig })
      const categories = result.categories || {}
      setModelConfig({
        script: categories.script || {},
        image: categories.image || {},
        video: categories.video || {},
        voice: categories.voice || {},
      })
      message.success('模型与 API 配置已保存，新任务将自动生效')
    } catch (err: any) {
      message.error('保存模型配置失败：' + (err.response?.data?.detail || err.message || '未知错误'))
    } finally {
      setSavingModel(false)
    }
  }

  useEffect(() => {
    void loadStyleTemplates().catch(() => undefined)
    void loadSkillConfigs().catch(() => undefined)
    void loadModelConfigs().catch(() => undefined)
  }, [])

  return (
    <section className="main-workspace settings-workspace" aria-label="系统设置">
      <div className="settings-page panel-enter">
        <div className="settings-page-head">
          <div>
            <div className="asset-board-title">系统设置</div>
            <div className="asset-board-note">画风模板、模型 API 与子 Agent Skill 方案集中管理，保存后只影响后续新生成素材。</div>
          </div>
          <Button icon={<ArrowLeftOutlined />} onClick={onBack}>
            返回工作区
          </Button>
        </div>

        <div className="settings-shell">
          <nav className="settings-nav" aria-label="设置分区">
            {TAB_ITEMS.map((tab) => (
              <button
                key={tab.key}
                type="button"
                className={`settings-nav-item${activeTab === tab.key ? ' active' : ''}`}
                onClick={() => setActiveTab(tab.key)}
              >
                <span className="settings-nav-icon">{tab.icon}</span>
                <span className="settings-nav-text">
                  <strong>{tab.label}</strong>
                  <span>{tab.desc}</span>
                </span>
              </button>
            ))}
          </nav>

          <div className="settings-content">
            {activeTab === 'appearance' && (
              <div className="settings-page-grid">
                <section className="settings-section settings-section-wide theme-settings-section">
                  <div className="settings-section-title">界面主题</div>
                  <div className="theme-switch-row">
                    <Segmented
                      value={appTheme}
                      onChange={(value) => handleThemeChange(value as AppTheme)}
                      options={THEME_OPTIONS.map((item) => ({ value: item.value, label: item.label }))}
                    />
                    <span>{THEME_OPTIONS.find((item) => item.value === appTheme)?.description}</span>
                  </div>
                </section>

                <section className="settings-section settings-section-wide style-preset-section">
                  <div className="settings-section-title">预设与自定义模板</div>
                  <div className="settings-field">
                    <span>当前画风模板</span>
                    <Select
                      value={style}
                      onChange={(value) => void updateProjectField('style', value)}
                      options={styleTemplates.map((item) => ({
                        value: item.value,
                        label: item.custom ? `${item.label}（自定义）` : item.label,
                      }))}
                    />
                  </div>
                  <div className="settings-template-list">
                    {styleTemplates.map((item) => (
                      <button
                        key={item.value}
                        type="button"
                        className={`settings-template-chip${style === item.value ? ' active' : ''}`}
                        onClick={() => void updateProjectField('style', item.value)}
                      >
                        <strong>{item.label}</strong>
                        <span>{item.custom ? item.keywords || '自定义模板' : STYLE_DESCRIPTIONS[item.value] || item.keywords || '预设模板'}</span>
                      </button>
                    ))}
                  </div>
                </section>

                <section className="settings-section custom-style-section">
                  <div className="settings-section-title">保存自定义画风</div>
                  <div className="settings-field">
                    <span>模板名称</span>
                    <Input value={customStyleName} onChange={(event) => setCustomStyleName(event.target.value)} />
                  </div>
                  <div className="settings-field">
                    <span>画风关键词</span>
                    <TextArea
                      autoSize={{ minRows: 5, maxRows: 9 }}
                      value={customStyleKeywords}
                      onChange={(event) => setCustomStyleKeywords(event.target.value)}
                      placeholder="例如：柔和水彩、低饱和校园光、干净线稿、统一暖色后期"
                    />
                  </div>
                  <div className="settings-field">
                    <span>负向关键词</span>
                    <Input
                      value={customStyleNegative}
                      onChange={(event) => setCustomStyleNegative(event.target.value)}
                      placeholder="例如：过曝、凌乱笔触、文字、水印"
                    />
                  </div>
                  <Button type="primary" icon={<SaveOutlined />} loading={savingStyleTemplate} onClick={() => void handleSaveCustomStyle()}>
                    保存为自定义模板
                  </Button>
                </section>

                <section className="settings-section generation-settings-section">
                  <div className="settings-section-title">全局生成配置</div>
                  <div className="settings-field">
                    <span>输出分辨率</span>
                    <Select
                      value={resolution}
                      onChange={(value) => void updateProjectField('resolution', value)}
                      options={[
                        { value: '720p', label: '高清 720' },
                        { value: '1080p', label: '全高清 1080' },
                        { value: '2k', label: '影院级 2K' },
                        { value: '4k', label: '超高清 4K' },
                      ]}
                    />
                  </div>
                  <div className="settings-field">
                    <span>发布平台</span>
                    <Input value={platform} disabled />
                  </div>
                  <div className="settings-field">
                    <span>画面比例</span>
                    <Select
                      value={outputFormat}
                      onChange={(value) => void updateProjectField('outputFormat', value)}
                      options={[
                        { value: '9:16', label: '竖屏 9:16（抖音 / 快手）' },
                        { value: '16:9', label: '横屏 16:9（横版长视频）' },
                        { value: '1:1', label: '方形 1:1（信息流）' },
                        { value: '4:3', label: '传统 4:3' },
                        { value: '3:4', label: '竖版 3:4' },
                      ]}
                    />
                  </div>
                </section>
              </div>
            )}

            {activeTab === 'models' && (
              <div className="settings-models">
                <div className="settings-models-head">
                  <div>
                    <div className="settings-section-title">模型与 API 自定义配置</div>
                    <div className="asset-board-note">分别配置剧本、图像、视频、配音四类生成模型的接口地址、密钥与模型名，保存后新任务自动加载最新配置。</div>
                  </div>
                  <Button type="primary" icon={<SaveOutlined />} loading={savingModel} onClick={() => void handleSaveModelConfig()}>
                    保存全部配置
                  </Button>
                </div>
                <div className="settings-model-grid">
                  <ModelConfigCard
                    title="剧本生成模型"
                    subtitle="LLM · 脚本生成 / 分镜决策"
                    category="script"
                    config={modelConfig.script}
                    onChange={updateModelField}
                    providerHint="openai / mimo / deepseek"
                    extraFields={[{ key: 'max_tokens', label: '最大 Token', type: 'number' }]}
                  />
                  <ModelConfigCard
                    title="图像生成模型"
                    subtitle="角色三视图 / 场景基准 / 定稿故事板"
                    category="image"
                    config={modelConfig.image}
                    onChange={updateModelField}
                    providerHint="local / stability / doubao-seedream-5.0-lite"
                    extraFields={[{ key: 'image_size', label: '出图尺寸', type: 'text', placeholder: '例如 1440x2560' }]}
                  />
                  <ModelConfigCard
                    title="视频生成模型"
                    subtitle="SeedDance · 逐镜头视频"
                    category="video"
                    config={modelConfig.video}
                    onChange={updateModelField}
                    providerHint="Doubao-Seedance-1.5-pro"
                  />
                  <ModelConfigCard
                    title="配音生成模型"
                    subtitle="Mimo 内置 TTS"
                    category="voice"
                    config={modelConfig.voice}
                    onChange={updateModelField}
                    hideProvider
                    extraFields={[
                      { key: 'voice', label: '默认音色', type: 'text', placeholder: '例如 冰糖' },
                      { key: 'format', label: '音频格式', type: 'text', placeholder: '例如 wav' },
                    ]}
                  />
                </div>
              </div>
            )}

            {activeTab === 'skill' && (
              <section className="settings-section skill-settings-section">
                <div className="settings-section-title">子 Agent Skill 配置</div>
                <div className="skill-template-toolbar">
                  <Select value={activeSkillId} onChange={handleSelectSkillTemplate} options={skillOptions} />
                  <Input value={draftSkill.name} onChange={(event) => setDraftSkill({ ...draftSkill, name: event.target.value })} />
                  <Button type="primary" icon={<SaveOutlined />} loading={savingSkill} onClick={() => void handleSaveSkillTemplate(false)}>
                    保存
                  </Button>
                  <Button icon={<ReloadOutlined />} onClick={handleResetSkillTemplate}>
                    重置
                  </Button>
                  <Button icon={<CopyOutlined />} loading={savingSkill} onClick={() => void handleSaveSkillTemplate(true)}>
                    另存为模板
                  </Button>
                  <Button icon={<UploadOutlined />} onClick={() => skillImportRef.current?.click()}>
                    导入配置
                  </Button>
                  <input
                    ref={skillImportRef}
                    type="file"
                    accept="application/json,.json"
                    style={{ display: 'none' }}
                    onChange={(event) => {
                      const file = event.target.files?.[0]
                      if (file) void handleImportSkillFile(file)
                      event.target.value = ''
                    }}
                  />
                </div>
                <div className="skill-binding-grid">
                  <BindingSelect
                    label="全局默认方案"
                    value={globalDefaultSkillId}
                    options={skillOptions}
                    onChange={(value) => {
                      setGlobalDefaultSkillId(value)
                      void handleSaveBindings({ global_default_template_id: value })
                    }}
                  />
                  <BindingSelect
                    label="大项目绑定方案"
                    value={projectBindingValue}
                    options={[{ value: '', label: '继承全局默认' }, ...skillOptions]}
                    disabled={!projectBindingKey}
                    onChange={(value) => {
                      const next = { ...projectBindings }
                      if (projectBindingKey) {
                        if (value) next[projectBindingKey] = value
                        else delete next[projectBindingKey]
                      }
                      setProjectBindings(next)
                      void handleSaveBindings({ project_bindings: next })
                    }}
                  />
                  <BindingSelect
                    label="单剧集绑定方案"
                    value={episodeBindingValue}
                    options={[{ value: '', label: '继承项目或全局' }, ...skillOptions]}
                    disabled={!projectId}
                    onChange={(value) => {
                      const next = { ...episodeBindings }
                      if (projectId) {
                        if (value) next[projectId] = value
                        else delete next[projectId]
                      }
                      setEpisodeBindings(next)
                      void handleSaveBindings({ episode_bindings: next })
                    }}
                  />
                </div>
                <div className="skill-agent-grid">
                  <AgentSkillPanel
                    title="剧本生成子Agent配置区"
                    agent={draftSkill.script_agent}
                    styleTemplates={styleTemplates}
                    onChange={(agent) => setDraftSkill((current) => ({ ...current, script_agent: agent }))}
                  />
                  <AgentSkillPanel
                    title="分镜生成子Agent配置区"
                    agent={draftSkill.storyboard_agent}
                    styleTemplates={styleTemplates}
                    onChange={(agent) => setDraftSkill((current) => ({ ...current, storyboard_agent: agent }))}
                  />
                </div>
              </section>
            )}
          </div>
        </div>
      </div>
    </section>
  )
}

function ModelConfigCard({
  title,
  subtitle,
  category,
  config,
  onChange,
  providerHint,
  hideProvider,
  extraFields,
}: {
  title: string
  subtitle: string
  category: ModelCategory
  config: ModelConfig
  onChange: (category: ModelCategory, field: string, value: any) => void
  providerHint?: string
  hideProvider?: boolean
  extraFields?: { key: string; label: string; type: 'text' | 'number'; placeholder?: string }[]
}) {
  return (
    <div className="model-config-card">
      <div className="model-config-head">
        <strong>{title}</strong>
        <span>{subtitle}</span>
      </div>
      {!hideProvider && (
        <div className="settings-field">
          <span>Provider 渠道</span>
          <Input
            value={config.provider || ''}
            placeholder={providerHint}
            onChange={(event) => onChange(category, 'provider', event.target.value)}
          />
        </div>
      )}
      <div className="settings-field">
        <span>接口地址 Base URL</span>
        <Input
          value={config.base_url || ''}
          placeholder="https://..."
          onChange={(event) => onChange(category, 'base_url', event.target.value)}
        />
      </div>
      <div className="settings-field">
        <span>API 密钥</span>
        <Password
          value={config.api_key || ''}
          placeholder="留空表示沿用环境变量配置"
          visibilityToggle
          onChange={(event) => onChange(category, 'api_key', event.target.value)}
        />
      </div>
      <div className="settings-field">
        <span>模型名称</span>
        <Input value={config.model || ''} onChange={(event) => onChange(category, 'model', event.target.value)} />
      </div>
      {extraFields?.map((field) => (
        <div className="settings-field" key={field.key}>
          <span>{field.label}</span>
          {field.type === 'number' ? (
            <InputNumber
              style={{ width: '100%' }}
              value={config[field.key] ?? undefined}
              onChange={(value) => onChange(category, field.key, value)}
            />
          ) : (
            <Input
              value={config[field.key] || ''}
              placeholder={field.placeholder}
              onChange={(event) => onChange(category, field.key, event.target.value)}
            />
          )}
        </div>
      ))}
    </div>
  )
}

function BindingSelect({
  label,
  value,
  options,
  disabled,
  onChange,
}: {
  label: string
  value: string
  options: { value: string; label: string }[]
  disabled?: boolean
  onChange: (value: string) => void
}) {
  return (
    <div className="settings-field skill-binding-field">
      <span>{label}</span>
      <Select value={value} disabled={disabled} onChange={onChange} options={options} />
    </div>
  )
}

function AgentSkillPanel({
  title,
  agent,
  styleTemplates,
  onChange,
}: {
  title: string
  agent: AgentSkillConfig
  styleTemplates: StyleOption[]
  onChange: (agent: AgentSkillConfig) => void
}) {
  const update = <K extends keyof AgentSkillConfig>(key: K, value: AgentSkillConfig[K]) => {
    onChange({ ...agent, [key]: value })
  }

  return (
    <div className="skill-agent-panel">
      <div className="skill-agent-title">{title}</div>
      <div className="settings-field">
        <span>全局画风模板</span>
        <Select
          value={agent.style_template_id}
          onChange={(value) => update('style_template_id', value)}
          options={styleTemplates.map((item) => ({ value: item.value, label: item.custom ? `${item.label}（自定义）` : item.label }))}
        />
      </div>
      <div className="settings-field">
        <span>自定义画风补充</span>
        <TextArea
          autoSize={{ minRows: 2, maxRows: 4 }}
          value={agent.custom_style_keywords}
          onChange={(event) => update('custom_style_keywords', event.target.value)}
        />
      </div>
      <div className="settings-field">
        <span>镜头构图规范默认参数</span>
        <TextArea
          autoSize={{ minRows: 2, maxRows: 4 }}
          value={agent.camera_composition}
          onChange={(event) => update('camera_composition', event.target.value)}
        />
      </div>
      <ToggleRow label="TTS 过滤指令话术" checked={agent.filter_tts_instruction_text} onChange={(value) => update('filter_tts_instruction_text', value)} />
      <ToggleRow label="强制引用人物/场景基准图" checked={agent.force_character_scene_references} onChange={(value) => update('force_character_scene_references', value)} />
      <ToggleRow label="Prompt 自动拼装" checked={agent.prompt_auto_assembly} onChange={(value) => update('prompt_auto_assembly', value)} />
      <ToggleRow label="OpenPose 骨骼锁定" checked={agent.openpose_lock_enabled} onChange={(value) => update('openpose_lock_enabled', value)} />
      <ToggleRow label="镜头续帧连贯逻辑" checked={agent.continuity_enabled} onChange={(value) => update('continuity_enabled', value)} />
      <WeightField label="参考图画风权重" value={agent.style_reference_weight} onChange={(value) => update('style_reference_weight', value)} />
      <WeightField label="动作权重" value={agent.action_reference_weight} onChange={(value) => update('action_reference_weight', value)} />
    </div>
  )
}

function ToggleRow({ label, checked, onChange }: { label: string; checked: boolean; onChange: (value: boolean) => void }) {
  return (
    <div className="skill-toggle-row">
      <span>{label}</span>
      <Switch checked={checked} onChange={onChange} />
    </div>
  )
}

function WeightField({ label, value, onChange }: { label: string; value: number; onChange: (value: number) => void }) {
  return (
    <div className="skill-weight-row">
      <span>{label}</span>
      <Slider min={0} max={1} step={0.05} value={value} onChange={onChange} />
      <InputNumber min={0} max={1} step={0.05} value={value} onChange={(next) => onChange(Number(next || 0))} />
    </div>
  )
}

function cloneTemplate(template: SkillTemplate): SkillTemplate {
  return {
    ...template,
    script_agent: { ...DEFAULT_AGENT_CONFIG, ...template.script_agent },
    storyboard_agent: { ...DEFAULT_AGENT_CONFIG, ...template.storyboard_agent },
  }
}

export { STYLE_TEMPLATES_UPDATED_EVENT }
export default SystemSettingsPage

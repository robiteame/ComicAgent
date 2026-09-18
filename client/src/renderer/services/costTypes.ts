/**
 * 成本 / 预算 / 用量的前后端共享类型。
 *
 * 与后端 `server/api/routes/budget.py`、`server/services/budget_service.py`、
 * `server/services/usage_service.py` 的稳定 DTO 一一对应。三条不能违反的约定：
 *
 * 1. 金额一律是**整数 micro**（1 CNY = 1_000_000 micro），前端只做展示换算，
 *    绝不用浮点数拼出要回传的金额；
 * 2. `cost_known === false` 时 `cost_micro` 必为 `null`，界面必须显示「成本未知」，
 *    绝不显示 0 或任何估算值；
 * 3. 估算（cost_estimates）与实际（usage_records）是两份数据，永远分开展示。
 */

/** 后端返回的最小货币单位倍率：1 个货币单位 = 1_000_000 micro。 */
export const MICRO_PER_UNIT = 1_000_000

export type BudgetLevel = 'unlimited' | 'ok' | 'soft_exceeded' | 'hard_exceeded'

/** 触发超限的口径：金额 / 时长 / 无。 */
export type BudgetReason = 'cost' | 'seconds' | ''

export type BudgetScopeType = 'project' | 'global'

/** 生效预算的来源：项目自身 / 父系列或全局 / 未设置。 */
export type BudgetSource = 'project' | 'global' | 'none'

export type DurationSource = 'history' | 'heuristic' | 'unknown'

export type CostSource = 'pricing' | 'local' | 'unknown'

/** 与任务类型（job_type）完全一致。 */
export type BudgetJobType =
  | 'script_pipeline'
  | 'storyboard'
  | 'asset_generation'
  | 'shot_image'
  | 'shot_audio'
  | 'shot_video'
  | 'render'

export type BudgetCapability = 'llm' | 'image' | 'video' | 'tts' | 'ffmpeg' | string

// --- 1. 价目表 -------------------------------------------------------------

export interface PricingItemDto {
  id: string
  capability: BudgetCapability
  provider: string
  model: string
  currency: string
  /** 整数 micro；null = 未配置单价（该能力的成本未知）。 */
  unit_price_micro: number | null
  /** 次计价单位（仅 LLM 输出 token），其余能力为 null。 */
  unit_price_secondary_micro: number | null
  /** 分辨率倍率：名称 -> 整数 micro 倍率（1_000_000 = 1.0）。 */
  resolution_multipliers: Record<string, number>
  configured: boolean
  note: string
  updated_at: string | null
}

export interface PricingCapabilityDto {
  capability: BudgetCapability
  label: string
  /** 基础数量单位：token / 张 / 秒 / 字符。 */
  base_unit: string
  /** 主计价单位展示名，例如「每 100 万 tokens」「每张」「每秒」。 */
  pricing_unit: string
  /** 一个计价单位包含多少基础数量。 */
  unit_scale: number
  /** 次计价单位展示名（仅 LLM），其余为 null。 */
  secondary_unit: string | null
  items: PricingItemDto[]
}

export interface PricingTableDto {
  currency: string
  micro_per_unit: number
  rounding: string
  capabilities: PricingCapabilityDto[]
}

export interface PricingSaveItem {
  capability: BudgetCapability
  provider: string
  model: string
  unit_price_micro: number | null
  unit_price_secondary_micro: number | null
  resolution_multipliers: Record<string, number>
  configured: boolean
  note: string
}

export interface PricingSavePayload {
  currency?: string
  items: PricingSaveItem[]
}

// --- 2. 预算配置 -----------------------------------------------------------

export interface BudgetConfigRowDto {
  scope_type: BudgetScopeType | ''
  scope_id: string
  currency: string
  soft_cost_micro: number | null
  hard_cost_micro: number | null
  soft_seconds: number | null
  hard_seconds: number | null
  enabled: boolean
  note: string
}

/** `effective`：生效预算（项目 > 父系列 > 全局 > 未设置）。 */
export interface EffectiveBudgetDto extends BudgetConfigRowDto {
  source: BudgetSource
  source_label: string
}

export interface BudgetConfigDto {
  project_id: string
  series_id: string
  global: BudgetConfigRowDto | null
  project: BudgetConfigRowDto | null
  series: BudgetConfigRowDto | null
  effective: EffectiveBudgetDto
}

export interface BudgetSavePayload {
  scope_type: BudgetScopeType
  scope_id: string
  currency?: string
  soft_cost_micro: number | null
  hard_cost_micro: number | null
  soft_seconds: number | null
  hard_seconds: number | null
  enabled: boolean
  note: string
}

// --- 3. 预算状态 -----------------------------------------------------------

export interface BudgetUsageDto {
  call_count: number
  unknown_call_count: number
  failed_call_count: number
  cost_known: boolean
}

/** `GET /api/budget/status` 与各响应内嵌的 `budget` / `status` 字段。 */
export interface BudgetStateDto {
  level: BudgetLevel
  /** `budget_exceeded` / `budget_soft_exceeded` / ''。 */
  code: string
  message: string
  reason: BudgetReason
  unlimited: boolean
  currency: string
  /** 项目已用成本是否「全部已知」；false 时 used_cost_micro 只是已知部分。 */
  cost_known: boolean
  soft_cost_micro: number | null
  hard_cost_micro: number | null
  soft_seconds: number | null
  hard_seconds: number | null
  used_cost_micro: number
  reserved_cost_micro: number
  committed_cost_micro: number
  projected_cost_micro: number
  used_seconds: number
  reserved_seconds: number
  projected_seconds: number
  estimate_cost_micro: number | null
  estimate_seconds: number | null
  budget_source: BudgetSource
  budget_source_label: string
  usage: BudgetUsageDto
  reservation_count: number
}

// --- 4. 估算 ---------------------------------------------------------------

export interface EstimateComponentDto {
  capability: BudgetCapability
  label: string
  component_label: string
  provider: string
  model: string
  quantity: number
  secondary_quantity: number
  base_unit: string
  resolution: string
  calls: number
  cost_micro: number | null
  cost_known: boolean
  estimated_seconds: number
}

export interface EstimateUnknownComponentDto {
  capability: BudgetCapability
  label: string
  provider: string
  model: string
  quantity: number
  /** 后端给出的未知原因（例如「未配置该 provider / 模型的单价」）。 */
  reason: string
}

export interface TaskEstimateDto {
  job_type: string
  job_type_label: string
  project_id: string
  shot_id: string
  currency: string
  estimated_cost_micro: number | null
  cost_known: boolean
  estimated_seconds: number | null
  duration_source: DurationSource
  components: EstimateComponentDto[]
  unknown_components: EstimateUnknownComponentDto[]
  note: string
}

export interface EstimateRequest {
  job_type: BudgetJobType | string
  project_id: string
  shot_id?: string
  shot_ids?: string[]
}

/** `POST /api/budget/estimate` 的响应。 */
export interface TaskEstimateResponse {
  job_type: string
  project_id: string
  shot_id: string
  estimate: TaskEstimateDto
  budget: BudgetStateDto
  /** 硬预算不足：界面必须禁用「确认执行」。 */
  blocked: boolean
  /** 软预算超支提示（非阻断）。 */
  warning: string
}

// --- 5. 汇总与用量明细 -----------------------------------------------------

export interface CapabilityUsageDto {
  capability: BudgetCapability
  label: string
  call_count: number
  cost_micro: number
  cost_known: boolean
  unknown_call_count: number
  quantity: number
  secondary_quantity: number
  seconds: number
  base_unit: string
  currency: string
}

export interface UsageSummaryDto {
  call_count: number
  cost_micro: number
  cost_known: boolean
  unknown_call_count: number
  failed_call_count: number
  duration_ms: number
  currency: string
  by_capability: CapabilityUsageDto[]
}

export interface UsageGroupDto {
  key: string
  call_count: number
  cost_micro: number
  cost_known: boolean
  unknown_call_count: number
  currency: string
}

export interface UsageRecordDto {
  id: string
  job_key: string
  job_id: string
  job_type: string
  job_status: string
  project_id: string
  series_id: string
  shot_id: string
  capability: BudgetCapability
  capability_label: string
  provider: string
  model: string
  quantity: number
  secondary_quantity: number
  base_unit: string
  resolution: string
  units: Record<string, unknown>
  status: 'succeeded' | 'failed' | 'cancelled' | string
  error_code: string
  cost_micro: number | null
  cost_known: boolean
  cost_source: CostSource
  currency: string
  duration_ms: number
  created_at: string | null
}

export interface UsageRecordPageDto {
  items: UsageRecordDto[]
  total: number
  page: number
  page_size: number
  pages: number
}

export interface UsageQueryParams {
  project_id?: string
  series_id?: string
  shot_id?: string
  job_id?: string
  job_key?: string
  capability?: string
  job_type?: string
  group_by?: string[]
  page?: number
  page_size?: number
}

export interface UsageResponseDto {
  filters: Record<string, string>
  summary: UsageSummaryDto
  groups: Record<string, UsageGroupDto[]>
  records: UsageRecordPageDto
  data_sources: { actual: string; estimate: string }
}

export interface RemainingWorkloadDto {
  currency: string
  cost_micro: number | null
  cost_known: boolean
  /** 已知部分成本（用于「部分未知」时给出下限）。 */
  partial_cost_micro: number
  seconds: number | null
  components: EstimateComponentDto[]
  unknown_components: EstimateUnknownComponentDto[]
}

export interface EpisodeCostDto {
  project_id: string
  title: string
  episode_number: number
  status: string
  used: {
    cost_micro: number
    cost_known: boolean
    unknown_call_count: number
    seconds: number
  }
  budget_status: BudgetStateDto
}

/** `GET /api/budget/summary` 的响应（项目 / 剧集页）。 */
export interface BudgetSummaryDto {
  project_id: string
  series_id: string
  is_episode: boolean
  currency: string
  used: {
    cost_micro: number
    cost_known: boolean
    unknown_call_count: number
    failed_call_count: number
    call_count: number
    seconds: number
    by_capability: CapabilityUsageDto[]
  }
  reserved: { cost_micro: number; seconds: number; count: number }
  remaining: RemainingWorkloadDto
  budget: EffectiveBudgetDto
  status: BudgetStateDto
  by_job_type: UsageGroupDto[]
  by_shot: UsageGroupDto[]
  by_capability: UsageGroupDto[]
  episodes: EpisodeCostDto[]
}

/** `GET /api/budget/jobs/{job_id}` 的响应：失败任务同样可查已发生成本。 */
export interface JobCostDetailDto {
  job_id: string
  job_key: string
  job_type: string
  status: string
  duration_seconds: number
  summary: UsageSummaryDto
  estimate: TaskEstimateDto | null
  records: UsageRecordPageDto
}

// --- 6. 任务 DTO 内嵌的成本块 ----------------------------------------------

/** `JobDto.cost`：单次任务的实际成本 + 启动前估算。 */
export interface JobCostDto {
  currency: string
  /** 未知时必为 null。 */
  cost_micro: number | null
  cost_known: boolean
  call_count: number
  unknown_call_count: number
  failed_call_count: number
  /** 供应商调用耗时（秒），与任务墙钟时长 `duration_seconds` 不同。 */
  provider_seconds: number
  by_capability: {
    capability: BudgetCapability
    call_count: number
    cost_micro: number
    cost_known: boolean
  }[]
  estimated_cost_micro: number | null
  estimated_cost_known: boolean
  estimated_seconds: number | null
  duration_source: DurationSource | ''
  has_usage: boolean
}

/** `GET /api/jobs/stats` 内嵌的成本块。 */
export interface JobStatsCostDto {
  currency: string
  cost_micro: number
  cost_known: boolean
  unknown_call_count: number
  call_count: number
}

/** 提交类接口在软预算超支时附加的字段。 */
export interface BudgetWarningFields {
  budget_level?: string
  budget_warning?: string
}

/** 硬预算超限时 HTTP 409 的响应体（detail 为对象）。 */
export interface BudgetBlockedDetail {
  ok: false
  status: string
  error_code: string
  message: string
  budget?: BudgetStateDto | null
  estimate?: TaskEstimateDto | null
}

export const BUDGET_BLOCKED_STATUS = 'budget_blocked'
export const BUDGET_EXCEEDED_CODE = 'budget_exceeded'
export const BUDGET_SOFT_EXCEEDED_CODE = 'budget_soft_exceeded'

/** 模型端点未配置时 HTTP 409 的响应体（detail 为对象），任务不会启动。 */
export interface ProviderBlockedDetail {
  ok: false
  status: string
  error_code: string
  message: string
  missing?: Array<{ capability: string; label?: string; message?: string }>
}

export const PROVIDER_BLOCKED_STATUS = 'provider_not_configured'
export const PROVIDER_NOT_CONFIGURED_CODE = 'provider_not_configured'

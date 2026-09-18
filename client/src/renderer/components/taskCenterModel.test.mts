import assert from 'node:assert/strict'

import {
  ACTIVE_STATUSES,
  DEFAULT_FILTERS,
  EMPTY_FILTERED_TEXT,
  applyJobEvent,
  emptyStateText,
  errorSummary,
  filterJobs,
  matchesFilters,
  formatDuration,
  formatRelativeTime,
  jobActionState,
  jobSection,
  mergeJobLists,
  nextReconnectDelay,
  normalizeJob,
  normalizeJobList,
  progressText,
  projectJumpDetail,
  queryFromFilters,
  sectionTabAriaProps,
  sortJobs,
  statusTone,
  summarizeJobs,
  upsertJob,
} from './taskCenterModel.ts'
import { resolveWorkspaceTabIndex } from './workspaceTabs.ts'

const ACTIVE_STATES = ['queued', 'running', 'cancelling']
const RETRYABLE_STATES = ['failed', 'cancelled', 'interrupted']

function makeJob(overrides: Record<string, unknown> = {}) {
  const status = (overrides.status as string) || 'running'
  const active = ACTIVE_STATES.indexOf(status) >= 0
  const retryable = RETRYABLE_STATES.indexOf(status) >= 0
  const job = normalizeJob({
    id: 'job-1',
    scope: 'project:p1',
    project_id: 'p1',
    job_type: 'render',
    job_type_label: '成片渲染',
    display_name: '成片渲染 · 项目一',
    status,
    status_label: '进行中',
    progress: 40,
    current_step: 'rendering',
    message: '正在合成',
    error_code: '',
    error_message: '',
    attempt: 1,
    retry_of: null,
    version: 1,
    created_at: '2025-01-01T10:00:00',
    started_at: '2025-01-01T10:00:00',
    updated_at: '2025-01-01T10:01:00',
    finished_at: null,
    cancel_requested_at: null,
    duration_seconds: 60,
    eta_seconds: null,
    is_active: active,
    is_terminal: !active,
    has_active_successor: false,
    can_cancel: active,
    can_retry: retryable,
    can_resume: retryable,
    can_delete: !active,
    retry_blocked_reason: '',
    resume_blocked_reason: '',
    ...overrides,
  })
  if (!job) throw new Error('normalizeJob returned null')
  return job
}

// --- 归一化 ---------------------------------------------------------------

assert.equal(normalizeJob(null), null, '空值不应产生任务对象')
assert.equal(normalizeJob({ scope: 'project:p1' }), null, '缺少 id 的任务必须被丢弃')
assert.equal(normalizeJobList('nope').length, 0, '非数组输入应返回空列表')
assert.equal(normalizeJobList([{ id: 'a' }, null, 'x']).length, 1, '列表里的脏数据应被逐个丢弃')

const withoutRunToken = normalizeJob({ id: 'x', status: 'running', run_token: 'secret' }) as unknown as Record<string, unknown>
assert.equal('run_token' in withoutRunToken, false, 'DTO 归一化不得保留 run token 之类的内部字段')

const clamped = makeJob({ progress: 250 })
assert.equal(clamped.progress, 100, '进度必须夹在 0-100 之间')
assert.equal(makeJob({ status: 'failed', status_label: '' }).status_label, '失败', '缺少 label 时按稳定状态表补齐')

// --- 去重与合并 -----------------------------------------------------------

const running = makeJob()
const newer = makeJob({ status: 'completed', progress: 100, updated_at: '2025-01-01T10:05:00' })
const stale = makeJob({ status: 'queued', progress: 1, updated_at: '2025-01-01T09:00:00' })

assert.equal(upsertJob([running], newer).length, 1, '同一 id 的更新不能产生重复条目')
assert.equal(upsertJob([running], newer)[0].status, 'completed', '更新的状态应被采纳')
assert.equal(upsertJob([newer], stale)[0].status, 'completed', '更旧的乱序事件必须被丢弃')

const merged = mergeJobLists([running], [makeJob({ id: 'job-2', display_name: '另一个任务' })])
assert.equal(merged.length, 2, '不同 id 的任务应合并进列表')
assert.equal(new Set(merged.map((job) => job.id)).size, merged.length, '合并后不允许出现重复 id')

// --- WebSocket 事件 -------------------------------------------------------

const fromEvent = applyJobEvent([running], { type: 'job.progress', job: newer as never })
assert.equal(fromEvent.length, 1)
assert.equal(fromEvent[0].progress, 100, '进度事件应就地更新同一条任务')

const snapshot = applyJobEvent([running], {
  type: 'job_snapshot',
  jobs: [newer as never, makeJob({ id: 'job-3', job_type: 'shot_video' }) as never],
})
assert.equal(snapshot.length, 2, '快照应合并进本地列表')
assert.equal(snapshot.find((job) => job.id === 'job-1')?.status, 'completed')

const untouched = [running]
assert.equal(applyJobEvent(untouched, { type: 'pong' }), untouched, '无关消息不应改变任务列表')
assert.equal(applyJobEvent(untouched, null), untouched, '空事件不应改变任务列表')

// --- 筛选与排序 -----------------------------------------------------------

const failed = makeJob({ id: 'job-failed', status: 'failed', status_label: '失败', can_retry: true, project_id: 'p2', job_type: 'shot_video', error_message: '视频生成失败', updated_at: '2025-01-01T09:30:00' })
const interrupted = makeJob({ id: 'job-interrupted', status: 'interrupted', status_label: '已中断', can_retry: true, can_resume: true, project_id: 'p1', job_type: 'storyboard', updated_at: '2025-01-01T09:40:00' })
const completed = makeJob({ id: 'job-done', status: 'completed', status_label: '已完成', progress: 100, project_id: 'p1', job_type: 'render', updated_at: '2025-01-01T09:50:00' })
const all = [running, failed, interrupted, completed]

assert.equal(filterJobs(all, { ...DEFAULT_FILTERS, projectId: 'p1' }).length, 3, '项目筛选应只保留该项目任务')
assert.equal(filterJobs(all, { ...DEFAULT_FILTERS, statuses: ['failed'] }).length, 1, '状态筛选应生效')
assert.equal(filterJobs(all, { ...DEFAULT_FILTERS, jobTypes: ['shot_video'] }).length, 1, '类型筛选应生效')
assert.equal(filterJobs(all, { ...DEFAULT_FILTERS, onlyActive: true }).length, 1, '仅看进行中应只保留活动任务')
assert.equal(filterJobs(all, { ...DEFAULT_FILTERS, search: '视频生成失败' }).length, 1, '关键词应能命中错误摘要')
assert.equal(filterJobs(all, { ...DEFAULT_FILTERS, search: 'p2' }).length, 1, '关键词应能命中项目 ID')

assert.deepEqual(
  sortJobs(all, 'updated').map((job) => job.id),
  ['job-1', 'job-done', 'job-interrupted', 'job-failed'],
  '默认按 updated_at 倒序',
)
assert.equal(sortJobs(all, 'status')[0].id, 'job-1', '状态排序应把进行中的任务排在最前')
assert.equal(sortJobs(all, 'progress')[0].progress, 100, '进度排序应把进度高的排在最前')

// --- 汇总 -----------------------------------------------------------------

const summary = summarizeJobs(all)
assert.equal(summary.activeCount, 1, '活动任务数量应只统计 queued/running/cancelling')
assert.equal(summary.failedCount, 1, '失败数量应只统计 failed')
assert.equal(summary.interruptedCount, 1, '中断数量应只统计 interrupted')
assert.equal(summary.retryableCount, 2, '可重试数量应来自服务端 DTO 的 can_retry')
assert.equal(summary.latest?.id, 'job-1', '最近一次任务应按更新时间取最新')
assert.deepEqual(ACTIVE_STATUSES, ['queued', 'running', 'cancelling'])

// --- 动作按钮状态 ---------------------------------------------------------

const runningActions = jobActionState(running)
assert.equal(runningActions.cancel.enabled, true, '进行中的任务可以取消')
assert.equal(runningActions.retry.enabled, false, '进行中的任务不能重试')
assert.equal(runningActions.remove.enabled, false, '进行中的任务不能删除')
assert.match(runningActions.retry.reason, /重试|不可/)

const failedActions = jobActionState(failed)
assert.equal(failedActions.retry.enabled, true, '失败任务可以重试')
assert.equal(failedActions.cancel.enabled, false, '终态任务不能取消')

const blocked = makeJob({
  id: 'job-blocked',
  status: 'failed',
  can_retry: false,
  can_resume: false,
  can_delete: true,
  retry_blocked_reason: '该任务已有正在执行的新尝试',
})
const blockedActions = jobActionState(blocked)
assert.equal(blockedActions.retry.enabled, false)
assert.equal(blockedActions.retry.reason, '该任务已有正在执行的新尝试', '禁用原因应直接来自服务端')
assert.equal(blockedActions.remove.enabled, true)

// --- 分组 / 语气 ----------------------------------------------------------

assert.equal(jobSection('running'), 'active')
assert.equal(jobSection('cancelling'), 'active')
assert.equal(jobSection('failed'), 'failed')
assert.equal(jobSection('interrupted'), 'interrupted')
assert.equal(jobSection('cancelled'), 'cancelled')
assert.equal(jobSection('completed'), 'completed')
assert.equal(statusTone('running'), 'active')
assert.equal(statusTone('completed'), 'success')
assert.equal(statusTone('failed'), 'danger')
assert.equal(statusTone('interrupted'), 'muted')

// --- 格式化 ---------------------------------------------------------------

assert.equal(formatDuration(0), '0 秒')
assert.equal(formatDuration(59), '59 秒')
assert.equal(formatDuration(65), '1 分 05 秒')
assert.equal(formatDuration(3725), '1 小时 02 分')
assert.equal(formatRelativeTime(null), '—')
assert.equal(formatRelativeTime('not-a-date'), '—')
const now = new Date('2025-01-01T12:00:00').getTime()
assert.equal(formatRelativeTime('2025-01-01T11:59:30', now), '30 秒前')
assert.equal(formatRelativeTime('2025-01-01T11:30:00', now), '30 分钟前')
assert.equal(formatRelativeTime('2025-01-01T09:00:00', now), '3 小时前')
assert.equal(formatRelativeTime('2024-12-30T09:00:00', now), '12-30')
assert.equal(progressText(makeJob({ progress: 37 })), '37%')
assert.equal(progressText(makeJob({ status: 'completed', progress: 0 })), '100%')
assert.equal(errorSummary(failed).startsWith('job_failed'), false)
assert.equal(errorSummary(makeJob({ error_code: 'provider_error', error_message: '模型不可用' })), 'provider_error：模型不可用')

// --- 查询参数 / 重连 / ARIA / 跳转 ---------------------------------------

assert.deepEqual(queryFromFilters(DEFAULT_FILTERS), { page: 1, page_size: 50 })
const params = queryFromFilters({ ...DEFAULT_FILTERS, projectId: 'p1', statuses: ['failed'], jobTypes: ['render'], onlyActive: true, search: ' x ' })
assert.equal(params.project_id, 'p1')
assert.deepEqual(params.status, ['failed'])
assert.deepEqual(params.job_type, ['render'])
assert.equal(params.active_only, true)
assert.equal(params.q, 'x')

assert.equal(nextReconnectDelay(0), 1000)
assert.equal(nextReconnectDelay(1), 2000)
assert.equal(nextReconnectDelay(4), 15000, '重连退避必须有上限')
assert.equal(nextReconnectDelay(20), 15000)

const selectedTab = sectionTabAriaProps('active', 'active')
assert.equal(selectedTab['aria-selected'], true)
assert.equal(selectedTab.tabIndex, 0)
assert.equal(selectedTab.role, 'tab')
const otherTab = sectionTabAriaProps('failed', 'active')
assert.equal(otherTab['aria-selected'], false)
assert.equal(otherTab.tabIndex, -1, 'roving tabindex：非选中标签不进入 Tab 序列')
assert.equal(otherTab['aria-controls'], selectedTab['aria-controls'], '标签与面板的 ARIA 关系必须成对')
assert.equal(resolveWorkspaceTabIndex('ArrowRight', 0, 3), 1, '方向键应在分组标签间移动')
assert.equal(resolveWorkspaceTabIndex('End', 0, 3), 2)
assert.equal(resolveWorkspaceTabIndex('Escape', 0, 3), null, '未处理的按键不得被拦截')

assert.equal(matchesFilters(failed, { ...DEFAULT_FILTERS, projectId: 'p1' }), false, '项目维度必须经过统一的筛选入口')
assert.equal(matchesFilters(failed, { ...DEFAULT_FILTERS, projectId: 'p2' }), true)

assert.deepEqual(projectJumpDetail(failed), { projectId: 'p2' })
assert.equal(projectJumpDetail(makeJob({ project_id: '' })), null, '没有项目的任务不提供跳转')

assert.equal(emptyStateText(false, false).includes('还没有'), true, '空状态文案应稳定')
assert.equal(emptyStateText(true, true), EMPTY_FILTERED_TEXT, '筛选无结果应给出区分文案')

console.log('taskCenterModel.test.mts ok')

"""后台任务的稳定词汇表：状态机、任务类型与错误码。

任务中心只依赖稳定标识做分支（`job_type` / `status` / `error_code`），中文提示
只用于展示。所有模块（task_registry、job_center、jobs 路由、WebSocket 事件）
都从这里取词表，避免出现第二套任务系统或第二套状态取值。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# --- 任务状态 -------------------------------------------------------------

STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_CANCELLING = "cancelling"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"
STATUS_CANCELLED = "cancelled"
STATUS_INTERRUPTED = "interrupted"

JOB_STATUSES = (
    STATUS_QUEUED,
    STATUS_RUNNING,
    STATUS_CANCELLING,
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_CANCELLED,
    STATUS_INTERRUPTED,
)
ACTIVE_STATUSES = (STATUS_QUEUED, STATUS_RUNNING, STATUS_CANCELLING)
TERMINAL_STATUSES = (STATUS_COMPLETED, STATUS_FAILED, STATUS_CANCELLED, STATUS_INTERRUPTED)
# 允许「重试」的终态：完成的成果不应被重跑，正在执行的必须走取消。
RETRYABLE_STATUSES = (STATUS_FAILED, STATUS_CANCELLED, STATUS_INTERRUPTED)

STATUS_LABELS = {
    STATUS_QUEUED: "排队中",
    STATUS_RUNNING: "进行中",
    STATUS_CANCELLING: "取消中",
    STATUS_COMPLETED: "已完成",
    STATUS_FAILED: "失败",
    STATUS_CANCELLED: "已取消",
    STATUS_INTERRUPTED: "已中断",
}

# 明确的状态迁移规则：终态是吸收态，任何执行路径都不能把终态直接改回 running。
# 需要「再跑一次」时必须走重试，由重试新建一行 attempt+1，而不是复活旧行。
ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    STATUS_QUEUED: frozenset({STATUS_RUNNING, STATUS_CANCELLING, STATUS_CANCELLED, STATUS_FAILED, STATUS_INTERRUPTED}),
    STATUS_RUNNING: frozenset(
        {STATUS_CANCELLING, STATUS_COMPLETED, STATUS_FAILED, STATUS_CANCELLED, STATUS_INTERRUPTED}
    ),
    # cancelling 只允许收敛到终态：由持有 run token 的协程或作用域取消负责。
    STATUS_CANCELLING: frozenset(
        {STATUS_CANCELLED, STATUS_COMPLETED, STATUS_FAILED, STATUS_INTERRUPTED}
    ),
    STATUS_COMPLETED: frozenset(),
    STATUS_FAILED: frozenset(),
    STATUS_CANCELLED: frozenset(),
    STATUS_INTERRUPTED: frozenset(),
}


def can_transition(current: str | None, target: str) -> bool:
    """判断一次状态写入是否合法；未知状态一律拒绝，避免脏数据扩散。"""

    if target not in ALLOWED_TRANSITIONS:
        return False
    if current is None:
        return target == STATUS_QUEUED
    return target in ALLOWED_TRANSITIONS.get(current, frozenset())


def status_label(status: str) -> str:
    return STATUS_LABELS.get(status, "未知状态")


# --- 任务类型 -------------------------------------------------------------

JOB_TYPE_SCRIPT_PIPELINE = "script_pipeline"
JOB_TYPE_STORYBOARD = "storyboard"
JOB_TYPE_ASSET_GENERATION = "asset_generation"
JOB_TYPE_SHOT_IMAGE = "shot_image"
JOB_TYPE_SHOT_AUDIO = "shot_audio"
JOB_TYPE_SHOT_VIDEO = "shot_video"
JOB_TYPE_RENDER = "render"
JOB_TYPE_AV_PREVIEW = "av_preview"
JOB_TYPE_UNKNOWN = "unknown"

JOB_TYPES = (
    JOB_TYPE_SCRIPT_PIPELINE,
    JOB_TYPE_STORYBOARD,
    JOB_TYPE_ASSET_GENERATION,
    JOB_TYPE_SHOT_IMAGE,
    JOB_TYPE_SHOT_AUDIO,
    JOB_TYPE_SHOT_VIDEO,
    JOB_TYPE_RENDER,
    JOB_TYPE_AV_PREVIEW,
)

JOB_TYPE_LABELS = {
    JOB_TYPE_SCRIPT_PIPELINE: "剧本解析",
    JOB_TYPE_STORYBOARD: "分镜与素材",
    JOB_TYPE_ASSET_GENERATION: "素材生成",
    JOB_TYPE_SHOT_IMAGE: "镜头故事板",
    JOB_TYPE_SHOT_AUDIO: "镜头配音",
    JOB_TYPE_SHOT_VIDEO: "镜头视频",
    JOB_TYPE_RENDER: "成片渲染",
    JOB_TYPE_AV_PREVIEW: "混音预览",
    JOB_TYPE_UNKNOWN: "其他任务",
}

# 幂等键形如 owner_type:owner_id:operation[:qualifier]。
_OPERATION_TO_JOB_TYPE = {
    ("project", "pipeline"): JOB_TYPE_SCRIPT_PIPELINE,
    ("project", "storyboard"): JOB_TYPE_STORYBOARD,
    ("project", "assets"): JOB_TYPE_ASSET_GENERATION,
    ("project", "render"): JOB_TYPE_RENDER,
    ("project", "audio_preview"): JOB_TYPE_AV_PREVIEW,
    ("shot", "storyboard"): JOB_TYPE_SHOT_IMAGE,
    ("shot", "audio"): JOB_TYPE_SHOT_AUDIO,
    ("shot", "video"): JOB_TYPE_SHOT_VIDEO,
}

# 可以从已有数据库状态 / 中间产物继续执行的任务类型（任务中心的「续跑」按钮）。
RESUMABLE_JOB_TYPES = frozenset(
    {
        JOB_TYPE_SCRIPT_PIPELINE,
        JOB_TYPE_STORYBOARD,
        JOB_TYPE_ASSET_GENERATION,
        JOB_TYPE_SHOT_IMAGE,
        JOB_TYPE_SHOT_AUDIO,
        JOB_TYPE_SHOT_VIDEO,
        JOB_TYPE_RENDER,
    }
)

# services/job_dispatch 真正实现了重新派发的任务类型；其余类型按钮直接禁用，
# 而不是让用户点了以后才拿到 500。
DISPATCHABLE_JOB_TYPES = frozenset(
    {
        JOB_TYPE_SCRIPT_PIPELINE,
        JOB_TYPE_STORYBOARD,
        JOB_TYPE_SHOT_IMAGE,
        JOB_TYPE_SHOT_VIDEO,
        JOB_TYPE_RENDER,
    }
)

_ARCHIVED_KEY_SUFFIX = re.compile(r"#attempt-[0-9]+$")


@dataclass(frozen=True)
class JobKey:
    """从幂等键解析出的业务身份。"""

    raw: str
    owner_type: str
    owner_id: str
    operation: str
    qualifier: str
    job_type: str

    @property
    def canonical(self) -> str:
        """去掉历史尝试后缀的规范键；新的尝试总是占用规范键。"""

        return _ARCHIVED_KEY_SUFFIX.sub("", self.raw)

    @property
    def archived(self) -> bool:
        return bool(_ARCHIVED_KEY_SUFFIX.search(self.raw))


def parse_job_key(key: str) -> JobKey:
    base = _ARCHIVED_KEY_SUFFIX.sub("", key or "")
    parts = base.split(":")
    owner_type = parts[0] if parts else ""
    owner_id = parts[1] if len(parts) > 1 else ""
    operation = parts[2] if len(parts) > 2 else ""
    qualifier = ":".join(parts[3:]) if len(parts) > 3 else ""
    job_type = _OPERATION_TO_JOB_TYPE.get((owner_type, operation), JOB_TYPE_UNKNOWN)
    return JobKey(
        raw=key,
        owner_type=owner_type,
        owner_id=owner_id,
        operation=operation,
        qualifier=qualifier,
        job_type=job_type,
    )


def archived_key(key: str, attempt: int) -> str:
    """把某次尝试的幂等键归档：保留可追溯的历史行，同时释放规范键。"""

    canonical = _ARCHIVED_KEY_SUFFIX.sub("", key or "")
    return f"{canonical}#attempt-{max(1, int(attempt))}"


def job_type_label(job_type: str) -> str:
    return JOB_TYPE_LABELS.get(job_type, JOB_TYPE_LABELS[JOB_TYPE_UNKNOWN])


# --- 错误码 ---------------------------------------------------------------

ERROR_CODE_JOB_FAILED = "job_failed"
ERROR_CODE_JOB_CANCELLED = "job_cancelled"
ERROR_CODE_JOB_INTERRUPTED = "job_interrupted"
ERROR_CODE_SERVER_RESTART = "server_restart"
ERROR_CODE_TIMEOUT = "timeout"
ERROR_CODE_PROVIDER = "provider_error"
ERROR_CODE_CONFIG = "provider_config_error"
ERROR_CODE_STORAGE = "storage_error"
ERROR_CODE_VALIDATION = "invalid_request"
ERROR_CODE_NOT_FOUND = "job_not_found"
ERROR_CODE_NOT_RETRYABLE = "job_not_retryable"
ERROR_CODE_NOT_RESUMABLE = "job_not_resumable"
ERROR_CODE_SCOPE_CONFLICT = "scope_conflict"
ERROR_CODE_ALREADY_RUNNING = "job_already_running"
ERROR_CODE_UNSUPPORTED = "job_type_unsupported"
# 预算相关：硬预算超限会直接阻止任务启动，因此必须是稳定且可被前端分支的错误码。
ERROR_CODE_BUDGET_EXCEEDED = "budget_exceeded"
ERROR_CODE_BUDGET_SOFT_EXCEEDED = "budget_soft_exceeded"

_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (ERROR_CODE_BUDGET_EXCEEDED, ("budget_exceeded", "超出项目硬预算", "硬预算", "预算不足")),
    (ERROR_CODE_BUDGET_SOFT_EXCEEDED, ("budget_soft_exceeded", "软预算")),
    (ERROR_CODE_SERVER_RESTART, ("server restarted", "restart")),
    (ERROR_CODE_JOB_CANCELLED, ("cancel", "取消", "版本已变化")),
    (ERROR_CODE_TIMEOUT, ("timeout", "timed out", "超时")),
    (ERROR_CODE_CONFIG, ("api key", "未配置", "unauthorized", "401", "403", "缺少")),
    (ERROR_CODE_PROVIDER, ("provider", "供应商", "connection", "connect", "http")),
    (ERROR_CODE_STORAGE, ("disk", "storage", "no space", "磁盘", "存储")),
)


def classify_error_code(text: str) -> str:
    """把一段脱敏后的失败文本归到稳定错误码；识别不出时返回通用失败码。"""

    haystack = (text or "").lower()
    if not haystack.strip():
        return ERROR_CODE_JOB_FAILED
    for code, needles in _RULES:
        if any(needle.lower() in haystack for needle in needles):
            return code
    return ERROR_CODE_JOB_FAILED


def error_code_for_status(status: str, text: str = "") -> str:
    if status == STATUS_CANCELLED:
        return ERROR_CODE_JOB_CANCELLED
    if status == STATUS_INTERRUPTED:
        return ERROR_CODE_SERVER_RESTART
    if status == STATUS_COMPLETED:
        return ""
    return classify_error_code(text)


__all__ = [
    "ACTIVE_STATUSES",
    "ALLOWED_TRANSITIONS",
    "DISPATCHABLE_JOB_TYPES",
    "ERROR_CODE_ALREADY_RUNNING",
    "ERROR_CODE_BUDGET_EXCEEDED",
    "ERROR_CODE_BUDGET_SOFT_EXCEEDED",
    "ERROR_CODE_CONFIG",
    "ERROR_CODE_JOB_CANCELLED",
    "ERROR_CODE_JOB_FAILED",
    "ERROR_CODE_JOB_INTERRUPTED",
    "ERROR_CODE_NOT_FOUND",
    "ERROR_CODE_NOT_RESUMABLE",
    "ERROR_CODE_NOT_RETRYABLE",
    "ERROR_CODE_PROVIDER",
    "ERROR_CODE_SCOPE_CONFLICT",
    "ERROR_CODE_SERVER_RESTART",
    "ERROR_CODE_STORAGE",
    "ERROR_CODE_TIMEOUT",
    "ERROR_CODE_UNSUPPORTED",
    "ERROR_CODE_VALIDATION",
    "JOB_STATUSES",
    "JOB_TYPES",
    "JOB_TYPE_ASSET_GENERATION",
    "JOB_TYPE_AV_PREVIEW",
    "JOB_TYPE_LABELS",
    "JOB_TYPE_RENDER",
    "JOB_TYPE_SCRIPT_PIPELINE",
    "JOB_TYPE_SHOT_AUDIO",
    "JOB_TYPE_SHOT_IMAGE",
    "JOB_TYPE_SHOT_VIDEO",
    "JOB_TYPE_STORYBOARD",
    "JOB_TYPE_UNKNOWN",
    "JobKey",
    "RESUMABLE_JOB_TYPES",
    "RETRYABLE_STATUSES",
    "STATUS_CANCELLED",
    "STATUS_CANCELLING",
    "STATUS_COMPLETED",
    "STATUS_FAILED",
    "STATUS_INTERRUPTED",
    "STATUS_LABELS",
    "STATUS_QUEUED",
    "STATUS_RUNNING",
    "TERMINAL_STATUSES",
    "archived_key",
    "can_transition",
    "classify_error_code",
    "error_code_for_status",
    "job_type_label",
    "parse_job_key",
    "status_label",
]

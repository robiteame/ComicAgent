"""路由层的任务抢占守卫：把预算阻断转成稳定、可解析的 409 响应。

所有启动后台任务的入口都经过这里，因此「硬预算阻止任务启动」只需要在抢占处实现
一次（services/task_registry.claim_job），不会被某条遗漏的路径绕过。

约定：
- 抢占成功 + 配置了软预算并已超支 -> 响应里带 budget_warning（提示但不阻断）；
- 抢占失败 + 预算超限 -> 409，detail.error_code = budget_exceeded；
- 抢占失败 + 作用域被占 -> 交给调用方按既有「已有任务在运行」去重逻辑处理。
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from services import budget_service
from services.task_registry import ClaimResult, claim_job


class BudgetBlockedError(HTTPException):
    """硬预算不足：阻止任务启动（HTTP 409 + error_code=budget_exceeded）。"""

    def __init__(self, result: ClaimResult):
        details: dict[str, Any] = result.budget.get("details") if isinstance(result.budget, dict) else None
        super().__init__(
            status_code=409,
            detail={
                "ok": False,
                "status": "budget_blocked",
                "error_code": result.error_code or budget_service.CODE_BUDGET_EXCEEDED,
                "message": result.message or "已超出项目硬预算，任务未启动",
                "budget": details or {},
                "estimate": (result.budget or {}).get("estimate") if isinstance(result.budget, dict) else None,
            },
        )


def claim_or_block(key: str, scope: str, **kwargs: Any) -> ClaimResult:
    """抢占任务；被硬预算拦下时抛 409，其余失败原因原样返回给调用方。"""

    result = claim_job(key, scope, **kwargs)
    if not result.claimed and result.blocked_by_budget:
        raise BudgetBlockedError(result)
    return result


def budget_notice(result: ClaimResult | None) -> dict[str, Any]:
    """把软预算提示合并进成功响应（未触发时返回空 dict）。"""

    if result is None or not isinstance(result.budget, dict):
        return {}
    details = result.budget.get("details") or {}
    level = str(result.budget.get("level") or "")
    if level != budget_service.LEVEL_SOFT_EXCEEDED:
        return {}
    return {
        "budget_level": level,
        "budget_warning": str(details.get("message") or "已超出项目软预算"),
    }


__all__ = ["BudgetBlockedError", "budget_notice", "claim_or_block"]

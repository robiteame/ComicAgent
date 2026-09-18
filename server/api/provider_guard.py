"""路由层的 Provider 配置预检守卫：把缺失配置转成稳定、可解析的 409 响应。

与 ``claim_guard``（预算闸门）并列的任务启动闸门：所有会消耗模型能力的任务
入口在抢占任务槽位前先做预检，缺配置时任务根本不启动。

响应约定（HTTP 409）：
    detail = {
        "ok": False,
        "status": "provider_not_configured",
        "error_code": "provider_not_configured",
        "message": "以下模型端点尚未配置 API Key：……",
        "missing": [{"capability": "voice", "label": "配音（TTS）", "message": "……"}],
    }
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from services.provider_readiness import (
    CODE_PROVIDER_NOT_CONFIGURED,
    ProviderNotConfiguredError,
    missing_providers,
)


class ProviderNotConfigured(HTTPException):
    """模型端点未配置：阻止任务启动（HTTP 409 + error_code=provider_not_configured）。"""

    def __init__(self, missing: list[dict]):
        super().__init__(
            status_code=409,
            detail={
                "ok": False,
                "status": CODE_PROVIDER_NOT_CONFIGURED,
                "error_code": CODE_PROVIDER_NOT_CONFIGURED,
                "message": ProviderNotConfiguredError(missing).message,
                "missing": missing,
            },
        )


def ensure_providers_ready(job_type: str, **hints: Any) -> None:
    """预检某类任务的 Provider 配置；缺失时抛 409。"""

    try:
        missing = missing_providers(job_type, **hints)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if missing:
        raise ProviderNotConfigured(missing)


__all__ = ["ProviderNotConfigured", "ensure_providers_ready"]

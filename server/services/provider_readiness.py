"""任务启动前的 Provider 配置预检。

在 API 入口启动后台任务之前，同步检查本次任务真正需要的模型端点是否已配置；
缺失时立即以稳定错误拒绝启动（error_code=provider_not_configured），而不是让
任务排队后才在执行中途因缺少密钥失败。

检查口径（缺什么才拦什么，能自动回退的能力不拦截）：
- script：LLM 主/备端点至少一个配置了 API Key（与 ``LLMService.available`` 同口径，
  备端点需与主端点不是同一个服务地址）；
- image：永不拦截 —— 未配置密钥时图像服务自动回退占位图（既有约定，见
  ``image_service._resolve_route``）；
- video：视频端点必须配置 API Key（视频没有本地回退）；
- voice：默认必须配置；但当视频适配器声明原生音频能力且已接入厂商实现
  （``audio_routing.native_audio_capable``）时不强制 —— 视频模型能随画面直出
  对白语音时，独立 TTS 不再是必需品。
"""

from __future__ import annotations

from services.providers.endpoint import endpoint_identity, get_endpoint

CODE_PROVIDER_NOT_CONFIGURED = "provider_not_configured"

# 支持预检的任务类型（与预算 job_type 口径对齐的子集）。
READY_JOB_TYPES = ("script_pipeline", "shot_video", "shot_audio")

CAPABILITY_LABELS = {
    "script": "剧本解析（LLM）",
    "video": "视频生成模型",
    "voice": "配音（TTS）",
}


class ProviderNotConfiguredError(RuntimeError):
    """预检未通过：携带缺失项列表，由路由层转成结构化 HTTP 响应。"""

    def __init__(self, missing: list[dict]):
        self.missing = missing
        self.message = format_message(missing)
        super().__init__(self.message)


def voice_endpoint_configured() -> bool:
    """语音端点是否配置了 API Key。"""
    return bool(str(get_endpoint("voice").api_key or "").strip())


def native_video_audio_ready(endpoint=None) -> bool:
    """视频端点是否具备真正可用的原生音频能力（能力声明 + 厂商实现已接入）。"""

    from services.audio_routing import native_audio_capable  # 局部导入，避免循环依赖

    return native_audio_capable(endpoint)


def missing_providers(
    job_type: str,
    *,
    mode: str = "",
    has_dialogue: bool | None = None,
    audio_mode_override: str = "",
) -> list[dict]:
    """返回某类任务启动前缺失的 Provider 配置列表；空列表表示可以启动。

    - ``mode``：script_pipeline 的运行模式；auto 模式端到端跑完，还需要视频/配音。
    - ``has_dialogue``：shot_video 用；镜头没有台词时根本不会调用 TTS。
    - ``audio_mode_override``：镜头级音频路径覆盖；显式指定 tts 时必须配置语音端点。
    """

    job_type = str(job_type or "").strip().lower()
    if job_type == "script_pipeline":
        issues = []
        if not _script_ready():
            issues.append(_issue("script"))
        if str(mode or "").strip().lower() == "auto":
            if not _video_ready():
                issues.append(_issue("video"))
            voice = _voice_issue(has_dialogue=True, audio_mode_override="")
            if voice:
                issues.append(voice)
        return issues
    if job_type == "shot_video":
        issues = []
        if not _video_ready():
            issues.append(_issue("video"))
        voice = _voice_issue(has_dialogue=has_dialogue, audio_mode_override=audio_mode_override)
        if voice:
            issues.append(voice)
        return issues
    if job_type == "shot_audio":
        # 纯配音任务本身就是 TTS 调用，原生音频能力替代不了它。
        voice = _voice_issue(has_dialogue=True, audio_mode_override="tts")
        return [voice] if voice else []
    raise ValueError(f"未知任务类型: {job_type or '<empty>'}，可选值: {', '.join(READY_JOB_TYPES)}")


def ensure_task_providers_ready(job_type: str, **hints) -> None:
    """预检不通过时抛出 ``ProviderNotConfiguredError``。"""

    missing = missing_providers(job_type, **hints)
    if missing:
        raise ProviderNotConfiguredError(missing)


def format_message(missing: list[dict]) -> str:
    names = "、".join(str(item.get("label") or item.get("capability") or "") for item in missing)
    return f"以下模型端点尚未配置 API Key：{names}。请在「系统设置 → 模型服务」补齐后重试。"


# ---------------------------------------------------------------------------
# 各能力的配置判定
# ---------------------------------------------------------------------------


def _script_ready() -> bool:
    endpoint = get_endpoint("script")
    if str(endpoint.api_key or "").strip():
        return True
    # 备端点：配置了密钥、且与主端点不是同一个服务地址时可用（与 LLMService 口径一致）。
    fallback = get_endpoint("script_fallback")
    return bool(str(fallback.api_key or "").strip()) and endpoint_identity(fallback.base_url) != endpoint_identity(
        endpoint.base_url
    )


def _video_ready() -> bool:
    return bool(str(get_endpoint("video").api_key or "").strip())


def _voice_issue(*, has_dialogue: bool | None, audio_mode_override: str) -> dict | None:
    if has_dialogue is False:
        return None  # 没有台词的镜头不会调用 TTS
    override = str(audio_mode_override or "").strip().lower()
    if override == "native":
        return None
    if override != "tts" and native_video_audio_ready():
        # 视频模型支持原生对白语音：不强制要求 TTS。
        return None
    if voice_endpoint_configured():
        return None
    return _issue("voice")


def _issue(capability: str) -> dict:
    return {
        "capability": capability,
        "label": CAPABILITY_LABELS.get(capability, capability),
        "message": f"{CAPABILITY_LABELS.get(capability, capability)}未配置 API Key",
    }


__all__ = [
    "CODE_PROVIDER_NOT_CONFIGURED",
    "READY_JOB_TYPES",
    "ProviderNotConfiguredError",
    "ensure_task_providers_ready",
    "format_message",
    "missing_providers",
    "native_video_audio_ready",
    "voice_endpoint_configured",
]

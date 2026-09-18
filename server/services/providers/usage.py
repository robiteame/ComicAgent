"""统一的用量元数据（usage metadata）。

所有协议适配器都用这一种结构描述「这次调用消耗了什么」：token、张数、秒数、字符数、
分辨率与供应商调用耗时。上层（services/usage_service.py）只认这一种结构，因此新增
供应商时不需要改动计费逻辑。

诚实性约束（与前端「成本未知」状态一一对应）：

- declared (known=True) 表示用量来自供应商返回值或调用请求本身，可信；
- 供应商没有回报用量时置 known=False，记账层据此把成本标成「未知」，绝不按 0 计；
- 本地能力（占位图、本地 FFmpeg）置 billable=False，表示不产生外部费用。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

CAPABILITY_LLM = "llm"
CAPABILITY_IMAGE = "image"
CAPABILITY_VIDEO = "video"
CAPABILITY_TTS = "tts"
CAPABILITY_FFMPEG = "ffmpeg"

CAPABILITIES: tuple[str, ...] = (
    CAPABILITY_LLM,
    CAPABILITY_IMAGE,
    CAPABILITY_VIDEO,
    CAPABILITY_TTS,
    CAPABILITY_FFMPEG,
)

CAPABILITY_LABELS: dict[str, str] = {
    CAPABILITY_LLM: "文本模型",
    CAPABILITY_IMAGE: "图像生成",
    CAPABILITY_VIDEO: "视频生成",
    CAPABILITY_TTS: "语音合成",
    CAPABILITY_FFMPEG: "本地编码",
}

# 主计价单位：(展示名, 一个计价单位包含多少个基础数量)
CAPABILITY_PRICING_UNITS: dict[str, tuple[str, int]] = {
    CAPABILITY_LLM: ("每 100 万 tokens", 1_000_000),
    CAPABILITY_IMAGE: ("每张", 1),
    CAPABILITY_VIDEO: ("每秒", 1),
    CAPABILITY_TTS: ("每 1000 字符", 1_000),
    CAPABILITY_FFMPEG: ("每分钟编码", 60),
}

# 基础数量的名字，用于前端与文档说明记账口径。
CAPABILITY_BASE_UNITS: dict[str, str] = {
    CAPABILITY_LLM: "token",
    CAPABILITY_IMAGE: "张",
    CAPABILITY_VIDEO: "秒",
    CAPABILITY_TTS: "字符",
    CAPABILITY_FFMPEG: "秒",
}

# 次计价单位只用于 LLM（输出 token）；其余能力为 None。
CAPABILITY_SECONDARY_UNITS: dict[str, str | None] = {
    CAPABILITY_LLM: "每 100 万输出 tokens",
    CAPABILITY_IMAGE: None,
    CAPABILITY_VIDEO: None,
    CAPABILITY_TTS: None,
    CAPABILITY_FFMPEG: None,
}

# 供应商调用失败且没有回报用量时的稳定错误码（不落供应商原始响应）。
ERROR_CODE_PROVIDER_CALL_FAILED = "provider_call_failed"


def _ceil_seconds(value: float) -> int:
    """秒数按「向上取整」计入整数数量，避免把不足 1 秒的调用记为 0。"""

    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0
    if number <= 0:
        return 0
    return int(number) if float(number).is_integer() else int(number) + 1


@dataclass(frozen=True)
class UsageMetadata:
    """一次调用的统一用量描述。"""

    capability: str
    provider: str = ""
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    images: int = 0
    seconds: float = 0.0
    characters: int = 0
    audio_seconds: float = 0.0
    resolution: str = ""
    # 供应商是否回报了可信用量；False 时记账层把成本标记为「未知」。
    known: bool = True
    # 是否产生外部费用；本地能力（占位图 / 本地编码）为 False。
    billable: bool = True
    # provider=供应商回报；request=由请求推出；local=本地能力；unknown=未知
    source: str = "provider"
    duration_ms: int = 0
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def quantity(self) -> int:
        """主计价数量（整数）。"""

        if self.capability == CAPABILITY_LLM:
            return max(0, int(self.input_tokens or 0))
        if self.capability == CAPABILITY_IMAGE:
            return max(0, int(self.images or 0))
        if self.capability == CAPABILITY_VIDEO:
            return _ceil_seconds(self.seconds)
        if self.capability == CAPABILITY_TTS:
            return max(0, int(self.characters or 0))
        if self.capability == CAPABILITY_FFMPEG:
            return _ceil_seconds(self.seconds)
        return 0

    @property
    def secondary_quantity(self) -> int:
        if self.capability == CAPABILITY_LLM:
            return max(0, int(self.output_tokens or 0))
        return 0

    @property
    def has_usage(self) -> bool:
        return bool(self.quantity or self.secondary_quantity)

    def units(self) -> dict[str, Any]:
        """明细字段：只保留非零项，便于前端直接展示。"""

        raw: dict[str, Any] = {
            "input_tokens": int(self.input_tokens or 0),
            "output_tokens": int(self.output_tokens or 0),
            "images": int(self.images or 0),
            "seconds": round(float(self.seconds or 0), 3),
            "characters": int(self.characters or 0),
            "audio_seconds": round(float(self.audio_seconds or 0), 3),
        }
        detail = {key: value for key, value in raw.items() if value}
        if self.resolution:
            detail["resolution"] = self.resolution
        detail.update({key: value for key, value in (self.extra or {}).items() if value not in (None, "", 0)})
        detail["known"] = bool(self.known)
        return detail

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability": self.capability,
            "provider": self.provider,
            "model": self.model,
            "quantity": self.quantity,
            "secondary_quantity": self.secondary_quantity,
            "resolution": self.resolution,
            "units": self.units(),
            "known": bool(self.known),
            "billable": bool(self.billable),
            "source": self.source,
            "duration_ms": int(self.duration_ms or 0),
        }


def _adapter_endpoint(adapter: object) -> tuple[str, str]:
    endpoint = getattr(adapter, "endpoint", None)
    protocol = str(getattr(endpoint, "protocol", "") or "")
    model = str(getattr(endpoint, "model", "") or "")
    return protocol, model


def adapter_usage_for_request(
    adapter: object,
    capability: str,
    request: object | None = None,
    *,
    model: str = "",
) -> UsageMetadata:
    """安全读取适配器的请求侧用量。

    适配器没实现用量钩子（例如测试替身或第三方自定义适配器）时回退为「未知用量」，
    绝不因此中断生成流程，也绝不猜测数量。
    """

    protocol, endpoint_model = _adapter_endpoint(adapter)
    method = getattr(adapter, "usage_for_request", None)
    if callable(method):
        try:
            result = method(capability, request)
        except TypeError:
            try:
                result = method(capability, request, model=model)
            except Exception:  # noqa: BLE001
                result = None
        except Exception:  # noqa: BLE001
            result = None
        if isinstance(result, UsageMetadata):
            return result
    return unknown_usage(capability, protocol, model or endpoint_model)


def adapter_usage_from_response(
    adapter: object,
    capability: str,
    response: object | None = None,
    *,
    request: object | None = None,
    model: str = "",
    duration_ms: int = 0,
) -> UsageMetadata:
    """安全读取适配器的响应侧用量（供应商回报的 token 等）。"""

    protocol, endpoint_model = _adapter_endpoint(adapter)
    method = getattr(adapter, "usage_from_response", None)
    if callable(method):
        try:
            result = method(capability, response, model=model, duration_ms=duration_ms)
        except TypeError:
            try:
                result = method(capability, response)
            except Exception:  # noqa: BLE001
                result = None
        except Exception:  # noqa: BLE001
            result = None
        if isinstance(result, UsageMetadata):
            return result
    return unknown_usage(capability, protocol, model or endpoint_model, duration_ms=duration_ms)


def unknown_usage(capability: str, provider: str = "", model: str = "", *, duration_ms: int = 0) -> UsageMetadata:
    """供应商没有回报用量时的统一结果：已知「发生过调用」，但不知道花了多少。"""

    return UsageMetadata(
        capability=capability,
        provider=provider,
        model=model,
        known=False,
        billable=False,
        source="unknown",
        duration_ms=duration_ms,
    )


def local_usage(capability: str, provider: str = "local", model: str = "", **kwargs) -> UsageMetadata:
    """本地能力的用量：数量可信、不产生外部费用。"""

    return UsageMetadata(
        capability=capability,
        provider=provider,
        model=model,
        known=True,
        billable=False,
        source="local",
        **kwargs,
    )


def _usage_field(usage: Any, *names: str) -> int:
    for name in names:
        value = usage.get(name) if isinstance(usage, dict) else getattr(usage, name, None)
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            return int(value)
    return 0


def usage_from_chat_response(
    response: Any,
    *,
    provider: str = "",
    model: str = "",
    duration_ms: int = 0,
) -> UsageMetadata:
    """OpenAI 兼容 Chat Completions 响应的用量映射（所有 openai-chat 协议共用）。

    供应商未返回 usage 时返回 known=False：宁可显示「成本未知」，也不估算 token。
    """

    usage = getattr(response, "usage", None)
    if usage is None and isinstance(response, dict):
        usage = response.get("usage")
    if usage is None:
        return unknown_usage(CAPABILITY_LLM, provider, model, duration_ms=duration_ms)
    input_tokens = _usage_field(usage, "prompt_tokens", "input_tokens")
    output_tokens = _usage_field(usage, "completion_tokens", "output_tokens")
    if not input_tokens and not output_tokens:
        return unknown_usage(CAPABILITY_LLM, provider, model, duration_ms=duration_ms)
    return UsageMetadata(
        capability=CAPABILITY_LLM,
        provider=provider,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        known=True,
        billable=True,
        source="provider",
        duration_ms=duration_ms,
    )


__all__ = [
    "CAPABILITIES",
    "adapter_usage_for_request",
    "adapter_usage_from_response",
    "CAPABILITY_BASE_UNITS",
    "CAPABILITY_FFMPEG",
    "CAPABILITY_IMAGE",
    "CAPABILITY_LABELS",
    "CAPABILITY_LLM",
    "CAPABILITY_PRICING_UNITS",
    "CAPABILITY_SECONDARY_UNITS",
    "CAPABILITY_TTS",
    "CAPABILITY_VIDEO",
    "ERROR_CODE_PROVIDER_CALL_FAILED",
    "UsageMetadata",
    "local_usage",
    "unknown_usage",
    "usage_from_chat_response",
]

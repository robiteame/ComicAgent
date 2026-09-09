"""协议适配器基类与各能力的能力声明 dataclass。"""

from __future__ import annotations

from dataclasses import dataclass

from services.providers.endpoint import EndpointConfig


@dataclass(frozen=True)
class LLMCapabilities:
    json_mode: str = "auto"  # auto=试探 response_format 并在报错时自动降级；supported/unsupported
    vision: bool = True  # 是否支持图片输入（call_with_image）


@dataclass(frozen=True)
class ImageCapabilities:
    reference_images: bool = False  # 是否支持参考图输入（seedream 支持多图）


@dataclass(frozen=True)
class VideoCapabilities:
    reference_image: bool = False  # 是否需要/支持首帧参考图（Seedance 必须）
    native_audio: bool = False  # 是否原生生成音频（含对白语音）
    dialogue_in_prompt: bool = False  # 对白是否通过 prompt 文本驱动（Veo 3 风格）
    voice_consistent: bool = False  # 能否指定/锁定音色


class BaseAdapter:
    """协议适配器基类：持有一个端点配置，由子类实现具体协议调用。"""

    capabilities: object = None

    def __init__(self, endpoint: EndpointConfig):
        self.endpoint = endpoint

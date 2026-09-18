"""阿里云百炼（DashScope）语音合成适配器。

调用 ``{base_url}/services/audio/tts``（CosyVoice 系列模型，Bearer 鉴权），
非流式返回 JSON，音频在 ``output.audio``（base64）。单次请求文本上限 2000
字符，超长时按句切分分段合成后本地拼接：wav 用标准库按参数严格拼接，其余
格式按字节顺序拼接。角色音色档案存量是 Mimo 归一化音色名，这里映射到
CosyVoice 音色 ID（``long*_v2``）；已是百炼音色 ID 时直接透传。
"""

from __future__ import annotations

import base64
import wave
from io import BytesIO

import httpx

from config import settings
from services.providers.base import BaseAdapter, TTSRequest
from services.providers.usage import CAPABILITY_TTS, UsageMetadata

_DEFAULT_BASE = "https://dashscope.aliyuncs.com/api/v1"
_DEFAULT_MODEL = "cosyvoice-v2"
_DEFAULT_VOICE = "longwan_v2"  # 龙婉 · 温柔女声

# CosyVoice 单次请求文本上限 2000 字符；按句切分时留余量。
_SEGMENT_CHAR_LIMIT = 1800
_SENTENCE_BREAKS = "。！？；，…,.!?;\n"

# 百炼 CosyVoice 音色 ID（cosyvoice-v2 用 *_v2 后缀，v1 去掉后缀）。
COSYVOICE_VOICES = {
    "longwan_v2",  # 龙婉 · 温柔女声
    "longcheng_v2",  # 龙橙 · 沉稳男声
    "longhua_v2",  # 龙华 · 浑厚男声
    "longxiaochun_v2",  # 龙小淳 · 少年音
    "longxiaoxia_v2",  # 龙小夏 · 标准女声
    "longxiaochen_v2",  # 龙小晨 · 亲切女声
    "longxiaobai_v2",  # 龙小白 · 甜美女声
    "longxiaobei_v2",  # 龙小北 · 女声
    "longxiaoni_v2",  # 龙小妮 · 女声
    "longxiaoxuan_v2",  # 龙小萱 · 童声
    "longlaotie_v2",  # 龙老铁 · 东北男声
    "longshu_v2",  # 龙书 · 男声
    "longshuo_v2",  # 龙朔 · 男声
    "longjing_v2",  # 龙晶 · 女声
    "longmiao_v2",  # 龙妙 · 女声
    "longyue_v2",  # 龙悦 · 悦耳女声
    "longyuan_v2",  # 龙渊 · 浑厚男声
    "longfei_v2",  # 龙飞 · 男声
    "longjielidou_v2",  # 龙杰力豆 · 卡通男声
    "longtong_v2",  # 龙彤 · 活泼女声
    "longxiang_v2",  # 龙湘 · 女声
    "loongstella_v2",  # Loong Stella · 知性女声
    "loongbella_v2",  # Loong Bella · 女声
}

# Mimo 音色名（角色档案存量）与通用风格标签 → 百炼 CosyVoice 音色。
DASHSCOPE_VOICE_ALIASES = {
    "mimo_default": "longwan_v2",
    "冰糖": "longwan_v2",  # 温柔女声
    "Mia": "longwan_v2",
    "茉莉": "longyue_v2",  # 悦耳女声
    "Chloe": "longtong_v2",  # 活泼女声
    "苏打": "longxiaoxuan_v2",  # 童声
    "Milo": "longshuo_v2",  # 男声
    "Dean": "longcheng_v2",  # 沉稳男声
    "白桦": "longhua_v2",  # 浑厚男声
    "少女": "longwan_v2",
    "女声": "longxiaoxia_v2",
    "甜美": "longwan_v2",
    "少年": "longxiaochun_v2",
    "男声": "longshuo_v2",
    "青年": "longshuo_v2",
    "御姐": "longyue_v2",
    "成熟女声": "longyue_v2",
    "姐姐": "longyue_v2",
    "大叔": "longcheng_v2",
    "成熟男声": "longcheng_v2",
    "叔叔": "longcheng_v2",
    "儿童": "longxiaoxuan_v2",
    "孩子": "longxiaoxuan_v2",
    "老人": "longhua_v2",
    "老年": "longhua_v2",
}


def normalize_dashscope_voice(voice_id: str = "", default_voice: str = "") -> str:
    """把 Mimo 音色名 / 通用标签 / 百炼音色 ID 归一化为 CosyVoice 音色。"""

    voice = (voice_id or "").strip()
    if voice in COSYVOICE_VOICES or voice.lower().startswith(("long", "loong")):
        return voice
    if voice in DASHSCOPE_VOICE_ALIASES:
        return DASHSCOPE_VOICE_ALIASES[voice]
    default = (default_voice or "").strip()
    if default in COSYVOICE_VOICES or default.lower().startswith(("long", "loong")):
        return default
    if default in DASHSCOPE_VOICE_ALIASES:
        return DASHSCOPE_VOICE_ALIASES[default]
    return _DEFAULT_VOICE


class DashscopeTTSAdapter(BaseAdapter):
    def usage_for_request(
        self,
        capability: str,
        request: TTSRequest | None = None,
        *,
        model: str = "",
    ) -> UsageMetadata:
        """百炼 CosyVoice 按字符计费；音色与音频格式记进明细便于核对。"""

        text = str(getattr(request, "text", "") or "")
        return UsageMetadata(
            capability=CAPABILITY_TTS,
            provider=self.endpoint.protocol,
            model=model or self.endpoint.model,
            characters=len(text.strip()),
            known=True,
            billable=True,
            source="request",
            extra={
                "voice": normalize_dashscope_voice(
                    str(getattr(request, "voice_id", "") or ""), str(self.endpoint.param("voice") or "")
                ),
                "format": str(self.endpoint.param("format") or ""),
            },
        )

    async def synthesize(self, request: TTSRequest) -> bytes:
        if not self.endpoint.api_key:
            raise RuntimeError("未配置语音端点 API Key，无法调用百炼语音合成")
        text = str(request.text or "").strip()
        if not text:
            raise RuntimeError("配音文本为空，无法调用 TTS")
        if len(text) > settings.MAX_SCRIPT_TEXT_CHARS:
            raise RuntimeError("配音文本超过长度限制")

        voice = normalize_dashscope_voice(request.voice_id, str(self.endpoint.param("voice") or ""))
        codec = str(self.endpoint.param("format") or "wav").strip().lower().lstrip(".") or "wav"
        chunks: list[bytes] = []
        for segment in self._split_text(text):
            chunks.append(await self._synthesize_segment(segment, voice, codec))
        audio = chunks[0] if len(chunks) == 1 else self._concat_audio(chunks, codec)
        if len(audio) > settings.MAX_TTS_AUDIO_BYTES:
            raise RuntimeError("音频数据超过大小限制")
        return audio

    # --- 协议细节 ---

    async def _synthesize_segment(self, text: str, voice: str, codec: str) -> bytes:
        payload = {
            "model": self.endpoint.model or _DEFAULT_MODEL,
            "input": {"text": text},
            "parameters": {"voice": voice, "format": codec},
        }
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(
                f"{self._api_base()}/services/audio/tts",
                headers={
                    "Authorization": f"Bearer {self.endpoint.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
        if response.status_code >= 400:
            raise RuntimeError(f"百炼语音合成调用失败: {response.status_code} {response.text[:600]}")

        data = response.json() or {}
        error_code = data.get("code")
        if error_code:
            raise RuntimeError(f"百炼语音合成调用失败: {error_code} {data.get('message')}")
        b64_data = str((data.get("output") or {}).get("audio") or "")
        if not b64_data:
            raise RuntimeError(f"百炼语音合成返回缺少 audio: {data}")

        limit = int(settings.MAX_TTS_AUDIO_BYTES)
        if len(b64_data) > int(limit * 4 / 3) + 16:
            raise RuntimeError("音频数据超过大小限制")
        try:
            decoded = base64.b64decode(b64_data, validate=True)
        except Exception as exc:
            raise RuntimeError("音频数据编码无效") from exc
        if len(decoded) > limit:
            raise RuntimeError("音频数据超过大小限制")
        return decoded

    def _split_text(self, text: str) -> list[str]:
        """按句切分超长文本：优先在标点断句，避免把一句话切成两段语气断裂。"""

        segments: list[str] = []
        remaining = text
        while len(remaining) > _SEGMENT_CHAR_LIMIT:
            cut = _SEGMENT_CHAR_LIMIT
            for index in range(_SEGMENT_CHAR_LIMIT, max(_SEGMENT_CHAR_LIMIT // 2, 1), -1):
                if remaining[index - 1] in _SENTENCE_BREAKS:
                    cut = index
                    break
            segments.append(remaining[:cut])
            remaining = remaining[cut:]
        if remaining.strip():
            segments.append(remaining)
        return segments or [text]

    def _concat_audio(self, chunks: list[bytes], codec: str) -> bytes:
        if codec != "wav":
            return b"".join(chunks)
        output = BytesIO()
        with wave.open(output, "wb") as writer:
            for index, chunk in enumerate(chunks):
                with wave.open(BytesIO(chunk)) as reader:
                    if index == 0:
                        writer.setnchannels(reader.getnchannels())
                        writer.setsampwidth(reader.getsampwidth())
                        writer.setframerate(reader.getframerate())
                    writer.writeframes(reader.readframes(reader.getnframes()))
        return output.getvalue()

    def _api_base(self) -> str:
        base = (self.endpoint.base_url or _DEFAULT_BASE).rstrip("/")
        if not base.endswith("/api/v1"):
            base = f"{base}/api/v1"
        return base


__all__ = [
    "COSYVOICE_VOICES",
    "DASHSCOPE_VOICE_ALIASES",
    "DashscopeTTSAdapter",
    "normalize_dashscope_voice",
]

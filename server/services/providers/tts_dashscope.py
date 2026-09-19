"""阿里云百炼（DashScope）语音合成适配器。

调用 ``{base_url}/services/audio/tts/SpeechSynthesizer``（CosyVoice /
Qwen-Audio-TTS 系列模型，Bearer 鉴权）。按官方 2026-08 起的 HTTP 协议：
voice/format 等参数直接放在 ``input`` 内；非流式响应不再返回 base64，
``output.audio.url`` 指向合成音频（24 小时有效，域名为 *.aliyuncs.com），
需校验域名后自行下载。非流式合成必须整段等待，实测约 0.09 秒/字符，超长
文本按句切到 600 字符一段依次合成，再本地拼接：wav 用标准库重写头部并拼接
（返回音频的头尺寸是占位值），其余格式按字节顺序拼接。角色音色
档案存量是 Mimo 归一化音色名，这里映射到实测可用的 CosyVoice 音色；v2 模型
只放行验证过的音色 ID（其余 long*/loong* 会触发引擎 418），复刻音色透传。
"""

from __future__ import annotations

import base64
import wave
from io import BytesIO
from urllib.parse import urlparse

import httpx

from config import settings
from services.providers.base import BaseAdapter, TTSRequest
from services.providers.usage import CAPABILITY_TTS, UsageMetadata

_DEFAULT_BASE = "https://dashscope.aliyuncs.com/api/v1"
_DEFAULT_MODEL = "cosyvoice-v2"
_DEFAULT_VOICE = "longwan_v2"  # 龙婉 · 温柔女声

# 官方单次请求文本上限 2000 字符；实测非流式合成耗时约 0.09s/字符且必须整段
# 等待，1800 字符一段会超过网关超时，按句切到 600 字符一段（约 1 分钟）。
_SEGMENT_CHAR_LIMIT = 600
_SENTENCE_BREAKS = "。！？；，…,.!?;\n"

# 百炼 cosyvoice-v2 实测可用音色（2026-09 逐一验证；longwan、longxiaochun、
# longtong、longxiang 等无后缀名及 longxiaoxuan_v2 等并非 v2 音色，传入会触发
# 引擎 418「音色与模型版本不匹配」）。
COSYVOICE_VOICES = {
    "longwan_v2",  # 龙婉 · 温柔女声
    "longcheng_v2",  # 龙橙 · 沉稳男声
    "longhua_v2",  # 龙华 · 浑厚男声
    "longxiaochun_v2",  # 龙小淳 · 少年音
    "longxiaoxia_v2",  # 龙小夏 · 标准女声
    "longxiaobai_v2",  # 龙小白 · 甜美女声
    "longlaotie_v2",  # 龙老铁 · 东北男声
    "longshu_v2",  # 龙书 · 男声
    "longshuo_v2",  # 龙朔 · 男声
    "longjing_v2",  # 龙晶 · 女声
    "longmiao_v2",  # 龙妙 · 女声
    "longyue_v2",  # 龙悦 · 悦耳女声
    "longyuan_v2",  # 龙渊 · 浑厚男声
    "longfei_v2",  # 龙飞 · 男声
    "longjielidou_v2",  # 龙杰力豆 · 卡通男声
    "longhuhu",  # 龙呼呼 · 童声（v2 少数无后缀可用音色）
    "loongstella_v2",  # Loong Stella · 知性女声
    "loongbella_v2",  # Loong Bella · 女声
}

# Mimo 音色名（角色档案存量）与通用风格标签 → 百炼 CosyVoice 音色，
# 目标必须都在上面验证过的集合内。
DASHSCOPE_VOICE_ALIASES = {
    "mimo_default": "longwan_v2",
    "冰糖": "longwan_v2",  # 温柔女声
    "Mia": "longwan_v2",
    "茉莉": "longyue_v2",  # 悦耳女声
    "Chloe": "longxiaobai_v2",  # 甜美女声（longtong_v2 非 v2 音色）
    "苏打": "longhuhu",  # 童声（longxiaoxuan_v2 非 v2 音色）
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
    "儿童": "longhuhu",  # 童声
    "孩子": "longhuhu",  # 童声
    "童声": "longhuhu",  # 童声
    "老人": "longhua_v2",
    "老年": "longhua_v2",
}


def normalize_dashscope_voice(voice_id: str = "", default_voice: str = "", model: str = "") -> str:
    """把 Mimo 音色名 / 通用标签 / 百炼音色 ID 归一化为目标模型可用的音色。

    cosyvoice-v2 只认验证过的 ``COSYVOICE_VOICES``，其余 long*/loong* ID（v1
    无后缀名、_v3 名、拼错的 _v2 名）传入都会触发引擎 418，因此统一回退到
    默认音色；其他模型版本（v3/v3.5 等）没有本地可验证的音色表，long*/loong*
    ID 原样透传。声音复刻音色（cosyvoice- 前缀）自带版本信息，直接透传。
    """

    def _resolve(candidate: str) -> str | None:
        voice = (candidate or "").strip()
        if not voice:
            return None
        if voice in COSYVOICE_VOICES:
            return voice
        if voice in DASHSCOPE_VOICE_ALIASES:
            return DASHSCOPE_VOICE_ALIASES[voice]
        v2_strict = not model or model.strip().lower().startswith("cosyvoice-v2")
        if voice.lower().startswith("cosyvoice-"):  # 复刻音色，如 cosyvoice-v2-clone…
            return voice
        if not v2_strict and voice.lower().startswith(("long", "loong")):
            return voice
        return None

    return _resolve(voice_id) or _resolve(default_voice) or _DEFAULT_VOICE


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
                    str(getattr(request, "voice_id", "") or ""),
                    str(self.endpoint.param("voice") or ""),
                    model or self.endpoint.model,
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

        voice = normalize_dashscope_voice(
            request.voice_id,
            str(self.endpoint.param("voice") or ""),
            self.endpoint.model or _DEFAULT_MODEL,
        )
        codec = str(self.endpoint.param("format") or "wav").strip().lower().lstrip(".") or "wav"
        chunks: list[bytes] = []
        for segment in self._split_text(text):
            chunks.append(await self._synthesize_segment(segment, voice, codec))
        # 百炼返回的 wav 头部尺寸是占位值，统一经标准库重写；多段时顺带拼接。
        audio = self._concat_audio(chunks, codec) if codec == "wav" else b"".join(chunks)
        if len(audio) > settings.MAX_TTS_AUDIO_BYTES:
            raise RuntimeError("音频数据超过大小限制")
        return audio

    # --- 协议细节 ---

    async def _synthesize_segment(self, text: str, voice: str, codec: str) -> bytes:
        payload = {
            "model": self.endpoint.model or _DEFAULT_MODEL,
            "input": {"text": text, "voice": voice, "format": codec},
        }
        async with httpx.AsyncClient(timeout=180) as client:
            response = await client.post(
                f"{self._api_base()}/services/audio/tts/SpeechSynthesizer",
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
            message = f"百炼语音合成调用失败: {error_code} {data.get('message')}"
            if "418" in str(data.get("message")):
                message += "（官方错误码 418 = 音色与模型版本不匹配，请检查 voice 是否为目标模型支持的音色）"
            raise RuntimeError(message)
        audio = (data.get("output") or {}).get("audio") or {}
        if not isinstance(audio, dict):
            audio = {}

        # 非流式响应给 url；内联 base64（data）只在流式场景出现，兜底支持。
        b64_data = str(audio.get("data") or "").strip()
        if b64_data:
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

        url = str(audio.get("url") or "").strip()
        if not url:
            raise RuntimeError(f"百炼语音合成返回缺少 audio: {data}")
        return await self._download_audio(url)

    async def _download_audio(self, url: str) -> bytes:
        """下载合成音频。官方要求先确认 URL 是阿里云域名再请求。"""

        host = (urlparse(url).hostname or "").lower()
        if not (host == "aliyuncs.com" or host.endswith(".aliyuncs.com")):
            raise RuntimeError("百炼语音合成返回的音频地址不是阿里云域名，已拒绝下载")
        async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
            response = await client.get(url)
        if response.status_code >= 400:
            raise RuntimeError(f"百炼语音合成音频下载失败: {response.status_code}")
        audio = response.content
        if len(audio) > int(settings.MAX_TTS_AUDIO_BYTES):
            raise RuntimeError("音频数据超过大小限制")
        return audio

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
                    # 读实际可读数据而非头部的 nframes（百炼 wav 头尺寸是占位值）。
                    writer.writeframes(reader.readframes(reader.getnframes()))
        return output.getvalue()

    def _api_base(self) -> str:
        base = (self.endpoint.base_url or _DEFAULT_BASE).rstrip("/")
        # OpenAI 兼容模式地址（compatible-mode/v1）和裸域名统一归一到 /api/v1 根。
        lowered = base.lower()
        for suffix in ("/compatible-mode/v1", "/compatible-mode"):
            if lowered.endswith(suffix):
                base = base[: -len(suffix)]
                lowered = base.lower()
                break
        if not base.lower().endswith("/api/v1"):
            base = f"{base}/api/v1"
        return base


__all__ = [
    "COSYVOICE_VOICES",
    "DASHSCOPE_VOICE_ALIASES",
    "DashscopeTTSAdapter",
    "normalize_dashscope_voice",
]

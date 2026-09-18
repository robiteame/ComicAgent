"""Mimo TTS 协议适配器（原 TTSService 的 Mimo 调用逻辑迁入）。

含中文音色别名映射；鉴权同时携带 api-key 请求头与 Bearer（与既有行为一致）。
"""

from __future__ import annotations

import base64

import httpx

from config import settings
from services.providers.base import BaseAdapter, TTSRequest
from services.providers.usage import CAPABILITY_TTS, UsageMetadata

MIMO_TTS_VOICES = {"mimo_default", "冰糖", "茉莉", "苏打", "白桦", "Mia", "Chloe", "Milo", "Dean"}

VOICE_ALIASES = {
    "少女": "冰糖",
    "女声": "冰糖",
    "甜美": "冰糖",
    "少年": "Milo",
    "男声": "Milo",
    "青年": "Milo",
    "御姐": "茉莉",
    "成熟女声": "茉莉",
    "姐姐": "茉莉",
    "大叔": "Dean",
    "成熟男声": "Dean",
    "叔叔": "Dean",
    "儿童": "苏打",
    "孩子": "苏打",
    "老人": "白桦",
    "老年": "白桦",
    "zh-CN-XiaoxiaoNeural": "冰糖",
    "zh-CN-XiaoyiNeural": "茉莉",
    "zh-CN-YunjianNeural": "Milo",
    "zh-CN-YunxiNeural": "Milo",
    "zh-CN-YunyangNeural": "Dean",
}


def normalize_mimo_voice(voice_id: str = "", default_voice: str = "") -> str:
    """Map generic or legacy voice labels to voices accepted by Mimo TTS."""
    voice = (voice_id or "").strip()
    if voice in MIMO_TTS_VOICES:
        return voice
    if voice in VOICE_ALIASES:
        return VOICE_ALIASES[voice]

    default = (default_voice or "mimo_default").strip()
    if default in MIMO_TTS_VOICES:
        return default
    return "mimo_default"


class MimoTTSAdapter(BaseAdapter):
    def usage_for_request(
        self,
        capability: str,
        request: TTSRequest | None = None,
        *,
        model: str = "",
    ) -> UsageMetadata:
        """Mimo TTS 按字符计费；音色与音频格式记进明细便于核对。"""

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
                "voice": str(getattr(request, "voice_id", "") or self.endpoint.param("voice") or ""),
                "format": str(self.endpoint.param("format") or ""),
            },
        )

    async def synthesize(self, request: TTSRequest) -> bytes:
        endpoint = self.endpoint
        if not endpoint.api_key:
            raise RuntimeError("未配置语音端点 API Key，无法调用 TTS")
        text = str(request.text or "").strip()
        if not text:
            raise RuntimeError("配音文本为空，无法调用 TTS")
        if len(text) > settings.MAX_SCRIPT_TEXT_CHARS:
            raise RuntimeError("配音文本超过长度限制")

        audio_format = str(endpoint.param("format") or "wav")
        payload = {
            "model": endpoint.model,
            "messages": [
                {"role": "user", "content": "请把下一条 assistant 消息合成为自然中文配音。"},
                {"role": "assistant", "content": f"{self._emotion_hint(request.emotion)}{text}"},
            ],
            "modalities": ["audio", "text"],
            "audio": {
                "voice": normalize_mimo_voice(request.voice_id, str(endpoint.param("voice") or "")),
                "format": audio_format,
            },
        }
        headers = {
            "api-key": endpoint.api_key,
            "Authorization": f"Bearer {endpoint.api_key}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(
                f"{endpoint.base_url.rstrip('/')}/chat/completions",
                headers=headers,
                json=payload,
            )
        if response.status_code >= 400:
            raise RuntimeError(f"Mimo TTS 调用失败: {response.status_code} {response.text[:600]}")

        return self._extract_audio(response.json())

    def _extract_audio(self, data: dict) -> bytes:
        try:
            message = data["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(f"Mimo TTS 返回缺少 choices/message: {data}") from exc

        audio = message.get("audio") or {}
        b64_data = audio.get("data") or audio.get("b64_json") or audio.get("base64")
        if not b64_data:
            raise RuntimeError(f"Mimo TTS 返回缺少 audio.data: {data}")
        if "," in b64_data and b64_data.startswith("data:"):
            b64_data = b64_data.split(",", 1)[1]
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

    @staticmethod
    def _emotion_hint(emotion: str) -> str:
        return {
            "happy": "用轻快、温暖的语气：",
            "shy": "用稍微害羞、柔和的语气：",
            "sad": "用低落、克制的语气：",
            "angry": "用坚定、略带急切的语气：",
            "surprised": "用惊讶、明亮的语气：",
        }.get(emotion, "")

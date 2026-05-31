import base64

import httpx

from config import settings


class TTSService:
    """Mimo built-in TTS service."""

    def __init__(self):
        self.output_dir = settings.OUTPUT_DIR / "projects"

    async def generate_dialogue(
        self,
        text: str,
        voice_id: str = "",
        emotion: str = "neutral",
        project_id: str = "",
        shot_id: str = "",
    ) -> str:
        audio_dir = self.output_dir / project_id / "audio"
        audio_dir.mkdir(parents=True, exist_ok=True)
        suffix = (settings.MIMO_TTS_FORMAT or "wav").lstrip(".")
        audio_path = audio_dir / f"{shot_id}.{suffix}"
        return await self._generate_mimo_tts(text, voice_id, emotion, audio_path)

    async def _generate_mimo_tts(self, text: str, voice_id: str, emotion: str, audio_path) -> str:
        if not settings.MIMO_API_KEY:
            raise RuntimeError("未配置 MIMO_API_KEY，无法调用 Mimo 内置 TTS")
        if not text.strip():
            raise RuntimeError("配音文本为空，无法调用 Mimo 内置 TTS")

        payload = {
            "model": settings.MIMO_TTS_MODEL,
            "messages": [
                {"role": "user", "content": "请把下一条 assistant 消息合成为自然中文配音。"},
                {"role": "assistant", "content": f"{self._emotion_hint(emotion)}{text.strip()}"},
            ],
            "modalities": ["audio", "text"],
            "audio": {
                "voice": voice_id or settings.MIMO_TTS_VOICE,
                "format": settings.MIMO_TTS_FORMAT or "wav",
            },
        }
        headers = {
            "api-key": settings.MIMO_API_KEY,
            "Authorization": f"Bearer {settings.MIMO_API_KEY}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(
                f"{settings.MIMO_BASE_URL.rstrip('/')}/chat/completions",
                headers=headers,
                json=payload,
            )
        if response.status_code >= 400:
            raise RuntimeError(f"Mimo TTS 调用失败: {response.status_code} {response.text[:600]}")

        audio_data = self._extract_mimo_audio(response.json())
        audio_path.write_bytes(audio_data)
        if not audio_path.exists() or audio_path.stat().st_size <= 1024:
            raise RuntimeError("Mimo TTS 返回音频为空或过小")
        return str(audio_path)

    def _extract_mimo_audio(self, data: dict) -> bytes:
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
        return base64.b64decode(b64_data)

    def _emotion_hint(self, emotion: str) -> str:
        return {
            "happy": "用轻快、温暖的语气：",
            "shy": "用稍微害羞、柔和的语气：",
            "sad": "用低落、克制的语气：",
            "angry": "用坚定、略带急切的语气：",
            "surprised": "用惊讶、明亮的语气：",
        }.get(emotion, "")

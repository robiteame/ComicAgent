import base64

import httpx

from config import settings
from services.security import atomic_write_bytes, safe_path, validate_identifier
from services.storage_service import StorageQuotaExceeded, StorageService


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


def normalize_mimo_voice(voice_id: str = "") -> str:
    """Map generic or legacy voice labels to voices accepted by Mimo TTS."""
    voice = (voice_id or "").strip()
    if voice in MIMO_TTS_VOICES:
        return voice
    if voice in VOICE_ALIASES:
        return VOICE_ALIASES[voice]

    default_voice = (settings.MIMO_TTS_VOICE or "mimo_default").strip()
    if default_voice in MIMO_TTS_VOICES:
        return default_voice
    return "mimo_default"


class TTSService:
    """Mimo built-in TTS service."""

    def __init__(self):
        self.output_dir = settings.OUTPUT_DIR / "projects"
        self.storage = StorageService()

    async def generate_dialogue(
        self,
        text: str,
        voice_id: str = "",
        emotion: str = "neutral",
        project_id: str = "",
        shot_id: str = "",
    ) -> str:
        try:
            safe_project_id = validate_identifier(project_id, "项目 ID")
            safe_shot_id = validate_identifier(shot_id, "镜头 ID")
        except ValueError as exc:
            raise RuntimeError(str(exc)) from exc
        audio_dir = safe_path(self.output_dir, safe_project_id, "audio", create_parent=True)
        suffix = (settings.MIMO_TTS_FORMAT or "wav").lstrip(".")
        audio_path = audio_dir / f"{safe_shot_id}.{suffix}"
        return await self._generate_mimo_tts(text, voice_id, emotion, audio_path)

    async def _generate_mimo_tts(self, text: str, voice_id: str, emotion: str, audio_path) -> str:
        if not settings.MIMO_API_KEY:
            raise RuntimeError("未配置 MIMO_API_KEY，无法调用 Mimo 内置 TTS")
        if not text.strip():
            raise RuntimeError("配音文本为空，无法调用 Mimo 内置 TTS")
        if len(text) > settings.MAX_SCRIPT_TEXT_CHARS:
            raise RuntimeError("配音文本超过长度限制")

        payload = {
            "model": settings.MIMO_TTS_MODEL,
            "messages": [
                {"role": "user", "content": "请把下一条 assistant 消息合成为自然中文配音。"},
                {"role": "assistant", "content": f"{self._emotion_hint(emotion)}{text.strip()}"},
            ],
            "modalities": ["audio", "text"],
            "audio": {
                "voice": normalize_mimo_voice(voice_id),
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
        try:
            self.storage.ensure_project_capacity(project_id=audio_path.parents[1].name, incoming_bytes=len(audio_data), replacing=audio_path)
        except StorageQuotaExceeded as exc:
            raise RuntimeError("项目媒体存储空间不足") from exc
        atomic_write_bytes(audio_path, audio_data, minimum_size=1024)
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

    def _emotion_hint(self, emotion: str) -> str:
        return {
            "happy": "用轻快、温暖的语气：",
            "shy": "用稍微害羞、柔和的语气：",
            "sad": "用低落、克制的语气：",
            "angry": "用坚定、略带急切的语气：",
            "surprised": "用惊讶、明亮的语气：",
        }.get(emotion, "")

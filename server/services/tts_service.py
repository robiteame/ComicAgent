"""TTS 配音服务：端点读取 + 路径/配额管理的薄封装。

协议调用委托给 ``providers.tts_mimo.MimoTTSAdapter``（默认协议 mimo-tts），
端点配置来自 ``get_endpoint("voice")``，保存配置后新任务即生效。
"""

from config import settings
from services.providers.base import TTSRequest
from services.providers.endpoint import get_endpoint
from services.providers.registry import get_adapter
from services.providers.tts_mimo import VOICE_ALIASES, MIMO_TTS_VOICES
from services.providers.tts_mimo import normalize_mimo_voice as _normalize_mimo_voice
from services.security import atomic_write_bytes, safe_path, validate_identifier
from services.storage_service import StorageQuotaExceeded, StorageService

__all__ = ["TTSService", "normalize_mimo_voice", "MIMO_TTS_VOICES", "VOICE_ALIASES"]


def normalize_mimo_voice(voice_id: str = "") -> str:
    """音色别名归一化；未知音色回落到语音端点配置的默认音色。"""
    return _normalize_mimo_voice(voice_id, str(get_endpoint("voice").param("voice") or ""))


class TTSService:
    """语音合成服务（默认 Mimo 内置 TTS，经 mimo-tts 协议适配器调用）。"""

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

        endpoint = get_endpoint("voice")
        if not text.strip():
            raise RuntimeError("配音文本为空，无法调用 TTS")
        if len(text) > settings.MAX_SCRIPT_TEXT_CHARS:
            raise RuntimeError("配音文本超过长度限制")
        if not endpoint.api_key:
            raise RuntimeError("未配置语音端点 API Key，无法调用 TTS")

        adapter = get_adapter("voice", endpoint.protocol)(endpoint)
        audio_data = await adapter.synthesize(TTSRequest(text=text, voice_id=voice_id, emotion=emotion))

        audio_dir = safe_path(self.output_dir, safe_project_id, "audio", create_parent=True)
        suffix = str(endpoint.param("format") or "wav").lstrip(".")
        audio_path = audio_dir / f"{safe_shot_id}.{suffix}"
        try:
            self.storage.ensure_project_capacity(
                project_id=safe_project_id, incoming_bytes=len(audio_data), replacing=audio_path
            )
        except StorageQuotaExceeded as exc:
            raise RuntimeError("项目媒体存储空间不足") from exc
        atomic_write_bytes(audio_path, audio_data, minimum_size=1024)
        if not audio_path.exists() or audio_path.stat().st_size <= 1024:
            raise RuntimeError("TTS 返回音频为空或过小")
        return str(audio_path)

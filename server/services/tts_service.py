import uuid
import edge_tts
from pathlib import Path
from config import settings


# 音色映射：角色类型 -> Edge-TTS 音色
VOICE_MAP = {
    "少女": "zh-CN-XiaoyiNeural",
    "少年": "zh-CN-YunxiNeural",
    "御姐": "zh-CN-XiaoxiaoNeural",
    "大叔": "zh-CN-YunjianNeural",
    "儿童": "zh-CN-XiaoxiaoNeural",
    "老人": "zh-CN-YunjianNeural",
}

# 情绪 -> 语速/语调调整
EMOTION_PARAMS = {
    "neutral": {"rate": "+0%", "pitch": "+0Hz"},
    "happy": {"rate": "+5%", "pitch": "+5Hz"},
    "shy": {"rate": "-5%", "pitch": "+2Hz"},
    "sad": {"rate": "-10%", "pitch": "-5Hz"},
    "angry": {"rate": "+10%", "pitch": "+10Hz"},
    "surprised": {"rate": "+5%", "pitch": "+8Hz"},
}


class TTSService:
    """TTS 配音服务（Edge-TTS）"""

    def __init__(self):
        self.output_dir = settings.OUTPUT_DIR / "projects"
        self.default_voice = settings.TTS_DEFAULT_VOICE

    async def generate_dialogue(
        self,
        text: str,
        voice_id: str = "",
        emotion: str = "neutral",
        project_id: str = "",
        shot_id: str = "",
    ) -> str:
        """为台词生成配音"""

        # 确定音色
        voice = self._resolve_voice(voice_id)

        # 获取情绪参数
        params = EMOTION_PARAMS.get(emotion, EMOTION_PARAMS["neutral"])

        # 输出路径
        audio_dir = self.output_dir / project_id / "audio"
        audio_dir.mkdir(parents=True, exist_ok=True)
        audio_path = audio_dir / f"{shot_id}.mp3"

        # 生成配音
        communicate = edge_tts.Communicate(
            text=text,
            voice=voice,
            rate=params["rate"],
            pitch=params["pitch"],
        )
        await communicate.save(str(audio_path))

        return str(audio_path)

    def _resolve_voice(self, voice_id: str) -> str:
        """解析音色标识为 Edge-TTS 音色名"""
        if not voice_id:
            return self.default_voice
        if voice_id in VOICE_MAP:
            return VOICE_MAP[voice_id]
        # 如果已经是完整的 Edge-TTS 音色名
        if voice_id.startswith("zh-CN-"):
            return voice_id
        return self.default_voice

    async def list_voices(self) -> list[dict]:
        """列出所有可用的中文音色"""
        voices = await edge_tts.list_voices()
        return [v for v in voices if v["Locale"].startswith("zh-CN")]

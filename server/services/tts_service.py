import wave

import edge_tts

from config import settings


VOICE_MAP = {
    "少女": "zh-CN-XiaoyiNeural",
    "少年": "zh-CN-YunxiNeural",
    "御姐": "zh-CN-XiaoxiaoNeural",
    "大叔": "zh-CN-YunjianNeural",
    "儿童": "zh-CN-XiaoxiaoNeural",
    "老人": "zh-CN-YunjianNeural",
}

EMOTION_PARAMS = {
    "neutral": {"rate": "+0%", "pitch": "+0Hz"},
    "happy": {"rate": "+5%", "pitch": "+5Hz"},
    "shy": {"rate": "-5%", "pitch": "+2Hz"},
    "sad": {"rate": "-10%", "pitch": "-5Hz"},
    "angry": {"rate": "+10%", "pitch": "+10Hz"},
    "surprised": {"rate": "+5%", "pitch": "+8Hz"},
}


class TTSService:
    """Edge-TTS service with a silent WAV fallback."""

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
        audio_dir = self.output_dir / project_id / "audio"
        audio_dir.mkdir(parents=True, exist_ok=True)
        mp3_path = audio_dir / f"{shot_id}.mp3"

        try:
            params = EMOTION_PARAMS.get(emotion, EMOTION_PARAMS["neutral"])
            communicate = edge_tts.Communicate(
                text=text,
                voice=self._resolve_voice(voice_id),
                rate=params["rate"],
                pitch=params["pitch"],
            )
            await communicate.save(str(mp3_path))
            return str(mp3_path)
        except Exception:
            wav_path = audio_dir / f"{shot_id}.wav"
            self._write_silence(wav_path, max(1.2, min(6.0, len(text) / 8)))
            return str(wav_path)

    def _resolve_voice(self, voice_id: str) -> str:
        if not voice_id:
            return self.default_voice
        if voice_id in VOICE_MAP:
            return VOICE_MAP[voice_id]
        if voice_id.startswith("zh-CN-"):
            return voice_id
        return self.default_voice

    def _write_silence(self, path, duration: float) -> None:
        sample_rate = 16000
        frames = int(sample_rate * duration)
        with wave.open(str(path), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(sample_rate)
            wav.writeframes(b"\x00\x00" * frames)

    async def list_voices(self) -> list[dict]:
        voices = await edge_tts.list_voices()
        return [v for v in voices if v["Locale"].startswith("zh-CN")]

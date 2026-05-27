import asyncio
import base64

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
    """Edge-TTS service. Real synthesis failures are surfaced to the pipeline."""

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

        params = EMOTION_PARAMS.get(emotion, EMOTION_PARAMS["neutral"])
        errors: list[str] = []
        for voice in self._voice_candidates(voice_id):
            try:
                communicate = edge_tts.Communicate(
                    text=text,
                    voice=voice,
                    rate=params["rate"],
                    pitch=params["pitch"],
                )
                await communicate.save(str(mp3_path))
                if mp3_path.exists() and mp3_path.stat().st_size > 0:
                    return str(mp3_path)
                errors.append(f"{voice}: 输出文件为空")
            except Exception as exc:
                errors.append(f"{voice}: {exc}")

        wav_path = audio_dir / f"{shot_id}.wav"
        try:
            await self._generate_windows_sapi(text, wav_path)
            if wav_path.exists() and wav_path.stat().st_size > 2048:
                return str(wav_path)
            errors.append("Windows SAPI: 生成文件为空")
        except Exception as exc:
            errors.append(f"Windows SAPI: {exc}")

        raise RuntimeError("配音生成失败: " + " | ".join(errors[-3:]))

    def _voice_candidates(self, voice_id: str) -> list[str]:
        resolved = self._resolve_voice(voice_id)
        candidates = [
            resolved,
            self.default_voice,
            "zh-CN-XiaoxiaoNeural",
            "zh-CN-YunxiNeural",
            "zh-CN-YunjianNeural",
        ]
        return list(dict.fromkeys(v for v in candidates if v))

    def _resolve_voice(self, voice_id: str) -> str:
        if not voice_id:
            return self.default_voice
        if voice_id in VOICE_MAP:
            return VOICE_MAP[voice_id]
        if voice_id.startswith("zh-CN-"):
            return voice_id
        return self.default_voice

    async def _generate_windows_sapi(self, text: str, wav_path) -> None:
        encoded_text = base64.b64encode(text.encode("utf-8")).decode("ascii")
        escaped_path = str(wav_path).replace("'", "''")
        ps = f"""
$ErrorActionPreference = 'Stop'
$text = [System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{encoded_text}'))
$path = '{escaped_path}'
$dir = Split-Path -Parent $path
New-Item -ItemType Directory -Force -Path $dir | Out-Null
$voice = New-Object -ComObject SAPI.SpVoice
$stream = New-Object -ComObject SAPI.SpFileStream
$format = New-Object -ComObject SAPI.SpAudioFormat
$format.Type = 22
$stream.Format = $format
$stream.Open($path, 3)
$voice.AudioOutputStream = $stream
[void]$voice.Speak($text)
$stream.Close()
"""
        encoded_command = base64.b64encode(ps.encode("utf-16le")).decode("ascii")
        proc = await asyncio.create_subprocess_exec(
            "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-EncodedCommand",
            encoded_command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(stderr.decode("utf-8", errors="ignore")[-1000:])
        if not wav_path.exists() or wav_path.stat().st_size <= 2048:
            raise RuntimeError("Windows SAPI 未生成有效音频")

    async def list_voices(self) -> list[dict]:
        voices = await edge_tts.list_voices()
        return [v for v in voices if v["Locale"].startswith("zh-CN")]

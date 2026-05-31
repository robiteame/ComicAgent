"""Compact API connectivity check.

This script uses existing .env configuration and prints no secrets:
- Mimo generates a short script and one storyboard shot.
- Mimo built-in TTS writes the matching local audio file.
- Doubao Seedance generates one shot video and a saved single frame.
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import settings
from services.llm_service import LLMService
from services.tts_service import TTSService
from services.video_service import SeedanceVideoService


def _print_config() -> None:
    print("CONFIG")
    print(f"  LLM_PROVIDER={settings.LLM_PROVIDER}")
    print(f"  MIMO_MODEL={settings.MIMO_MODEL}")
    print(f"  MIMO_MULTIMODAL_MODEL={settings.MIMO_MULTIMODAL_MODEL}")
    print(f"  MIMO_TTS_MODEL={settings.MIMO_TTS_MODEL}")
    print(f"  MIMO_KEY_PRESENT={bool(settings.MIMO_API_KEY)}")
    print(f"  VIDEO_PROVIDER={settings.VIDEO_PROVIDER}")
    print(f"  SEEDDANCE_BASE_URL={settings.SEEDDANCE_BASE_URL}")
    print(f"  SEEDDANCE_MODEL={settings.SEEDDANCE_MODEL}")
    print(f"  SEEDDANCE_KEY_PRESENT={bool(settings.SEEDDANCE_API_KEY or settings.ARK_API_KEY or settings.SEEDREAM_API_KEY)}")
    print(f"  TTS_PROVIDER={settings.TTS_PROVIDER}")


async def _check_mimo_storyboard() -> dict:
    result = await LLMService().call_json(
        "你是漫剧编导，只输出 JSON，不要 Markdown。",
        """
请生成一个极短中文漫剧测试剧本和单组分镜，用于接口连通性测试。
JSON 结构：
{
  "title": "标题",
  "script": "80字以内短剧本",
  "shot": {
    "shot_id": "mimo_seedance_check",
    "shot_type": "medium",
    "scene_description": "英文画面提示词，适合文生视频",
    "character_action": "英文动作提示词",
    "dialogue": "一句中文台词",
    "emotion": "happy",
    "duration": 5
  }
}
""",
        temperature=0,
        max_retries=0,
        allow_fallback=False,
        model_override=settings.MIMO_MULTIMODAL_MODEL,
    )
    shot = result.get("shot") or {}
    if not result.get("script") or not shot.get("scene_description") or not shot.get("dialogue"):
        raise RuntimeError(f"unexpected Mimo storyboard result: {result}")
    print(f"MIMO_OK title={result.get('title', '')} dialogue={shot.get('dialogue', '')}")
    return result


async def _check_tts(story: dict) -> str:
    shot = story["shot"]
    path = await TTSService().generate_dialogue(
        text=shot["dialogue"],
        emotion=shot.get("emotion", "neutral"),
        project_id="api_diagnostics",
        shot_id=shot.get("shot_id", "mimo_tts_check"),
    )
    audio = Path(path)
    if not audio.exists() or audio.stat().st_size <= 1024:
        raise RuntimeError(f"TTS output is missing or too small: {audio}")
    print(f"MIMO_TTS_OK {audio} {audio.stat().st_size} bytes")
    return str(audio)


async def _check_seedance(story: dict) -> dict[str, str]:
    shot = story["shot"]
    prompt = ", ".join(
        part
        for part in [
            shot.get("scene_description", ""),
            shot.get("character_action", ""),
            "vertical cinematic comic shot, gentle camera movement, clean composition, no subtitles, no watermark",
        ]
        if part
    )
    result = await SeedanceVideoService().generate_single_shot(
        prompt=prompt,
        project_id="api_diagnostics",
        shot_id=shot.get("shot_id", "seedance_check"),
        duration=int(shot.get("duration") or 5),
    )
    frame_path = Path(result["frame_path"])
    with Image.open(frame_path) as image:
        image.verify()
    video_path = Path(result["video_path"])
    _assert_video(video_path)
    print(f"SEEDDANCE_OK video={video_path} {video_path.stat().st_size} bytes")
    print(f"SEEDDANCE_FRAME_OK {frame_path} {frame_path.stat().st_size} bytes")
    return result


def _fallback_story() -> dict:
    return {
        "title": "diagnostic fallback",
        "script": "固定诊断镜头，仅在 Mimo 失败时用于继续探测 TTS 和 Seedance。",
        "shot": {
            "shot_id": "diagnostic_single_shot",
            "shot_type": "medium",
            "scene_description": "A friendly white service robot waves beside a sunlit desk in a vertical cinematic shot",
            "character_action": "the robot gently raises one hand to greet the viewer",
            "dialogue": "主人，早上好！",
            "emotion": "happy",
            "duration": 5,
        },
    }


def _assert_video(video_path: Path) -> None:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type", "-of", "json", str(video_path)],
        check=True,
        capture_output=True,
        text=True,
    )
    if "video" not in result.stdout:
        raise RuntimeError(f"Seedance output has no video stream: {video_path}")


async def main() -> int:
    _print_config()
    failures: list[str] = []
    story: dict | None = None
    audio_path = ""
    seedance_result: dict[str, str] = {}

    try:
        story = await _check_mimo_storyboard()
    except Exception as exc:
        failures.append(f"MIMO: {exc}")
        print(f"MIMO_FAILED {exc}")

    probe_story = story or _fallback_story()
    if story is None:
        print("USING_STATIC_STORY_FOR_DOWNSTREAM_PROBES")

    try:
        audio_path = await _check_tts(probe_story)
    except Exception as exc:
        failures.append(f"MIMO_TTS: {exc}")
        print(f"MIMO_TTS_FAILED {exc}")

    try:
        seedance_result = await _check_seedance(probe_story)
    except Exception as exc:
        failures.append(f"SEEDDANCE: {exc}")
        print(f"SEEDDANCE_FAILED {exc}")

    if failures:
        print("DIAGNOSTICS_FAILED")
        return 1

    print(f"OUTPUT_AUDIO {audio_path}")
    print(f"OUTPUT_FRAME {seedance_result['frame_path']}")
    print(f"OUTPUT_VIDEO {seedance_result['video_path']}")
    print("DIAGNOSTICS_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

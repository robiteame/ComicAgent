"""Check the real external services used by the full comic pipeline.

This is intentionally small and direct:
- Mimo must return JSON from the configured model.
- TTS must write a real audio file.
- Seedream must write a real image file.

It prints no secrets.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import settings
from services.image_service import ImageService
from services.llm_service import LLMService
from services.tts_service import TTSService


def _print_config() -> None:
    print("CONFIG")
    print(f"  LLM_PROVIDER={settings.LLM_PROVIDER}")
    print(f"  MIMO_MODEL={settings.MIMO_MODEL}")
    print(f"  MIMO_KEY_PRESENT={bool(settings.MIMO_API_KEY)}")
    print(f"  IMAGE_PROVIDER={settings.IMAGE_PROVIDER}")
    print(f"  SEEDDANCE_BASE_URL={settings.SEEDDANCE_BASE_URL}")
    print(f"  SEEDREAM_MODEL={settings.SEEDREAM_MODEL}")
    print(f"  SEEDREAM_IMAGE_SIZE={settings.SEEDREAM_IMAGE_SIZE}")
    print(f"  ARK_KEY_PRESENT={bool(settings.ARK_API_KEY or settings.SEEDDANCE_API_KEY or settings.STABILITY_API_KEY)}")
    print(f"  TTS_PROVIDER={settings.TTS_PROVIDER}")
    print(f"  TTS_DEFAULT_VOICE={settings.TTS_DEFAULT_VOICE}")


async def _check_llm() -> None:
    result = await LLMService().call_json(
        "你只输出 JSON。",
        '输出 {"ok": true, "stage": "llm"}',
        temperature=0,
        max_retries=0,
    )
    if result.get("ok") is not True:
        raise RuntimeError(f"unexpected LLM result: {result}")
    print("LLM_OK")


async def _check_tts() -> None:
    path = await TTSService().generate_dialogue(
        text="\u8fd9\u662f\u4e00\u6b21\u771f\u5b9e\u914d\u97f3\u8bca\u65ad\u3002",
        project_id="api_diagnostics",
        shot_id="tts_check",
    )
    audio = Path(path)
    if not audio.exists() or audio.stat().st_size <= 1024:
        raise RuntimeError(f"TTS output is missing or too small: {audio}")
    print(f"TTS_OK {audio} {audio.stat().st_size} bytes")


async def _check_seedream() -> None:
    shot = {
        "shot_id": "seedream_check",
        "version": 1,
        "shot_type": "medium",
        "scene_description": "A vertical Chinese comic frame of a creator reviewing storyboard panels on a bright desk",
        "character_action": "the creator smiles while holding a stylus",
        "characters_in_scene": ["主角"],
        "camera_angle": "正面",
        "emotion": "happy",
        "visual_notes": "diagnostic image generation",
    }
    characters = [
        {
            "name": "主角",
            "visual_prompt": "young Chinese comic creator, short black hair, clean casual hoodie",
            "key_features": ["short black hair", "white hoodie", "stylus"],
            "emotion_variants": {"happy": "gentle confident smile"},
            "negative_prompt": "watermark, subtitles, logo",
            "seed": 42,
        }
    ]
    path = await ImageService().generate_shot_image(shot, characters, {}, "api_diagnostics", 42)
    image_path = Path(path)
    if not image_path.exists() or image_path.stat().st_size <= 4096:
        raise RuntimeError(f"Seedream output is missing or too small: {image_path}")
    with Image.open(image_path) as image:
        image.verify()
    print(f"SEEDREAM_OK {image_path} {image_path.stat().st_size} bytes")


async def main() -> int:
    _print_config()
    failures: list[str] = []
    for name, check in [
        ("LLM", _check_llm),
        ("TTS", _check_tts),
        ("SEEDREAM", _check_seedream),
    ]:
        try:
            await check()
        except Exception as exc:
            failures.append(f"{name}: {exc}")
            print(f"{name}_FAILED {exc}")

    if failures:
        print("DIAGNOSTICS_FAILED")
        return 1
    print("DIAGNOSTICS_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

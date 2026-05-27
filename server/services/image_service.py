import hashlib
import textwrap

import httpx
from PIL import Image, ImageDraw, ImageFont

from config import settings


class ImageService:
    """Image generation service with a deterministic local placeholder fallback."""

    def __init__(self):
        self.api_key = settings.STABILITY_API_KEY
        self.api_url = settings.STABILITY_API_URL
        self.provider = (settings.IMAGE_PROVIDER or "local").lower()
        self.output_dir = settings.OUTPUT_DIR / "projects"

    async def generate_shot_image(
        self,
        shot: dict,
        characters: list,
        style_params: dict,
        project_id: str,
        seed: int = 42,
    ) -> str:
        prompt, negative_prompt = self._build_prompt(shot, characters, style_params)

        shot_dir = self.output_dir / project_id / "shots"
        shot_dir.mkdir(parents=True, exist_ok=True)
        image_path = shot_dir / f"{shot['shot_id']}_v{shot.get('version', 1)}.png"

        image_data: bytes | None = None
        if self.provider == "stability" and self.api_key:
            try:
                image_data = await self._call_stability(prompt, negative_prompt, seed)
            except Exception:
                image_data = None

        if image_data:
            image_path.write_bytes(image_data)
        else:
            self._write_placeholder(image_path, shot, seed)

        return str(image_path)

    def _build_prompt(self, shot: dict, characters: list, style_params: dict) -> tuple[str, str]:
        prompt_parts: list[str] = []
        negative_parts: list[str] = []

        if style_params.get("prompt_prefix"):
            prompt_parts.append(style_params["prompt_prefix"])

        for char_name in shot.get("characters_in_scene", []):
            char_card = next((c for c in characters if c.get("name") == char_name), None)
            if not char_card:
                continue
            prompt_parts.append(char_card.get("visual_prompt", ""))
            prompt_parts.extend(char_card.get("key_features", []))
            emotion = shot.get("emotion", "neutral")
            if char_card.get("emotion_variants", {}).get(emotion):
                prompt_parts.append(char_card["emotion_variants"][emotion])
            if char_card.get("negative_prompt"):
                negative_parts.append(char_card["negative_prompt"])

        prompt_parts.extend(
            [
                shot.get("scene_description", ""),
                self._camera_prompt(shot.get("shot_type", "medium")),
                self._angle_prompt(shot.get("camera_angle", "正面")),
                "clean comic frame, soft daylight, high detail",
            ]
        )
        negative_parts.extend(["low quality", "blurry", "watermark", "text artifacts", "bad anatomy"])
        return ", ".join(part for part in prompt_parts if part), ", ".join(negative_parts)

    async def _call_stability(self, prompt: str, negative_prompt: str, seed: int) -> bytes:
        async with httpx.AsyncClient(timeout=45) as client:
            response = await client.post(
                f"{self.api_url}/stable-image/generate/core",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Accept": "image/*",
                },
                data={
                    "prompt": prompt,
                    "negative_prompt": negative_prompt,
                    "seed": seed,
                    "output_format": "png",
                },
            )
            response.raise_for_status()
            return response.content

    def _write_placeholder(self, image_path, shot: dict, seed: int) -> None:
        width, height = 1080, 1920
        digest = hashlib.sha256(f"{shot.get('shot_id')}:{seed}".encode("utf-8")).digest()
        accent = (80 + digest[0] % 80, 120 + digest[1] % 80, 180 + digest[2] % 55)
        bg_top = (245, 249, 253)
        bg_bottom = (228, 238, 248)

        image = Image.new("RGB", (width, height), bg_top)
        draw = ImageDraw.Draw(image)
        for y in range(height):
            t = y / height
            color = tuple(int(bg_top[i] * (1 - t) + bg_bottom[i] * t) for i in range(3))
            draw.line((0, y, width, y), fill=color)

        draw.rounded_rectangle((90, 180, 990, 1390), radius=44, fill=(255, 255, 255), outline=(214, 226, 238), width=3)
        draw.rounded_rectangle((150, 260, 930, 1120), radius=36, fill=(240, 246, 252), outline=accent, width=5)
        draw.ellipse((345, 410, 735, 800), fill=(255, 255, 255), outline=accent, width=7)
        draw.rounded_rectangle((275, 800, 805, 1090), radius=48, fill=(255, 255, 255), outline=(207, 220, 233), width=4)
        draw.line((160, 1180, 920, 1180), fill=(214, 226, 238), width=4)

        font_title = self._font(46)
        font_body = self._font(34)
        font_meta = self._font(26)
        title = f"镜头 {shot.get('shot_id', '')[-4:]}"
        draw.text((150, 1225), title, fill=(32, 45, 58), font=font_title)
        scene = shot.get("scene_description") or "本地占位画面"
        wrapped = "\n".join(textwrap.wrap(scene, width=22))[:180]
        draw.multiline_text((150, 1310), wrapped, fill=(70, 86, 102), font=font_body, spacing=12)
        meta = f"{shot.get('shot_type', 'medium')} / {shot.get('emotion', 'neutral')} / {shot.get('camera_angle', '正面')}"
        draw.text((150, 1720), meta, fill=(105, 122, 140), font=font_meta)

        image.save(image_path, "PNG")

    def _font(self, size: int):
        candidates = [
            "C:/Windows/Fonts/msyh.ttc",
            "C:/Windows/Fonts/simhei.ttf",
            "C:/Windows/Fonts/arial.ttf",
        ]
        for path in candidates:
            try:
                return ImageFont.truetype(path, size=size)
            except Exception:
                continue
        return ImageFont.load_default()

    def _camera_prompt(self, shot_type: str) -> str:
        return {
            "wide": "wide establishing shot",
            "medium": "medium shot",
            "close-up": "close-up shot",
            "extreme_close": "extreme close-up",
        }.get(shot_type, "medium shot")

    def _angle_prompt(self, camera_angle: str) -> str:
        return {
            "正面": "front view",
            "侧面": "side view",
            "俯视": "high angle",
            "仰视": "low angle",
        }.get(camera_angle, "front view")

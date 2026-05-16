import os
import uuid
import httpx
from pathlib import Path
from config import settings


class ImageService:
    """图像生成服务（云端 API 过渡版）"""

    def __init__(self):
        self.api_key = settings.STABILITY_API_KEY
        self.api_url = settings.STABILITY_API_URL
        self.provider = settings.IMAGE_PROVIDER
        self.output_dir = settings.OUTPUT_DIR / "projects"

    async def generate_shot_image(
        self,
        shot: dict,
        characters: list,
        style_params: dict,
        project_id: str,
        seed: int = 42,
    ) -> str:
        """为镜头生成图像，注入角色卡片"""

        # 组装 prompt
        prompt, negative_prompt = self._build_prompt(shot, characters, style_params)

        # 生成图像
        image_data = await self._call_api(prompt, negative_prompt, seed)

        # 保存图片
        shot_dir = self.output_dir / project_id / "shots"
        shot_dir.mkdir(parents=True, exist_ok=True)
        image_path = shot_dir / f"{shot['shot_id']}_v{shot.get('version', 1)}.png"

        with open(image_path, "wb") as f:
            f.write(image_data)

        return str(image_path)

    def _build_prompt(
        self, shot: dict, characters: list, style_params: dict
    ) -> tuple[str, str]:
        """组装图像生成 prompt"""
        prompt_parts = []
        neg_parts = []

        # 风格前缀
        if style_params and style_params.get("prompt_prefix"):
            prompt_parts.append(style_params["prompt_prefix"])

        # 角色描述（从角色卡片强制注入）
        for char_name in shot.get("characters_in_scene", []):
            char_card = next((c for c in characters if c["name"] == char_name), None)
            if char_card:
                prompt_parts.append(char_card.get("visual_prompt", ""))
                prompt_parts.extend(char_card.get("key_features", []))

                # 情绪变体
                emotion = shot.get("emotion", "neutral")
                emotion_variants = char_card.get("emotion_variants", {})
                if emotion in emotion_variants:
                    prompt_parts.append(emotion_variants[emotion])

                # negative
                if char_card.get("negative_prompt"):
                    neg_parts.append(char_card["negative_prompt"])

        # 场景描述
        prompt_parts.append(shot.get("scene_description", ""))

        # 镜头类型
        camera_map = {
            "wide": "wide shot, full scene, establishing shot",
            "medium": "medium shot, waist up, character interaction",
            "close-up": "close-up shot, face and shoulders, emotional focus",
            "extreme_close": "extreme close-up, eyes detail, cinematic",
        }
        prompt_parts.append(camera_map.get(shot.get("shot_type", "medium"), "medium shot"))

        # 镜头角度
        angle_map = {
            "正面": "front view, facing camera",
            "侧面": "side view, profile",
            "俯视": "high angle, looking down",
            "仰视": "low angle, looking up",
        }
        prompt_parts.append(angle_map.get(shot.get("camera_angle", "正面"), "front view"))

        # 画面质量
        prompt_parts.append("masterpiece, best quality, highly detailed, 8k resolution")

        # negative 固定部分
        neg_parts.extend(
            [
                "low quality, worst quality, bad anatomy",
                "bad hands, missing fingers, extra fingers",
                "blurry, watermark, text, signature",
                "deformed, ugly, duplicate",
            ]
        )

        return ", ".join(p for p in prompt_parts if p), ", ".join(neg_parts)

    async def _call_api(self, prompt: str, negative_prompt: str, seed: int) -> bytes:
        """调用 Stability AI API"""
        async with httpx.AsyncClient(timeout=60) as client:
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

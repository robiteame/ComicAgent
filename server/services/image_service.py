import base64
from io import BytesIO

import httpx
from PIL import Image

from config import settings


class ImageService:
    """Image generation service backed by real remote image APIs."""

    def __init__(self):
        self.api_key = settings.ARK_API_KEY or settings.SEEDDANCE_API_KEY or settings.STABILITY_API_KEY
        self.api_url = settings.STABILITY_API_URL
        self.provider = (settings.IMAGE_PROVIDER or "").lower()
        self.output_dir = settings.OUTPUT_DIR / "projects"
        self.seedream_base_url = settings.SEEDDANCE_BASE_URL.rstrip("/")
        self.seedream_model = settings.SEEDREAM_MODEL or settings.IMAGE_PROVIDER

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

        if self.provider == "stability":
            if not self.api_key:
                raise RuntimeError("未配置 Stability API Key，无法生成真实画面")
            image_data = await self._call_stability(prompt, negative_prompt, seed)
        elif self._is_seedream_provider():
            if not self.api_key:
                raise RuntimeError("未配置火山方舟 API Key，无法调用 Seedream 生成真实画面")
            image_data = await self._call_seedream(prompt, negative_prompt, seed)
        else:
            raise RuntimeError(f"未支持的图像生成 provider: {settings.IMAGE_PROVIDER}")

        if not image_data:
            raise RuntimeError("图像生成接口未返回图片数据")

        self._validate_image(image_data)
        image_path.write_bytes(image_data)
        return str(image_path)

    def _is_seedream_provider(self) -> bool:
        provider = self.provider.replace("_", "-")
        return provider.startswith("doubao-seedream") or provider in {"seedream", "volcengine", "ark"}

    async def _call_seedream(self, prompt: str, negative_prompt: str, seed: int) -> bytes:
        errors: list[str] = []
        models = self._seedream_model_candidates()
        sizes = [settings.SEEDREAM_IMAGE_SIZE, "1440x2560", "2K"]

        async with httpx.AsyncClient(timeout=180) as client:
            for model in models:
                for size in list(dict.fromkeys(size for size in sizes if size)):
                    payload = {
                        "model": model,
                        "prompt": f"{prompt}\nNegative prompt: {negative_prompt}",
                        "response_format": "b64_json",
                        "size": size,
                        "n": 1,
                        "seed": seed,
                        "watermark": False,
                        "output_format": "png",
                        "sequential_image_generation": "disabled",
                    }
                    try:
                        response = await client.post(
                            f"{self.seedream_base_url}/images/generations",
                            headers={
                                "Authorization": f"Bearer {self.api_key}",
                                "Content-Type": "application/json",
                            },
                            json=payload,
                        )
                        if response.status_code in {401, 403}:
                            raise PermissionError(response.text[:600])
                        if response.status_code >= 400:
                            errors.append(f"{model} {size}: {response.status_code} {response.text[:400]}")
                            continue
                        return await self._extract_image_bytes(client, response)
                    except PermissionError as exc:
                        raise RuntimeError(f"火山方舟鉴权失败，请确认 API Key 和模型权限: {exc}") from exc
                    except Exception as exc:
                        errors.append(f"{model} {size}: {exc}")

        raise RuntimeError("Seedream 图像生成失败: " + " | ".join(errors[-4:]))

    def _seedream_model_candidates(self) -> list[str]:
        raw = [self.seedream_model, settings.IMAGE_PROVIDER]
        candidates: list[str] = []
        for value in raw:
            if not value:
                continue
            candidates.extend(
                [
                    value,
                    value.replace(".", "-"),
                    value.replace(".0", "-0"),
                ]
            )
        candidates.extend(
            [
                "doubao-seedream-5-0-lite",
                "doubao-seedream-5-0-lite-260128",
            ]
        )
        return list(dict.fromkeys(candidates))

    async def _extract_image_bytes(self, client: httpx.AsyncClient, response: httpx.Response) -> bytes:
        content_type = response.headers.get("content-type", "")
        if content_type.startswith("image/"):
            return response.content

        data = response.json()
        items = data.get("data") if isinstance(data, dict) else None
        if not items:
            raise RuntimeError(f"图像接口返回缺少 data: {data}")

        item = items[0]
        b64_data = item.get("b64_json") or item.get("image") or item.get("base64")
        if b64_data:
            if "," in b64_data and b64_data.startswith("data:"):
                b64_data = b64_data.split(",", 1)[1]
            return base64.b64decode(b64_data)

        image_url = item.get("url") or item.get("image_url")
        if isinstance(image_url, dict):
            image_url = image_url.get("url")
        if image_url:
            image_response = await client.get(image_url)
            image_response.raise_for_status()
            return image_response.content

        raise RuntimeError(f"无法解析图像接口返回: {data}")

    def _validate_image(self, image_data: bytes) -> None:
        try:
            with Image.open(BytesIO(image_data)) as image:
                image.verify()
        except Exception as exc:
            raise RuntimeError(f"图像数据无法打开: {exc}") from exc

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
                shot.get("character_action", ""),
                shot.get("visual_notes", ""),
                self._camera_prompt(shot.get("shot_type", "medium")),
                self._angle_prompt(shot.get("camera_angle", "正面")),
                "vertical cinematic comic frame, expressive characters, clean composition, high detail",
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

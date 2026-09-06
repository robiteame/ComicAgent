import base64
import json
import re
import textwrap
from io import BytesIO

import httpx
from PIL import Image, ImageDraw, ImageFont

from config import settings
from services.consistency_service import ConsistencyService
from services.reference_asset_service import ReferenceAssetService
from services.style_templates import style_prompt_params
from services.security import atomic_write_bytes, download_remote_bytes, safe_path, validate_identifier
from services.storage_service import StorageQuotaExceeded, StorageService


class ImageService:
    """Image generation service backed by real remote image APIs."""

    def __init__(self):
        self.output_dir = settings.OUTPUT_DIR / "projects"
        self.consistency = ConsistencyService()
        self.reference_assets = ReferenceAssetService()
        self.storage = StorageService()

    # 运行时实时读取 settings，保证保存模型/API 配置后新任务即生效。
    @property
    def api_key(self) -> str:
        return settings.ARK_API_KEY or settings.SEEDDANCE_API_KEY or settings.SEEDREAM_API_KEY or settings.STABILITY_API_KEY

    @property
    def api_url(self) -> str:
        return settings.STABILITY_API_URL

    @property
    def provider(self) -> str:
        return (settings.IMAGE_PROVIDER or "").lower()

    @property
    def seedream_base_url(self) -> str:
        return settings.SEEDDANCE_BASE_URL.rstrip("/")

    @property
    def seedream_model(self) -> str:
        return settings.SEEDREAM_MODEL or settings.IMAGE_PROVIDER

    async def generate_shot_image(
        self,
        shot: dict,
        characters: list,
        style_params: dict,
        project_id: str,
        seed: int = 42,
    ) -> str:
        prompt, negative_prompt = self._build_prompt(shot, characters, style_params)
        reference_images = self._reference_images_for_request(shot)

        try:
            safe_project_id = validate_identifier(project_id, "项目 ID")
            safe_shot_id = validate_identifier(str(shot["shot_id"]), "镜头 ID")
        except ValueError as exc:
            raise RuntimeError(str(exc)) from exc
        shot_dir = safe_path(self.output_dir, safe_project_id, "shots", create_parent=True)
        image_path = shot_dir / f"{safe_shot_id}_v{int(shot.get('version', 1) or 1)}.png"

        preferred_size = self._size_for_ratio(shot.get("output_format"))

        if self.provider == "stability" and self.api_key:
            image_data = await self._call_stability(prompt, negative_prompt, seed)
        elif self._is_seedream_provider() and self.api_key:
            image_data = await self._call_seedream(prompt, negative_prompt, seed, reference_images, preferred_size=preferred_size)
        else:
            image_data = self._generate_placeholder("SHOT PLACEHOLDER", prompt, self._placeholder_size(preferred_size))

        if not image_data:
            raise RuntimeError("图像生成接口未返回图片数据")

        self._validate_image(image_data)
        self._write_image(project_id, image_path, image_data)
        return str(image_path)

    async def generate_scene_baseline_reference(
        self,
        scene: dict,
        style: str,
        project_id: str,
        seed: int = 1200,
    ) -> str:
        prompt, negative_prompt = self.consistency.scene_baseline_prompt(scene, style)
        style_params = style_prompt_params(style)
        prompt = ", ".join(part for part in [style_params.get("scene_baseline_prompt", ""), prompt] if part)
        negative_prompt = ", ".join(part for part in [negative_prompt, style_params.get("negative_prompt", "")] if part)

        try:
            safe_project_id = validate_identifier(project_id, "项目 ID")
        except ValueError as exc:
            raise RuntimeError(str(exc)) from exc
        ref_dir = safe_path(self.output_dir, safe_project_id, "scenes", create_parent=True)
        safe_key = scene.get("id") or scene.get("scene_group_key") or scene.get("location") or scene.get("name", "scene")
        safe_name = re.sub(r"[^a-zA-Z0-9_-]+", "_", str(safe_key)).strip("_") or "scene"
        scene_dir = ref_dir / safe_name
        scene_dir.mkdir(parents=True, exist_ok=True)
        image_path = scene_dir / "baseline_original.png"
        preferred_size = settings.SEEDREAM_IMAGE_SIZE or "1440x2560"

        if self.provider == "stability" and self.api_key:
            image_data = await self._call_stability(prompt, negative_prompt, seed)
        elif self._is_seedream_provider() and self.api_key:
            image_data = await self._call_seedream(prompt, negative_prompt, seed, preferred_size=preferred_size)
        else:
            image_data = self._generate_placeholder("SCENE BASELINE", prompt, self._placeholder_size(preferred_size))

        self._validate_image(image_data)
        self._write_image(project_id, image_path, image_data)
        return str(image_path)

    async def generate_character_reference(
        self,
        character: dict,
        style: str,
        project_id: str,
        seed: int = 42,
    ) -> str:
        prompt, negative_prompt = self._build_character_reference_prompt(character, style)

        try:
            safe_project_id = validate_identifier(project_id, "项目 ID")
        except ValueError as exc:
            raise RuntimeError(str(exc)) from exc
        ref_dir = safe_path(self.output_dir, safe_project_id, "characters", create_parent=True)
        identity_key = character.get("id") or character.get("asset_id") or character.get("name", "character")
        safe_name = re.sub(r"[^a-zA-Z0-9_-]+", "_", str(identity_key)).strip("_") or "character"
        character_dir = ref_dir / safe_name
        character_dir.mkdir(parents=True, exist_ok=True)
        image_path = character_dir / "three_view_original.png"
        preferred_size = "2048x2048"

        if self.provider == "stability" and self.api_key:
            image_data = await self._call_stability(prompt, negative_prompt, seed)
        elif self._is_seedream_provider() and self.api_key:
            image_data = await self._call_seedream(prompt, negative_prompt, seed, preferred_size=preferred_size)
        else:
            image_data = self._generate_placeholder("CHARACTER REF", prompt, self._placeholder_size(preferred_size))

        self._validate_image(image_data)
        self._write_image(project_id, image_path, image_data)
        return str(image_path)

    def _is_seedream_provider(self) -> bool:
        provider = self.provider.replace("_", "-")
        return provider.startswith("doubao-seedream") or provider in {"seedream", "volcengine", "ark"}

    def _size_for_ratio(self, output_format: str | None) -> str:
        # 画面比例 -> Seedream 出图尺寸。未识别的比例回退到 settings 配置的默认尺寸，
        # 保证用户在前端切换 9:16 / 16:9 / 1:1 等比例后，定稿故事板真实按比例出图。
        ratio = str(output_format or "").strip()
        ratio_size_map = {
            "9:16": "1440x2560",
            "3:4": "1536x2048",
            "1:1": "2048x2048",
            "4:3": "2048x1536",
            "16:9": "2560x1440",
        }
        return ratio_size_map.get(ratio, settings.SEEDREAM_IMAGE_SIZE or "1440x2560")

    def build_shot_prompt(self, shot: dict, characters: list, style_params: dict) -> tuple[str, str]:
        return self._build_prompt(shot, characters, style_params)

    def _placeholder_size(self, preferred_size: str | None = None) -> tuple[int, int]:
        match = re.match(r"\s*(\d+)\s*[xX]\s*(\d+)", preferred_size or settings.SEEDREAM_IMAGE_SIZE or "")
        if match:
            return int(match.group(1)), int(match.group(2))
        return 1440, 2560

    def _placeholder_font(self, size: int):
        for name in ("msyh.ttc", "arial.ttf", "DejaVuSans.ttf"):
            try:
                return ImageFont.truetype(name, size)
            except Exception:
                continue
        return ImageFont.load_default()

    def _generate_placeholder(self, label: str, prompt: str, size: tuple[int, int]) -> bytes:
        """Render a deterministic placeholder image so the full pipeline runs without image API keys."""
        width, height = size
        tint = sum(ord(ch) for ch in label)
        background = (30 + tint * 53 % 60, 30 + tint * 97 % 60, 50 + tint * 131 % 60)
        image = Image.new("RGB", (width, height), background)
        draw = ImageDraw.Draw(image)
        font_px = max(width // 40, 16)
        title_font = self._placeholder_font(max(width // 18, 28))
        body_font = self._placeholder_font(font_px)
        margin = int(width * 0.06)
        draw.text((margin, margin), label, fill=(245, 245, 245), font=title_font)
        body = " ".join(str(prompt or "").split())[:600]
        chars_per_line = max(int(width * 0.9 / (font_px * 0.6)), 24)
        wrapped = textwrap.fill(body, width=chars_per_line, max_lines=12, placeholder=" …")
        draw.multiline_text((margin, int(height * 0.16)), wrapped, fill=(215, 215, 215), font=body_font, spacing=8)
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        data = buffer.getvalue()
        self._validate_image(data)
        return data

    async def _call_seedream(
        self,
        prompt: str,
        negative_prompt: str,
        seed: int,
        reference_images: list[str] | None = None,
        preferred_size: str | None = None,
    ) -> bytes:
        errors: list[str] = []
        models = self._seedream_model_candidates()
        sizes = [preferred_size, settings.SEEDREAM_IMAGE_SIZE, "2048x2048", "1440x2560", "2K"]

        async with httpx.AsyncClient(timeout=180) as client:
            for model in models:
                for size in list(dict.fromkeys(size for size in sizes if size)):
                    payload = self._seedream_payload(model, prompt, negative_prompt, seed, size, reference_images)
                    try:
                        request = client.build_request(
                            "POST",
                            f"{self.seedream_base_url}/images/generations",
                            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                            json=payload,
                        )
                        response = await client.send(request, stream=True)
                        response_bytes = await self._read_bounded_response(response)
                        if response.status_code in {401, 403}:
                            raise PermissionError(response_bytes.decode("utf-8", errors="replace")[:600])
                        if response.status_code >= 400:
                            errors.append(f"{model} {size}: {response.status_code} {response_bytes.decode('utf-8', errors='replace')[:400]}")
                            continue
                        return await self._extract_image_bytes(client, response, response_bytes)
                    except PermissionError as exc:
                        raise RuntimeError(f"火山方舟鉴权失败，请确认 API Key 和模型权限: {exc}") from exc
                    except Exception as exc:
                        errors.append(f"{model} {size}: {exc}")

        raise RuntimeError("Seedream 图像生成失败: " + " | ".join(errors[-4:]))

    def _seedream_payload(
        self,
        model: str,
        prompt: str,
        negative_prompt: str,
        seed: int,
        size: str,
        reference_images: list[str] | None = None,
    ) -> dict:
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
        if reference_images:
            payload["image"] = reference_images[:8]
        return payload

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

    async def _extract_image_bytes(self, client: httpx.AsyncClient, response: httpx.Response, response_bytes: bytes) -> bytes:
        content_type = response.headers.get("content-type", "")
        if content_type.startswith("image/"):
            if len(response_bytes) > settings.MAX_IMAGE_GENERATION_BYTES:
                raise RuntimeError("图像数据超过大小限制")
            return response_bytes

        try:
            data = json.loads(response_bytes)
        except (TypeError, ValueError) as exc:
            raise RuntimeError("图像接口返回不是有效 JSON") from exc
        items = data.get("data") if isinstance(data, dict) else None
        if not items:
            raise RuntimeError(f"图像接口返回缺少 data: {data}")

        item = items[0]
        b64_data = item.get("b64_json") or item.get("image") or item.get("base64")
        if b64_data:
            if "," in b64_data and b64_data.startswith("data:"):
                b64_data = b64_data.split(",", 1)[1]
            if len(b64_data) > int(settings.MAX_IMAGE_GENERATION_BYTES * 4 / 3) + 16:
                raise RuntimeError("图像数据超过大小限制")
            decoded = base64.b64decode(b64_data, validate=True)
            if len(decoded) > settings.MAX_IMAGE_GENERATION_BYTES:
                raise RuntimeError("图像数据超过大小限制")
            return decoded

        image_url = item.get("url") or item.get("image_url")
        if isinstance(image_url, dict):
            image_url = image_url.get("url")
        if image_url:
            try:
                return await download_remote_bytes(
                    image_url,
                    max_bytes=settings.MAX_IMAGE_GENERATION_BYTES,
                    timeout=180,
                )
            except Exception as exc:
                raise RuntimeError(f"图像 URL 下载失败: {exc}") from exc

        raise RuntimeError(f"无法解析图像接口返回: {data}")

    async def _read_bounded_response(self, response: httpx.Response) -> bytes:
        limit = max(1024, int(settings.MAX_IMAGE_GENERATION_BYTES * 4 / 3) + 16)
        length = response.headers.get("content-length")
        if length and int(length) > limit:
            await response.aclose()
            raise RuntimeError("图像接口响应超过大小限制")
        body = bytearray()
        try:
            async for chunk in response.aiter_bytes(1024 * 1024):
                body.extend(chunk)
                if len(body) > limit:
                    raise RuntimeError("图像接口响应超过大小限制")
            return bytes(body)
        finally:
            await response.aclose()

    def _write_image(self, project_id: str, image_path, image_data: bytes) -> None:
        try:
            self.storage.ensure_project_capacity(project_id, len(image_data), replacing=image_path)
        except StorageQuotaExceeded as exc:
            raise RuntimeError("项目媒体存储空间不足") from exc
        atomic_write_bytes(image_path, image_data, minimum_size=1024)

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
        if style_params.get("style_label"):
            prompt_parts.append(f"locked visual style preset: {style_params['style_label']}")
        if style_params.get("consistency_prefix"):
            prompt_parts.append(style_params["consistency_prefix"])
        if style_params.get("negative_prompt"):
            negative_parts.append(style_params["negative_prompt"])
        prompt_parts.append("NON-NEGOTIABLE AGENT CONSISTENCY SOP overrides any single-shot custom prompt")
        if shot.get("scene_reference_images"):
            prompt_parts.append("scene baseline/reference assets are loaded and mandatory for environment, props, lighting and perspective")
        if shot.get("character_reference_images"):
            prompt_parts.append("character three-view reference assets are loaded and mandatory for identity, outfit, face and hairstyle")
        if shot.get("continuity_reference_path"):
            prompt_parts.append("previous shot final frame reference is loaded and mandatory for eye-line, pose, axis and depth continuity")
        if shot.get("reference_weights"):
            weights = shot.get("reference_weights") or {}
            prompt_parts.append(
                f"apply locked reference weights: environment/style {float(weights.get('environment') or 0.45):.2f}, character/action {float(weights.get('action') or 0.30):.2f}"
            )
        if shot.get("reference_assets"):
            roles = ", ".join(str(item.get("role", "")) for item in shot.get("reference_assets", []) if isinstance(item, dict))
            prompt_parts.append(f"mandatory persisted reference assets drive these roles: {roles}")
        if shot.get("continuity_profile"):
            profile = shot.get("continuity_profile") or {}
            prompt_parts.append(
                "locked continuity controls: "
                f"{', '.join(profile.get('editing_logic', []))}; "
                f"OpenPose {profile.get('openpose_lock', 'not_required')}; "
                f"Depth {profile.get('depth_lock', 'not_required')}; "
                f"LUT {profile.get('lut', 'project_scene_lut_locked')}; "
                f"{profile.get('ambient_audio_policy', '')}"
            )
            blocking = profile.get("character_blocking") or {}
            if blocking:
                order = blocking.get("character_order_left_to_right") or []
                prompt_parts.append(
                    "locked character blocking: "
                    f"left-to-right order {', '.join(order) if order else 'single subject'}; "
                    f"{blocking.get('axis_line', '180-degree axis locked')}; "
                    f"eye-line {blocking.get('eye_line_target', 'locked')}; "
                    f"{blocking.get('camera_movement_limit', '')}; "
                    f"{blocking.get('skin_light_integration', '')}"
                )
        if shot.get("consistency_context"):
            prompt_parts.append(shot["consistency_context"])
        if shot.get("skill_prompt_append"):
            prompt_parts.append(shot["skill_prompt_append"])

        for char_card in self._select_character_cards(shot, characters):
            prompt_parts.append(char_card.get("visual_prompt", ""))
            prompt_parts.extend(char_card.get("key_features", []))
            appearance = char_card.get("appearance") or {}
            if isinstance(appearance, dict):
                prompt_parts.extend(str(value) for value in appearance.values() if value)
            if char_card.get("reference_images"):
                prompt_parts.append("strictly preserve identity from the approved character three-view reference sheet")
            if char_card.get("lora_profile"):
                prompt_parts.append(f"fixed LoRA profile {char_card['lora_profile']}")
            if char_card.get("ip_adapter_profile"):
                prompt_parts.append(f"fixed IP-Adapter identity profile {char_card['ip_adapter_profile']}")
            if char_card.get("wardrobe_lock"):
                prompt_parts.append(char_card["wardrobe_lock"])
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
                shot.get("storyboard_prompt", ""),
                self._camera_prompt(shot.get("shot_type", "medium")),
                self._angle_prompt(shot.get("camera_angle", "正面")),
                "finished color keyframe, approved storyboard standard, consistent character design, consistent scene style",
                "vertical cinematic comic frame, expressive characters, clean composition, high detail",
                "do not override Agent consistency SOP with any single-shot custom setting",
            ]
        )
        negative_parts.extend(["low quality", "blurry", "watermark", "text artifacts", "bad anatomy"])
        prompt = ", ".join(part for part in (self._clean_prompt_part(part) for part in prompt_parts) if part)
        return prompt[:6000], ", ".join(part for part in negative_parts if part)

    def _select_character_cards(self, shot: dict, characters: list) -> list[dict]:
        selected_ids = {str(item) for item in shot.get("character_asset_ids", []) if item}
        selected_names = {str(item) for item in shot.get("characters_in_scene", []) if item}
        selected: list[dict] = []
        seen: set[str] = set()

        for char in characters:
            char_id = str(char.get("id") or "")
            char_name = str(char.get("name") or "")
            if selected_ids and char_id not in selected_ids:
                continue
            key = char_id or char_name
            if key and key not in seen:
                selected.append(char)
                seen.add(key)

        if selected:
            return selected

        for char in characters:
            char_name = str(char.get("name") or "")
            if selected_names and char_name not in selected_names:
                continue
            key = str(char.get("id") or char_name)
            if key and key not in seen:
                selected.append(char)
                seen.add(key)
        return selected

    def _reference_images_for_request(self, shot: dict) -> list[str]:
        refs: list[str] = []
        for asset in shot.get("reference_assets") or []:
            if not isinstance(asset, dict):
                continue
            path = asset.get("path")
            if path:
                refs.append(path)
        for key in ("scene_reference_images", "character_reference_images"):
            values = shot.get(key) or []
            if isinstance(values, str):
                values = [values]
            refs.extend(value for value in values if value)
        if shot.get("continuity_reference_path"):
            refs.append(shot["continuity_reference_path"])
        if shot.get("pose_reference_path"):
            refs.append(shot["pose_reference_path"])
        if shot.get("depth_reference_path"):
            refs.append(shot["depth_reference_path"])

        image_urls: list[str] = []
        seen: set[str] = set()
        for ref in refs:
            if ref in seen:
                continue
            seen.add(ref)
            image_url = self.reference_assets.to_image_url(ref)
            if image_url:
                image_urls.append(image_url)
            if len(image_urls) >= 8:
                break
        return image_urls

    def _clean_prompt_part(self, value) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        if "生成失败" in text or "Traceback" in text:
            return ""
        if "Seedance" in text and ("失败" in text or "failed" in text.lower() or "'id'" in text or '"id"' in text):
            return ""
        text = re.sub(r"[A-Za-z]:[\\/][^,，\\n]+", "", text)
        text = re.sub(r"(?:[A-Za-z]:)?[\\/][^,，\\n]*(?:output|projects|characters|shots|seedance)[^,，\\n]*", "", text)
        text = re.sub(r"output[\\/][^,，\\n]+", "", text)
        text = text.replace("{", "").replace("}", "")
        return " ".join(text.split())

    def _build_character_reference_prompt(self, character: dict, style: str) -> tuple[str, str]:
        appearance = character.get("appearance") if isinstance(character.get("appearance"), dict) else {}
        features = character.get("key_features") or []
        style_params = style_prompt_params(style)
        style_prompt = style_params.get("character_reference_prompt", "")
        prompt_parts = [
            style_prompt,
            "high-resolution original character asset, no thumbnail, production reference quality",
            "standard three-view reference sheet, front view, side view, back view",
            "same character identity across all views, neutral pose, full body, plain background",
            character.get("id", "") and f"unique character asset id: {character.get('id')}",
            character.get("name", ""),
            character.get("visual_prompt", ""),
            character.get("personality", ""),
            *[str(value) for value in appearance.values() if value],
            *[str(value) for value in features if value],
        ]
        negative_parts = [
            character.get("negative_prompt", ""),
            style_params.get("negative_prompt", ""),
            "different outfits between views, inconsistent face, extra characters, watermark, text artifacts, low quality",
        ]
        return ", ".join(part for part in prompt_parts if part), ", ".join(part for part in negative_parts if part)

    async def _call_stability(self, prompt: str, negative_prompt: str, seed: int) -> bytes:
        async with httpx.AsyncClient(timeout=45) as client:
            request = client.build_request(
                "POST",
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
            response = await client.send(request, stream=True)
            try:
                response.raise_for_status()
                data = await self._read_bounded_response(response)
                if len(data) > settings.MAX_IMAGE_GENERATION_BYTES:
                    raise RuntimeError("图像数据超过大小限制")
                return data
            finally:
                await response.aclose()

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

import asyncio
import base64  # noqa: F401  (kept for reference-asset data URLs)
import logging
import re
import time

from PIL import Image
from io import BytesIO

from config import settings
from services import usage_service
from services.consistency_service import ConsistencyService
from services.providers.base import ImageRequest
from services.providers.endpoint import EndpointConfig, get_endpoint
from services.providers.image_placeholder import PlaceholderImageAdapter
from services.providers.registry import UnknownProtocolError, get_adapter
from services.providers.usage import (
    CAPABILITY_IMAGE,
    ERROR_CODE_PROVIDER_CALL_FAILED,
    adapter_usage_for_request,
)
from services.reference_asset_service import ReferenceAssetService
from services.security import atomic_write_bytes, safe_path, validate_identifier
from services.storage_service import StorageQuotaExceeded, StorageService
from services.style_templates import style_prompt_params

logger = logging.getLogger(__name__)


class ImageService:
    """Image generation service routing to protocol adapters via endpoint config."""

    def __init__(self):
        self.output_dir = settings.OUTPUT_DIR / "projects"
        self.consistency = ConsistencyService()
        self.reference_assets = ReferenceAssetService()
        self.storage = StorageService()

    # ------------------------------------------------------------------
    # 适配器路由：protocol 显式决定代码路径；协议非法或缺 key 回退占位图。
    # ------------------------------------------------------------------

    def _resolve_route(self) -> tuple[object, EndpointConfig]:
        endpoint = get_endpoint("image")
        try:
            adapter_cls = get_adapter("image", endpoint.protocol)
        except UnknownProtocolError as exc:
            logger.warning("图像协议 %r 未注册适配器，回退占位图: %s", endpoint.protocol, exc)
            return PlaceholderImageAdapter(EndpointConfig(protocol="placeholder")), endpoint
        capabilities = adapter_cls.capabilities
        if capabilities.requires_credentials and not endpoint.api_key:
            logger.warning(
                "图像协议 %s 未配置 API Key，本次生成回退占位图（配置密钥后自动启用云端出图）",
                endpoint.protocol,
            )
            return PlaceholderImageAdapter(EndpointConfig(protocol="placeholder")), endpoint
        return adapter_cls(endpoint), endpoint

    async def _generate(
        self,
        *,
        prompt: str,
        negative_prompt: str,
        seed: int,
        reference_images: list[str],
        preferred_size: str,
        label: str,
        shot_id: str = "",
    ) -> bytes:
        adapter, endpoint = self._resolve_route()
        size = preferred_size or str(endpoint.param("image_size") or "")
        request = ImageRequest(
            prompt=prompt,
            negative_prompt=negative_prompt,
            seed=seed,
            # 适配器声明支持参考图时才传入，不再硬编码假设。
            reference_images=list(reference_images) if adapter.capabilities.reference_images else [],
            size=size,
            label=label,
        )
        # 用量按「实际调用的适配器」记账：回退到占位图时 provider 记为 placeholder，
        # 不会被误记成已配置但未真正调用的云端 provider。
        metadata = adapter_usage_for_request(adapter, CAPABILITY_IMAGE, request)
        scope = usage_service.current_scope().merged(shot_id=shot_id)
        started = time.monotonic()
        try:
            image_data = await adapter.generate(request)
        except asyncio.CancelledError:
            # 任务被取消：调用已经发出，同样要留痕（金额未知，不虚增）。
            usage_service.record_cancelled(
                metadata,
                duration_ms=int((time.monotonic() - started) * 1000),
                scope=scope,
            )
            raise
        except Exception:
            usage_service.record_failure(
                metadata,
                error_code=ERROR_CODE_PROVIDER_CALL_FAILED,
                duration_ms=int((time.monotonic() - started) * 1000),
                scope=scope,
            )
            raise
        if not image_data:
            usage_service.record_failure(
                metadata,
                error_code=ERROR_CODE_PROVIDER_CALL_FAILED,
                duration_ms=int((time.monotonic() - started) * 1000),
                scope=scope,
            )
            raise RuntimeError("图像生成接口未返回图片数据")
        usage_service.record_metadata(
            metadata,
            duration_ms=int((time.monotonic() - started) * 1000),
            scope=scope,
        )
        return image_data

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
        image_data = await self._generate(
            prompt=prompt,
            negative_prompt=negative_prompt,
            seed=seed,
            reference_images=reference_images,
            preferred_size=preferred_size,
            label="SHOT PLACEHOLDER",
            shot_id=safe_shot_id,
        )

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
        preferred_size = str(get_endpoint("image").param("image_size") or "1440x2560")

        image_data = await self._generate(
            prompt=prompt,
            negative_prompt=negative_prompt,
            seed=seed,
            reference_images=[],
            preferred_size=preferred_size,
            label="SCENE BASELINE",
        )

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

        image_data = await self._generate(
            prompt=prompt,
            negative_prompt=negative_prompt,
            seed=seed,
            reference_images=[],
            preferred_size=preferred_size,
            label="CHARACTER REF",
        )

        self._validate_image(image_data)
        self._write_image(project_id, image_path, image_data)
        return str(image_path)

    def _seedream_payload(self, model: str, prompt: str, negative_prompt: str, seed: int, size: str, reference_images: list[str] | None = None) -> dict:
        """兼容保留：sop 校验脚本使用。实际载荷由 ark-seedream 适配器构造。"""
        from services.providers.image_ark_seedream import ArkSeedreamImageAdapter

        request = ImageRequest(
            prompt=prompt,
            negative_prompt=negative_prompt,
            seed=seed,
            reference_images=list(reference_images or []),
            size=size,
        )
        return ArkSeedreamImageAdapter(EndpointConfig(protocol="ark-seedream"))._payload(model, request, size)

    def _size_for_ratio(self, output_format: str | None) -> str:
        # 画面比例 -> Seedream 出图尺寸。未识别的比例回退到配置的默认尺寸，
        # 保证用户在前端切换 9:16 / 16:9 / 1:1 等比例后，定稿故事板真实按比例出图。
        ratio = str(output_format or "").strip()
        ratio_size_map = {
            "9:16": "1440x2560",
            "3:4": "1536x2048",
            "1:1": "2048x2048",
            "4:3": "2048x1536",
            "16:9": "2560x1440",
        }
        return ratio_size_map.get(ratio, str(get_endpoint("image").param("image_size") or "1440x2560"))

    def build_shot_prompt(self, shot: dict, characters: list, style_params: dict) -> tuple[str, str]:
        return self._build_prompt(shot, characters, style_params)

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

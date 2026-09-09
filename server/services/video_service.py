"""视频生成服务：prompt/参考图/一致性策略 + 协议适配器路由。

端点来自 ``get_endpoint("video")``，协议调用委托给
``services.providers.registry.get_adapter("video", protocol)`` 注册的适配器：
- ``ark-seedance``：异步任务式无声视频（对白走独立 TTS 路径）；
- ``native-audio``：原生音视频骨架（对白编入 prompt，音频随视频直出）。
"""

import asyncio
import logging
import re
from pathlib import Path

from config import settings
from services.consistency_service import ConsistencyService
from services.providers.base import Dialogue, VideoRequest
from services.providers.endpoint import get_endpoint
from services.providers.registry import get_adapter
from services.reference_asset_service import ReferenceAssetService
from services.security import safe_path, validate_identifier
from services.style_templates import style_prompt_params

logger = logging.getLogger(__name__)


class VideoService:
    """按端点协议路由的视频生成服务（保留原 SeedanceVideoService 的策略逻辑）。"""

    def __init__(self):
        self.output_dir = settings.OUTPUT_DIR / "projects"
        self.consistency = ConsistencyService()
        self.reference_assets = ReferenceAssetService()

    # ------------------------------------------------------------------
    # 对外入口
    # ------------------------------------------------------------------

    async def generate_single_shot(
        self,
        prompt: str,
        project_id: str = "api_diagnostics",
        shot_id: str = "seedance_check",
        duration: int = 5,
        ratio: str = "9:16",
        resolution: str = "720p",
        content: list[dict] | None = None,
        dialogues: list[Dialogue] | None = None,
    ) -> dict[str, str]:
        endpoint = get_endpoint("video")
        adapter = get_adapter("video", endpoint.protocol)(endpoint)
        if not prompt.strip():
            raise RuntimeError("视频生成提示词为空")

        if content is None:
            content = [{"type": "text", "text": prompt}]
        reference_image, content_payload_mode = self._reference_from_content(content)

        try:
            safe_project_id = validate_identifier(project_id, "项目 ID")
            safe_shot_id = validate_identifier(shot_id, "镜头 ID")
        except ValueError as exc:
            raise RuntimeError(str(exc)) from exc
        output_dir = safe_path(self.output_dir, safe_project_id, "seedance", create_parent=True)
        video_path = output_dir / f"{safe_shot_id}.mp4"
        frame_path = output_dir / f"{safe_shot_id}_frame.png"

        fixed_duration = getattr(adapter.capabilities, "fixed_duration", None)
        request = VideoRequest(
            prompt=prompt,
            reference_image=reference_image,
            dialogues=dialogues,
            duration=int(fixed_duration or duration or 5),
            ratio=ratio,
            resolution=resolution,
            project_id=safe_project_id,
            output_video_path=video_path,
            output_frame_path=frame_path,
        )
        result = await adapter.generate(request)

        if result.native_audio:
            # 原生音频契约校验：不允许产出无声成品。
            await self._assert_stream_has_audio(result.video_path)

        return {
            "video_path": result.video_path,
            "frame_path": result.frame_path,
            "task_id": result.task_id,
            "reference_payload_mode": result.payload_mode or content_payload_mode,
            "native_audio": bool(result.native_audio),
        }

    async def generate_shot_video(
        self,
        shot: dict,
        characters: list[dict],
        scenes: dict[str, dict],
        project_id: str,
    ) -> dict[str, str]:
        endpoint = get_endpoint("video")
        adapter_cls = get_adapter("video", endpoint.protocol)
        capabilities = adapter_cls.capabilities

        reference_manifest: list[dict] = []
        if capabilities.reference_image:
            reference_manifest = self._validate_video_references(shot)
            shot["seedance_reference_manifest"] = reference_manifest
        prompt = self._build_prompt(shot, characters, scenes)
        content = self._build_content(prompt, shot)
        if capabilities.reference_image and not self._has_image_content(content):
            raise RuntimeError("视频生成缺少已审核分镜首帧参考图，已阻止纯文本生成")
        return await self.generate_single_shot(
            prompt=prompt,
            project_id=project_id,
            shot_id=shot.get("shot_id", "seedance_shot"),
            duration=int(shot.get("duration") or 5),
            ratio=shot.get("output_format", "9:16"),
            resolution=self._resolution(shot.get("resolution")),
            content=content,
            dialogues=self._dialogues_from_shot(shot),
        )

    # ------------------------------------------------------------------
    # 台词与参考图策略
    # ------------------------------------------------------------------

    @staticmethod
    def _dialogues_from_shot(shot: dict) -> list[Dialogue] | None:
        dialogues = shot.get("dialogues")
        if not dialogues:
            return None
        normalized: list[Dialogue] = []
        for item in dialogues:
            if isinstance(item, Dialogue):
                normalized.append(item)
            elif isinstance(item, dict):
                normalized.append(
                    Dialogue(
                        role=str(item.get("role") or ""),
                        text=str(item.get("text") or ""),
                        emotion=str(item.get("emotion") or "neutral"),
                    )
                )
        return normalized or None

    def _reference_from_content(self, content: list[dict]) -> tuple[str | None, str]:
        """从内容列表中取首帧参考图；payload 模式由适配器按内容判定。"""
        for item in content or []:
            if item.get("type") == "image_url":
                url = (item.get("image_url") or {}).get("url") if isinstance(item.get("image_url"), dict) else None
                return (url or None), ""
        return None, "text_only"

    def _resolution(self, resolution: str | None) -> str:
        # 项目分辨率可为 720p/1080p/2k/4k；Seedance 1.5 pro 仅支持到 1080p，
        # 因此 2k/4k 统一降级到 1080p，保证 API 不因不支持的档位报错。
        value = str(resolution or "").strip().lower()
        mapping = {
            "480p": "480p",
            "720p": "720p",
            "1080p": "1080p",
            "1080": "1080p",
            "2k": "1080p",
            "4k": "1080p",
        }
        return mapping.get(value, "720p")

    def _build_prompt(self, shot: dict, characters: list[dict], scenes: dict[str, dict]) -> str:
        scene = scenes.get(shot.get("scene_asset_id", "")) or {}
        selected_characters = self._select_character_cards(shot, characters)
        style_params = style_prompt_params(shot.get("style") or shot.get("style_id"))
        parts = [
            "NON-NEGOTIABLE AGENT CONSISTENCY SOP overrides any single-shot custom prompt",
            style_params.get("video_prompt", ""),
            f"locked visual style preset: {style_params.get('style_label', '')}",
            "vertical cinematic short drama video, coherent motion, no subtitles, no watermark",
            "match the approved storyboard keyframe exactly for character identity, costume, scene palette and composition",
            "use loaded scene baseline, character references, and previous final-frame continuity reference when available",
            scene.get("visual_prompt", ""),
            scene.get("description", ""),
            scene.get("prop_lock", ""),
            shot.get("storyboard_prompt", ""),
            shot.get("visual_notes", ""),
            shot.get("scene_description", ""),
            shot.get("character_action", ""),
            shot.get("skill_prompt_append", ""),
            shot.get("shot_type", ""),
            shot.get("camera_angle", ""),
        ]
        if shot.get("storyboard_path") or shot.get("image_path"):
            parts.append(
                "Attached reference image order: image 1 is the approved storyboard keyframe and must anchor the first composition, pose, costume and palette."
            )
        if shot.get("continuity_reference_path"):
            parts.append("previous shot final frame must anchor eye-line, action carry-over, 180-degree axis, depth and pose continuity")
        if shot.get("reference_weights"):
            weights = shot.get("reference_weights") or {}
            parts.append(
                f"locked reference weights: environment/style {float(weights.get('environment') or 0.45):.2f}, character/action {float(weights.get('action') or 0.30):.2f}"
            )
        if shot.get("reference_assets"):
            roles = ", ".join(str(item.get("role", "")) for item in shot.get("reference_assets", []) if isinstance(item, dict))
            parts.append(f"mandatory persisted reference assets drive these roles: {roles}")
        if shot.get("seedance_reference_manifest"):
            manifest = shot.get("seedance_reference_manifest") or []
            loaded = ", ".join(str(item.get("type", "")) for item in manifest if isinstance(item, dict))
            parts.append(
                "Seedance 1.5 pro API-safe reference mode: the approved storyboard is attached as first_frame; "
                f"the following persisted assets were loaded and locked into this prompt before video generation: {loaded}"
            )
        if shot.get("continuity_profile"):
            profile = shot.get("continuity_profile") or {}
            parts.append(
                "locked continuity controls: "
                f"{', '.join(profile.get('editing_logic', []))}; "
                f"OpenPose {profile.get('openpose_lock', 'not_required')}; "
                f"Depth {profile.get('depth_lock', 'not_required')}; "
                f"same-scene transition {profile.get('same_scene_transition', 'hard cut or 0.2s fade')}; "
                f"LUT {profile.get('lut', 'project_scene_lut_locked')}; "
                f"{profile.get('ambient_audio_policy', '')}"
            )
            blocking = profile.get("character_blocking") or {}
            if blocking:
                order = blocking.get("character_order_left_to_right") or []
                parts.append(
                    "locked character blocking: "
                    f"left-to-right order {', '.join(order) if order else 'single subject'}; "
                    f"{blocking.get('axis_line', '180-degree axis locked')}; "
                    f"eye-line {blocking.get('eye_line_target', 'locked')}; "
                    f"{blocking.get('camera_movement_limit', '')}; "
                    f"{blocking.get('skin_light_integration', '')}"
                )
        if shot.get("consistency_context"):
            parts.append(shot["consistency_context"])
        for char in selected_characters:
            appearance = char.get("appearance") or {}
            appearance_parts = [str(value) for value in appearance.values()] if isinstance(appearance, dict) else []
            reference_lock = "preserve approved three-view character sheet identity" if char.get("reference_images") else ""
            parts.extend(
                [
                    char.get("visual_prompt", ""),
                    ", ".join(char.get("key_features", [])),
                    *appearance_parts,
                    reference_lock,
                    char.get("lora_profile", ""),
                    char.get("ip_adapter_profile", ""),
                    char.get("wardrobe_lock", ""),
                ]
            )
        prompt = ", ".join(part for part in (self._clean_prompt_part(part) for part in parts) if part)
        return prompt[:6000]

    def _select_character_cards(self, shot: dict, characters: list[dict]) -> list[dict]:
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

    def _build_content(self, prompt: str, shot: dict) -> list[dict]:
        content: list[dict] = [{"type": "text", "text": prompt}]

        first_frame = shot.get("storyboard_path") or shot.get("image_path") or ""
        first_frame_url = self.reference_assets.to_image_url(first_frame)
        if first_frame_url:
            content.append({"type": "image_url", "image_url": {"url": first_frame_url}, "role": "first_frame"})
        return content

    def _has_image_content(self, content: list[dict]) -> bool:
        return any(item.get("type") == "image_url" for item in content)

    def _reference_payload_mode(self, content: list[dict]) -> str:
        roles = {str(item.get("role") or "") for item in content if item.get("type") == "image_url"}
        if "first_frame" in roles:
            return "first_frame_reference"
        if roles:
            return "image_reference"
        return "text_only"

    def _validate_video_references(self, shot: dict) -> list[dict]:
        missing: list[str] = []
        manifest: list[dict] = []
        seen: set[tuple[str, str]] = set()

        def add_reference(kind: str, path: str, required: bool = True) -> None:
            value = str(path or "").strip()
            key = (kind, value)
            if key in seen:
                return
            seen.add(key)
            image_url = self.reference_assets.to_image_url(value)
            if image_url:
                manifest.append({"type": kind, "path": value, "loaded": True})
            elif required:
                missing.append(f"{kind}:{value or '<empty>'}")

        add_reference("approved_storyboard_first_frame", shot.get("storyboard_path") or shot.get("image_path") or "")
        for asset in self._ordered_reference_assets(shot):
            add_reference(str(asset.get("type") or "reference_asset"), str(asset.get("path") or ""), bool(asset.get("required", True)))

        profile = shot.get("continuity_profile") or {}
        if profile.get("openpose_lock") == "enabled":
            add_reference("openpose_control", shot.get("pose_reference_path", ""))
        if profile.get("depth_lock") == "enabled":
            add_reference("depth_control", shot.get("depth_reference_path", ""))

        if missing:
            raise RuntimeError("视频生成缺少必需一致性参考素材: " + " | ".join(missing))
        return manifest

    def _ordered_reference_assets(self, shot: dict) -> list[dict]:
        assets: list[dict] = [asset for asset in (shot.get("reference_assets") or []) if isinstance(asset, dict)]
        if shot.get("continuity_reference_path"):
            assets.append(
                {
                    "type": "continuity_frame",
                    "path": shot["continuity_reference_path"],
                    "weight": (shot.get("reference_weights") or {}).get("action", 0.30),
                }
            )
        if shot.get("pose_reference_path"):
            assets.append({"type": "openpose_source_frame", "path": shot["pose_reference_path"], "weight": (shot.get("reference_weights") or {}).get("action", 0.30)})
        if shot.get("depth_reference_path"):
            assets.append({"type": "depth_source_frame", "path": shot["depth_reference_path"], "weight": (shot.get("reference_weights") or {}).get("environment", 0.45)})

        priority = {
            "scene_baseline": 0,
            "character_three_view": 1,
            "continuity_frame": 2,
            "openpose_source_frame": 3,
            "depth_source_frame": 4,
        }
        return sorted(assets, key=lambda item: priority.get(str(item.get("type")), 9))

    async def _assert_stream_has_audio(self, video_path: str) -> None:
        """ffprobe 校验原生音频视频确有音轨（两条路径输出契约一致性）。"""
        proc = await asyncio.create_subprocess_exec(
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "stream=codec_type",
            "-of",
            "json",
            str(video_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"校验视频音轨失败: {stderr.decode('utf-8', errors='ignore')[-500:]}")
        if '"audio"' not in stdout.decode("utf-8", errors="ignore"):
            raise RuntimeError("原生音频视频未包含音轨，已阻止无声成品进入成片流程")


# 兼容旧导入名（api_diagnostics / sop 脚本 / 测试）。
SeedanceVideoService = VideoService

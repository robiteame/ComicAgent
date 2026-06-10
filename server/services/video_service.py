import asyncio
import base64
import re
from pathlib import Path

import httpx

from config import settings
from services.consistency_service import ConsistencyService
from services.reference_asset_service import ReferenceAssetService
from services.style_templates import style_prompt_params


class SeedanceVideoService:
    """Minimal Seedance client for one-shot connectivity checks."""

    def __init__(self):
        self.output_dir = settings.OUTPUT_DIR / "projects"
        self.consistency = ConsistencyService()
        self.reference_assets = ReferenceAssetService()

    # 运行时实时读取 settings，保证保存模型/API 配置后新任务即生效。
    @property
    def api_key(self) -> str:
        return settings.SEEDDANCE_API_KEY or settings.ARK_API_KEY or settings.SEEDREAM_API_KEY

    @property
    def base_url(self) -> str:
        return self._normalize_base_url(settings.SEEDDANCE_BASE_URL)

    @property
    def model(self) -> str:
        return settings.SEEDDANCE_MODEL or "doubao-seedance-1-5-pro-251215"

    async def generate_single_shot(
        self,
        prompt: str,
        project_id: str = "api_diagnostics",
        shot_id: str = "seedance_check",
        duration: int = 5,
        ratio: str = "9:16",
        resolution: str = "720p",
        content: list[dict] | None = None,
    ) -> dict[str, str]:
        if not self.api_key:
            raise RuntimeError("未配置 Seedance/Ark API Key，无法调用 Seedance")
        if not prompt.strip():
            raise RuntimeError("Seedance 提示词为空")

        output_dir = self.output_dir / project_id / "seedance"
        output_dir.mkdir(parents=True, exist_ok=True)
        task, payload_mode = await self._create_task(prompt, duration, ratio, resolution, content)
        task_id = self._extract_task_id(task)
        result = await self._wait_for_task(task_id)
        video_bytes, frame_bytes = await self._download_outputs(result)

        video_path = output_dir / f"{shot_id}.mp4"
        frame_path = output_dir / f"{shot_id}_frame.png"
        video_path.write_bytes(video_bytes)
        if frame_bytes:
            frame_path.write_bytes(frame_bytes)
        else:
            await self._extract_last_frame(video_path, frame_path)

        if video_path.stat().st_size <= 4096:
            raise RuntimeError("Seedance 返回视频为空或过小")
        if not frame_path.exists() or frame_path.stat().st_size <= 1024:
            raise RuntimeError("Seedance 单帧画面保存失败")
        return {"video_path": str(video_path), "frame_path": str(frame_path), "task_id": task_id, "reference_payload_mode": payload_mode}

    async def generate_shot_video(
        self,
        shot: dict,
        characters: list[dict],
        scenes: dict[str, dict],
        project_id: str,
    ) -> dict[str, str]:
        reference_manifest = self._validate_video_references(shot)
        shot["seedance_reference_manifest"] = reference_manifest
        prompt = self._build_prompt(shot, characters, scenes)
        content = self._build_content(prompt, shot)
        if not self._has_image_content(content):
            raise RuntimeError("Seedance 视频生成缺少已审核分镜首帧参考图，已阻止纯文本生成")
        return await self.generate_single_shot(
            prompt=prompt,
            project_id=project_id,
            shot_id=shot.get("shot_id", "seedance_shot"),
            duration=self._duration_for_model(),
            ratio=shot.get("output_format", "9:16"),
            resolution=self._seedance_resolution(shot.get("resolution")),
            content=content,
        )

    def _seedance_resolution(self, resolution: str | None) -> str:
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

    def _duration_for_model(self) -> int:
        # Seedance pro t2v rejects arbitrary shot durations. Keep generation at
        # the verified API-safe duration; ffmpeg still uses the shot duration
        # later when normalizing and composing clips.
        return 5

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
            raise RuntimeError("Seedance 视频生成缺少必需一致性参考素材: " + " | ".join(missing))
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

    async def _create_task(self, prompt: str, duration: int, ratio: str, resolution: str, content: list[dict] | None = None) -> tuple[dict, str]:
        request_content = content or [{"type": "text", "text": prompt}]
        payload = {
            "model": self.model,
            "content": request_content,
            "duration": duration,
            "ratio": ratio,
            "resolution": resolution,
            "return_last_frame": True,
            "watermark": False,
        }
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(self._tasks_url(), headers=self._headers(), json=payload)
            payload_mode = self._reference_payload_mode(request_content)
        if response.status_code >= 400:
            raise RuntimeError(f"Seedance 创建任务失败: {response.status_code} {response.text[:1000]}")
        return response.json(), payload_mode

    def _has_image_content(self, content: list[dict]) -> bool:
        return any(item.get("type") == "image_url" for item in content)

    def _reference_payload_mode(self, content: list[dict]) -> str:
        roles = {str(item.get("role") or "") for item in content if item.get("type") == "image_url"}
        if "first_frame" in roles:
            return "first_frame_reference"
        if roles:
            return "image_reference"
        return "text_only"

    async def _wait_for_task(self, task_id: str) -> dict:
        async with httpx.AsyncClient(timeout=60) as client:
            for _ in range(90):
                response = await client.get(f"{self._tasks_url()}/{task_id}", headers=self._headers())
                if response.status_code >= 400:
                    raise RuntimeError(f"Seedance 查询任务失败: {response.status_code} {response.text[:1000]}")
                data = response.json()
                status = str(data.get("status") or data.get("task_status") or data.get("data", {}).get("status") or "").lower()
                if status in {"succeeded", "success", "completed", "done"}:
                    return data
                if status in {"failed", "cancelled", "canceled", "error"}:
                    raise RuntimeError(f"Seedance 任务失败: {data}")
                await asyncio.sleep(5)
        raise TimeoutError(f"Seedance 任务超时: {task_id}")

    async def _download_outputs(self, data: dict) -> tuple[bytes, bytes | None]:
        video_url = self._find_url(data, {"video_url", "video", "url"})
        frame_url = self._find_url(data, {"last_frame_url", "frame_url", "image_url", "cover_url"})
        video_b64 = self._find_b64(data, {"video_base64", "video_b64", "b64_json"})
        frame_b64 = self._find_b64(data, {"last_frame_base64", "frame_base64", "image_base64"})

        if video_b64:
            video_bytes = base64.b64decode(video_b64)
        elif video_url:
            video_bytes = await self._download_url(video_url)
        else:
            raise RuntimeError(f"Seedance 返回缺少视频 URL/base64: {data}")

        frame_bytes = None
        if frame_b64:
            frame_bytes = base64.b64decode(frame_b64)
        elif frame_url:
            frame_bytes = await self._download_url(frame_url)
        return video_bytes, frame_bytes

    async def _download_url(self, url: str) -> bytes:
        async with httpx.AsyncClient(timeout=180, follow_redirects=True) as client:
            response = await client.get(url)
        response.raise_for_status()
        return response.content

    async def _extract_last_frame(self, video_path: Path, frame_path: Path) -> None:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-y",
            "-sseof",
            "-0.1",
            "-i",
            str(video_path),
            "-frames:v",
            "1",
            str(frame_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"提取 Seedance 单帧失败: {stderr.decode('utf-8', errors='ignore')[-1000:]}")

    def _extract_task_id(self, data: dict) -> str:
        for key in ("id", "task_id"):
            value = data.get(key) or data.get("data", {}).get(key)
            if value:
                return str(value)
        raise RuntimeError(f"Seedance 创建任务返回缺少任务 ID: {data}")

    def _find_url(self, value, keys: set[str]) -> str:
        if isinstance(value, dict):
            for key, item in value.items():
                if key in keys and isinstance(item, str) and item.startswith(("http://", "https://")):
                    return item
                nested = self._find_url(item, keys)
                if nested:
                    return nested
        if isinstance(value, list):
            for item in value:
                nested = self._find_url(item, keys)
                if nested:
                    return nested
        return ""

    def _find_b64(self, value, keys: set[str]) -> str:
        if isinstance(value, dict):
            for key, item in value.items():
                if key in keys and isinstance(item, str) and not item.startswith(("http://", "https://")):
                    return item.split(",", 1)[-1] if item.startswith("data:") else item
                nested = self._find_b64(item, keys)
                if nested:
                    return nested
        if isinstance(value, list):
            for item in value:
                nested = self._find_b64(item, keys)
                if nested:
                    return nested
        return ""

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    def _tasks_url(self) -> str:
        return f"{self.base_url}/contents/generations/tasks"

    def _normalize_base_url(self, value: str) -> str:
        base = (value or "https://ark.cn-beijing.volces.com/api/v3").rstrip("/")
        return base.replace("/api/plan/v3", "/api/v3")

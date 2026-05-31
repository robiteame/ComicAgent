import asyncio
import base64
from pathlib import Path

import httpx

from config import settings


class SeedanceVideoService:
    """Minimal Seedance client for one-shot connectivity checks."""

    def __init__(self):
        self.api_key = settings.SEEDDANCE_API_KEY or settings.ARK_API_KEY or settings.SEEDREAM_API_KEY
        self.base_url = self._normalize_base_url(settings.SEEDDANCE_BASE_URL)
        self.model = settings.SEEDDANCE_MODEL or "doubao-seedance-1-5-pro-251215"
        self.output_dir = settings.OUTPUT_DIR / "projects"

    async def generate_single_shot(
        self,
        prompt: str,
        project_id: str = "api_diagnostics",
        shot_id: str = "seedance_check",
        duration: int = 5,
        ratio: str = "9:16",
        resolution: str = "720p",
    ) -> dict[str, str]:
        if not self.api_key:
            raise RuntimeError("未配置 Seedance/Ark API Key，无法调用 Seedance")
        if not prompt.strip():
            raise RuntimeError("Seedance 提示词为空")

        output_dir = self.output_dir / project_id / "seedance"
        output_dir.mkdir(parents=True, exist_ok=True)
        task = await self._create_task(prompt, duration, ratio, resolution)
        task_id = self._extract_task_id(task)
        result = await self._wait_for_task(task_id)
        video_bytes, frame_bytes = await self._download_outputs(result)

        video_path = output_dir / f"{shot_id}.mp4"
        frame_path = output_dir / f"{shot_id}_frame.png"
        video_path.write_bytes(video_bytes)
        if frame_bytes:
            frame_path.write_bytes(frame_bytes)
        else:
            await self._extract_first_frame(video_path, frame_path)

        if video_path.stat().st_size <= 4096:
            raise RuntimeError("Seedance 返回视频为空或过小")
        if not frame_path.exists() or frame_path.stat().st_size <= 1024:
            raise RuntimeError("Seedance 单帧画面保存失败")
        return {"video_path": str(video_path), "frame_path": str(frame_path), "task_id": task_id}

    async def generate_shot_video(
        self,
        shot: dict,
        characters: list[dict],
        scenes: dict[str, dict],
        project_id: str,
    ) -> dict[str, str]:
        return await self.generate_single_shot(
            prompt=self._build_prompt(shot, characters, scenes),
            project_id=project_id,
            shot_id=shot.get("shot_id", "seedance_shot"),
            duration=self._duration_for_model(),
            ratio=shot.get("output_format", "9:16"),
            resolution="720p",
        )

    def _duration_for_model(self) -> int:
        # Seedance pro t2v rejects arbitrary shot durations. Keep generation at
        # the verified API-safe duration; ffmpeg still uses the shot duration
        # later when normalizing and composing clips.
        return 5

    def _build_prompt(self, shot: dict, characters: list[dict], scenes: dict[str, dict]) -> str:
        scene = scenes.get(shot.get("scene_asset_id", "")) or {}
        selected_character_ids = set(shot.get("character_asset_ids") or [])
        selected_characters = [
            item for item in characters if not selected_character_ids or item.get("id") in selected_character_ids
        ]
        parts = [
            "vertical cinematic anime short video, coherent motion, no subtitles, no watermark",
            scene.get("visual_prompt", ""),
            scene.get("description", ""),
            shot.get("scene_description", ""),
            shot.get("character_action", ""),
            shot.get("shot_type", ""),
            shot.get("camera_angle", ""),
        ]
        for char in selected_characters:
            parts.extend([char.get("visual_prompt", ""), ", ".join(char.get("key_features", []))])
        return ", ".join(part for part in parts if part)

    async def _create_task(self, prompt: str, duration: int, ratio: str, resolution: str) -> dict:
        payload = {
            "model": self.model,
            "content": [{"type": "text", "text": prompt}],
            "duration": duration,
            "ratio": ratio,
            "resolution": resolution,
            "return_last_frame": True,
            "watermark": False,
        }
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(self._tasks_url(), headers=self._headers(), json=payload)
        if response.status_code >= 400:
            raise RuntimeError(f"Seedance 创建任务失败: {response.status_code} {response.text[:1000]}")
        return response.json()

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

    async def _extract_first_frame(self, video_path: Path, frame_path: Path) -> None:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-y",
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

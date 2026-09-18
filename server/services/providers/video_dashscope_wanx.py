"""阿里云百炼（DashScope）通义万相视频适配器。

异步任务式：``X-DashScope-Async`` 创建任务 → 轮询 ``/tasks/{id}`` → 下载视频
+ FFmpeg 提取尾帧。产物为无声视频（对白由独立的 TTS 路径配音），
capabilities.native_audio=False 供音频路由识别。图生视频模型（wan*-i2v-*）以
``input.img_url`` 首帧参考图驱动，文生视频模型（wan*-t2v-*）纯文本驱动。
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx

from config import settings
from services.providers.base import BaseAdapter, VideoCapabilities, VideoRequest, VideoResult
from services.providers.usage import CAPABILITY_VIDEO, UsageMetadata
from services.security import (
    UploadLimitExceeded,
    download_remote_file,
)
from services.storage_service import StorageQuotaExceeded, StorageService

_DEFAULT_BASE = "https://dashscope.aliyuncs.com/api/v1"

# 各画幅的 720P 基准尺寸（宽, 高）；1080P 及以上按 1.5 倍放大（720→1080）。
_RATIO_BASE_SIZES: dict[str, tuple[int, int]] = {
    "9:16": (720, 1280),
    "16:9": (1280, 720),
    "1:1": (960, 960),
    "3:4": (720, 960),
    "4:3": (960, 720),
    "2:3": (720, 1080),
    "3:2": (1080, 720),
}


class DashscopeWanxVideoAdapter(BaseAdapter):
    capabilities = VideoCapabilities(
        reference_image=True,
        native_audio=False,
        dialogue_in_prompt=False,
        voice_consistent=False,
        fixed_duration=None,
    )

    def __init__(self, endpoint):
        super().__init__(endpoint)
        self.storage = StorageService()

    def usage_for_request(
        self,
        capability: str,
        request: VideoRequest | None = None,
        *,
        model: str = "",
    ) -> UsageMetadata:
        """万相按秒计费：时长取请求里的有效时长（服务层已按模型能力归一化）。"""

        return UsageMetadata(
            capability=CAPABILITY_VIDEO,
            provider=self.endpoint.protocol,
            model=model or self.endpoint.model,
            seconds=float(getattr(request, "duration", 0) or 0),
            resolution=str(getattr(request, "resolution", "") or ""),
            known=True,
            billable=True,
            source="request",
            extra={"ratio": str(getattr(request, "ratio", "") or "")},
        )

    async def generate(self, request: VideoRequest) -> VideoResult:
        payload_mode = "first_frame_reference" if request.reference_image else "text_only"

        task_id = await self._create_task(request)
        data = await self._wait_for_task(task_id)
        video_url = str((data.get("output") or {}).get("video_url") or "")
        if not video_url.startswith(("http://", "https://")):
            raise RuntimeError(f"百炼返回缺少视频 URL: {data}")

        video_path = request.output_video_path
        frame_path = request.output_frame_path
        await self._download_url_to_path(request.project_id, video_url, video_path, minimum_size=4096)
        await self._extract_last_frame(video_path, frame_path)

        if video_path.stat().st_size <= 4096:
            raise RuntimeError("百炼返回视频为空或过小")
        if not frame_path.exists() or frame_path.stat().st_size <= 1024:
            raise RuntimeError("百炼单帧画面保存失败")
        return VideoResult(
            video_path=str(video_path),
            frame_path=str(frame_path),
            native_audio=False,
            payload_mode=payload_mode,
            task_id=task_id,
        )

    # --- 异步任务协议 ---

    async def _create_task(self, request: VideoRequest) -> str:
        task_input: dict[str, str] = {"prompt": request.prompt}
        if request.reference_image:
            task_input["img_url"] = request.reference_image
        payload = {
            "model": self.endpoint.model,
            "input": task_input,
            "parameters": {
                "size": self._resolve_size(request.ratio, request.resolution),
                "duration": max(1, int(request.duration or 5)),
                "prompt_extend": True,
            },
        }
        headers = self._headers()
        headers["X-DashScope-Async"] = "enable"
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(self._create_url(), headers=headers, json=payload)
        if response.status_code >= 400:
            raise RuntimeError(f"百炼创建视频任务失败: {response.status_code} {response.text[:1000]}")
        data = response.json()
        task_id = str((data.get("output") or {}).get("task_id") or "")
        if not task_id:
            raise RuntimeError(f"百炼创建任务返回缺少任务 ID: {data}")
        return task_id

    async def _wait_for_task(self, task_id: str) -> dict:
        async with httpx.AsyncClient(timeout=60) as client:
            for _ in range(90):
                response = await client.get(f"{self._api_base()}/tasks/{task_id}", headers=self._headers())
                if response.status_code >= 400:
                    raise RuntimeError(f"百炼查询视频任务失败: {response.status_code} {response.text[:1000]}")
                data = response.json()
                status = str((data.get("output") or {}).get("task_status") or "").upper()
                if status == "SUCCEEDED":
                    return data
                if status in {"FAILED", "CANCELED", "UNKNOWN"}:
                    raise RuntimeError(f"百炼视频任务失败: {data}")
                await asyncio.sleep(5)
        raise TimeoutError(f"百炼视频任务超时: {task_id}")

    def _resolve_size(self, ratio: str, resolution: str) -> str:
        width, height = _RATIO_BASE_SIZES.get(str(ratio or "9:16"), (720, 1280))
        if str(resolution or "").lower() in {"1080p", "1080", "2k", "4k"}:
            width, height = round(width * 1.5), round(height * 1.5)
        return f"{width}*{height}"

    # --- 产物下载与落盘 ---

    async def _download_url_to_path(self, project_id: str, url: str, destination: Path, *, minimum_size: int) -> None:
        try:
            available = self.storage.ensure_project_capacity(project_id, replacing=destination)
            size = await download_remote_file(
                url,
                destination,
                max_bytes=min(settings.MAX_REMOTE_MEDIA_BYTES, available),
                timeout=180,
            )
        except (StorageQuotaExceeded, UploadLimitExceeded, ValueError, httpx.HTTPError) as exc:
            raise RuntimeError(f"下载远程媒体失败: {exc}") from exc
        if size < minimum_size:
            destination.unlink(missing_ok=True)
            raise RuntimeError("下载的远程媒体为空或过小")

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
        try:
            _, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=max(30, int(settings.FFMPEG_TIMEOUT_SECONDS)),
            )
        except asyncio.CancelledError:
            if proc.returncode is None:
                proc.kill()
            await proc.communicate()
            raise
        except asyncio.TimeoutError as exc:
            proc.kill()
            await proc.communicate()
            raise TimeoutError("提取百炼单帧超时") from exc
        if proc.returncode != 0:
            raise RuntimeError(f"提取百炼单帧失败: {stderr.decode('utf-8', errors='ignore')[-1000:]}")

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.endpoint.api_key}", "Content-Type": "application/json"}

    def _api_base(self) -> str:
        base = (self.endpoint.base_url or _DEFAULT_BASE).rstrip("/")
        if not base.endswith("/api/v1"):
            base = f"{base}/api/v1"
        return base

    def _create_url(self) -> str:
        return f"{self._api_base()}/services/aigc/video-generation/video-synthesis"

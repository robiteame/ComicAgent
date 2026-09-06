import asyncio
import hashlib
import os
import shutil
import uuid
from pathlib import Path

from config import settings
from services.security import existing_file, safe_path, validate_identifier
from services.storage_service import StorageQuotaExceeded, StorageService


class FFmpegService:
    """Render shot images and optional audio into a short MP4."""

    def __init__(self):
        self.output_dir = settings.OUTPUT_DIR / "projects"
        self.fps = settings.DEFAULT_FPS
        self.storage = StorageService()

    async def compose_video(
        self,
        shots: list[dict],
        output_format: str = "9:16",
        resolution: str = "1080p",
        project_id: str = "",
        publish: bool = True,
    ) -> str:
        try:
            safe_project_id = validate_identifier(project_id, "项目 ID")
        except ValueError as exc:
            raise ValueError(str(exc)) from exc
        video_dir = safe_path(self.output_dir, safe_project_id, "output", create_parent=True)
        try:
            self.storage.ensure_project_capacity(safe_project_id, settings.FFMPEG_WORKSPACE_RESERVE_BYTES)
        except StorageQuotaExceeded as exc:
            raise RuntimeError("项目媒体存储空间不足，无法开始渲染") from exc
        work_dir = video_dir / f".render-{uuid.uuid4().hex}"
        work_dir.mkdir(parents=True, exist_ok=False)
        width, height = self._get_resolution(resolution, output_format)

        try:
            clip_paths: list[Path] = []
            media_roots = (settings.OUTPUT_DIR, settings.ASSETS_DIR, settings.DATA_DIR)
            for index, shot in enumerate(shots):
                if shot.get("video_path"):
                    if existing_file(shot["video_path"], minimum_size=4096, allowed_roots=media_roots) is None:
                        raise ValueError(f"镜头视频文件不存在或无效: {shot.get('shot_id', index)}")
                    clip_paths.append(await self._normalize_video_clip(shot, width, height, index, work_dir))
                    continue
                if not shot.get("image_path"):
                    continue
                if existing_file(shot["image_path"], minimum_size=1, allowed_roots=media_roots) is None:
                    raise ValueError(f"镜头图片文件不存在或无效: {shot.get('shot_id', index)}")
                clip_paths.append(await self._render_shot_clip(shot, width, height, index, work_dir))

            if not clip_paths:
                raise ValueError("没有可渲染的镜头图片")

            rendered = await self._concat_clips(clip_paths, work_dir)
            rendered = await self._add_continuous_ambient_bed(rendered, work_dir)
            final_path = video_dir / ("final.mp4" if publish else f".final-{uuid.uuid4().hex}.candidate")
            os.replace(rendered, final_path)
            if not final_path.exists() or final_path.stat().st_size <= 1024:
                raise RuntimeError("FFmpeg 未生成有效的成片文件")
            return str(final_path)
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)

    async def _render_shot_clip(self, shot: dict, width: int, height: int, index: int, output_dir: Path) -> Path:
        clip_path = output_dir / f"clip_{index:04d}.mp4"
        duration = max(0.5, float(shot.get("duration") or 3.0))
        frames = max(1, int(duration * self.fps))
        image_obj = self._media_path(shot.get("image_path"), minimum_size=1)
        if image_obj is None:
            raise ValueError("镜头图片文件不存在或无效")
        image_path = str(image_obj)
        video_filter = self._clip_filter(
            self._zoom_filter(shot.get("shot_type", "medium"), width, height, frames),
            shot,
            duration,
        )

        audio_path = self._media_path(shot.get("audio_path"), minimum_size=1)
        if audio_path:
            audio_input = ["-i", str(audio_path)]
            audio_filter = ["-af", f"apad=pad_dur={duration}"]
        else:
            audio_input = ["-f", "lavfi", "-t", str(duration), "-i", "anullsrc=channel_layout=stereo:sample_rate=44100"]
            audio_filter = []

        await self._run(
            [
                "ffmpeg",
                "-y",
                "-loop",
                "1",
                "-i",
                image_path,
                *audio_input,
                "-vf",
                video_filter,
                "-t",
                str(duration),
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                *audio_filter,
                "-shortest",
                str(clip_path),
            ]
        )
        return clip_path

    async def _normalize_video_clip(self, shot: dict, width: int, height: int, index: int, output_dir: Path) -> Path:
        clip_path = output_dir / f"clip_{index:04d}.mp4"
        duration = max(0.5, float(shot.get("duration") or 3.0))
        video_path_obj = self._media_path(shot.get("video_path"), minimum_size=4096)
        if video_path_obj is None:
            raise ValueError("镜头视频文件不存在或无效")
        video_path = str(video_path_obj)
        audio_path = self._media_path(shot.get("audio_path"), minimum_size=1)
        if audio_path:
            audio_input = ["-i", str(audio_path)]
            map_audio = ["-map", "1:a:0"]
            audio_codec = ["-c:a", "aac", "-af", f"apad=pad_dur={duration}"]
        else:
            audio_input = ["-f", "lavfi", "-t", str(duration), "-i", "anullsrc=channel_layout=stereo:sample_rate=44100"]
            map_audio = ["-map", "1:a:0"]
            audio_codec = ["-c:a", "aac"]

        await self._run(
            [
                "ffmpeg",
                "-y",
                "-i",
                video_path,
                *audio_input,
                "-vf",
                self._clip_filter(f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height}", shot, duration),
                "-t",
                str(duration),
                "-map",
                "0:v:0",
                *map_audio,
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                *audio_codec,
                "-shortest",
                str(clip_path),
            ]
        )
        return clip_path

    async def _concat_clips(self, clip_paths: list[Path], output_dir: Path) -> Path:
        concat_path = output_dir / "final.mp4"
        inputs: list[str] = []
        for path in clip_paths:
            inputs.extend(["-i", str(path)])

        audio_filters = []
        concat_inputs = []
        for index in range(len(clip_paths)):
            audio_filters.append(f"[{index}:a:0]aresample=44100,aformat=channel_layouts=stereo[a{index}]")
            concat_inputs.append(f"[{index}:v:0][a{index}]")

        filter_complex = ";".join(audio_filters)
        filter_complex += ";" + "".join(concat_inputs)
        filter_complex += f"concat=n={len(clip_paths)}:v=1:a=1[v][a]"
        await self._run(
            [
                "ffmpeg",
                "-y",
                *inputs,
                "-filter_complex",
                filter_complex,
                "-map",
                "[v]",
                "-map",
                "[a]",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-movflags",
                "+faststart",
                str(concat_path),
            ]
        )
        return concat_path

    async def _add_continuous_ambient_bed(self, video_path: Path, output_dir: Path) -> Path:
        mixed_path = output_dir / "final_with_ambient.mp4"
        await self._run(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(video_path),
                "-f",
                "lavfi",
                "-i",
                "anoisesrc=color=pink:amplitude=0.008:sample_rate=44100",
                "-filter_complex",
                "[0:a:0]aresample=44100,aformat=channel_layouts=stereo[a0];[1:a:0]volume=0.08[amb];[a0][amb]amix=inputs=2:duration=first:dropout_transition=0[a]",
                "-map",
                "0:v:0",
                "-map",
                "[a]",
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                "-shortest",
                "-movflags",
                "+faststart",
                str(mixed_path),
            ]
        )
        mixed_path.replace(video_path)
        return video_path

    def _zoom_filter(self, shot_type: str, width: int, height: int, frames: int) -> str:
        if shot_type == "wide":
            zoom = "min(zoom+0.001,1.25)"
        elif shot_type in {"close-up", "extreme_close"}:
            zoom = "1.35"
        else:
            zoom = "1.10"
        return (
            f"scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},"
            f"zoompan=z='{zoom}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
            f"d={frames}:s={width}x{height}:fps={self.fps}"
        )

    def _clip_filter(self, base_filter: str, shot: dict, duration: float) -> str:
        filters = [base_filter, self._post_filter(shot)]
        profile = shot.get("post_profile") or {}
        transition_duration = self._cross_scene_transition_duration(profile, duration)
        if profile.get("cross_scene_in") and transition_duration > 0:
            filters.append(f"fade=t=in:st=0:d={transition_duration:.2f}:color=white")
        if profile.get("cross_scene_out") and transition_duration > 0:
            start = max(0.0, duration - transition_duration)
            filters.append(f"fade=t=out:st={start:.2f}:d={transition_duration:.2f}:color=white")
        return ",".join(part for part in filters if part)

    def _post_filter(self, shot: dict) -> str:
        profile = shot.get("post_profile") or {}
        scene_group = str(profile.get("scene_group_id") or shot.get("scene_group_id") or "project_scene")
        digest = int(hashlib.sha1(scene_group.encode("utf-8", errors="ignore")).hexdigest()[:8], 16)
        saturation = self._profile_number(profile.get("saturation"), 0.98 + (digest % 7) * 0.01, 0.94, 1.08)
        contrast = 1.00 + ((digest // 7) % 5) * 0.005
        brightness = (((digest // 35) % 5) - 2) * 0.002
        sharpness = self._profile_number(profile.get("sharpness"), 0.34 + ((digest // 175) % 7) * 0.025, 0.25, 0.55)
        return (
            f"eq=saturation={saturation:.3f}:contrast={contrast:.3f}:brightness={brightness:.3f},"
            f"unsharp=5:5:{sharpness:.3f}:3:3:0.0"
        )

    def _cross_scene_transition_duration(self, profile: dict, duration: float) -> float:
        requested = self._profile_number(profile.get("cross_scene_flash_seconds"), 0.35, 0.3, 0.5)
        if duration <= 0:
            return 0.0
        if duration < 0.6:
            return max(0.1, duration / 2)
        return min(requested, duration / 2)

    def _profile_number(self, value, fallback: float, low: float, high: float) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError):
            number = fallback
        return min(high, max(low, number))

    def _get_resolution(self, resolution: str, fmt: str) -> tuple[int, int]:
        sizes = {"720p": 720, "1080p": 1080, "2k": 1440, "4k": 2160}
        height = sizes.get(resolution, 1080)
        ratio = {"9:16": 9 / 16, "16:9": 16 / 9, "1:1": 1}.get(fmt, 9 / 16)
        width = int(height * ratio)
        return width - width % 2, height - height % 2

    async def _run(self, args: list[str]) -> None:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            _, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=max(30, int(settings.FFMPEG_TIMEOUT_SECONDS)),
            )
        except asyncio.CancelledError:
            # Cancelling the coroutine does not automatically terminate an
            # asyncio subprocess. Reap it before propagating cancellation so
            # project deletion cannot leave an encoder writing in the background.
            if proc.returncode is None:
                proc.kill()
            await proc.communicate()
            raise
        except asyncio.TimeoutError as exc:
            proc.kill()
            await proc.communicate()
            raise TimeoutError("FFmpeg 执行超时") from exc
        except asyncio.CancelledError:
            proc.kill()
            await proc.communicate()
            raise
        if proc.returncode != 0:
            message = stderr.decode("utf-8", errors="ignore")[-2000:]
            raise RuntimeError(f"FFmpeg 执行失败: {message}")

    def _media_path(self, value: str | None, minimum_size: int = 1) -> Path | None:
        if not value:
            return None
        return existing_file(
            value,
            minimum_size=minimum_size,
            allowed_roots=(settings.OUTPUT_DIR, settings.ASSETS_DIR, settings.DATA_DIR),
        )

import asyncio
import hashlib
from pathlib import Path

from config import settings


class FFmpegService:
    """Render shot images and optional audio into a short MP4."""

    def __init__(self):
        self.output_dir = settings.OUTPUT_DIR / "projects"
        self.fps = settings.DEFAULT_FPS

    async def compose_video(
        self,
        shots: list[dict],
        output_format: str = "9:16",
        resolution: str = "1080p",
        project_id: str = "",
    ) -> str:
        video_dir = self.output_dir / project_id / "output"
        video_dir.mkdir(parents=True, exist_ok=True)
        width, height = self._get_resolution(resolution, output_format)

        clip_paths: list[Path] = []
        for index, shot in enumerate(shots):
            if shot.get("video_path"):
                clip_paths.append(await self._normalize_video_clip(shot, width, height, index, video_dir))
                continue
            if not shot.get("image_path"):
                continue
            clip_paths.append(await self._render_shot_clip(shot, width, height, index, video_dir))

        if not clip_paths:
            raise ValueError("没有可渲染的镜头图片")

        final_path = await self._concat_clips(clip_paths, video_dir)
        final_path = await self._add_continuous_ambient_bed(final_path, video_dir)
        return str(final_path)

    async def _render_shot_clip(self, shot: dict, width: int, height: int, index: int, output_dir: Path) -> Path:
        clip_path = output_dir / f"clip_{index:04d}.mp4"
        duration = max(0.5, float(shot.get("duration") or 3.0))
        frames = max(1, int(duration * self.fps))
        image_path = str(shot["image_path"])
        video_filter = self._clip_filter(
            self._zoom_filter(shot.get("shot_type", "medium"), width, height, frames),
            shot,
            duration,
        )

        audio_path = Path(shot["audio_path"]) if shot.get("audio_path") else None
        if audio_path and audio_path.exists():
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
        video_path = str(shot["video_path"])
        audio_path = Path(shot["audio_path"]) if shot.get("audio_path") else None
        if audio_path and audio_path.exists():
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
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            message = stderr.decode("utf-8", errors="ignore")[-2000:]
            raise RuntimeError(f"FFmpeg 执行失败: {message}")
